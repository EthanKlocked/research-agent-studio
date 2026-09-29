import asyncio
import pytest

async def run_case(scenario="pass", **kwargs):
    from backend.manager import RunManager
    from backend.config import Settings
    from backend.schemas import RunRequest
    manager = RunManager(Settings(test_mode=True, **kwargs))
    snapshot = await manager.start(RunRequest(question="Apple FY2024 Q4 매출과 위험은?", mode="test", scenario=scenario))
    await manager.tasks[snapshot["run_id"]]
    return manager, manager.snapshot(snapshot["run_id"])

@pytest.mark.parametrize("scenario,status", [("pass", "success"), ("revise", "success"), ("limit", "limit_reached"), ("empty", "empty"), ("tool_error", "error"), ("timeout", "error")])
async def test_real_graph_scenarios(scenario, status):
    manager, result = await run_case(scenario, model_timeout=0.4 if scenario == "timeout" else 15)
    assert result["status"] == status, result
    assert result["finished_at"]
    events = list(manager.runs[result["run_id"]].events)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "terminal"
    assert all(e["data"]["snapshot"]["run_id"] == result["run_id"] for e in events)
    if status in ("success", "limit_reached"):
        assert result["report"]["claims"]
        assert any(e["type"] == "tool_complete" for e in events)
        ids = {e["id"] for e in result["evidence"]}
        assert all(set(c["citation_ids"]) <= ids for c in result["report"]["claims"])
    if scenario == "revise":
        assert result["iteration"] == 2
        assert len(result["revisions"]) == 2
        assert result["revisions"][1]["added_evidence_ids"]
        assert set(result["revisions"][0]["evidence_ids"]) < set(result["revisions"][1]["evidence_ids"])
        planners = [e for e in events if e["type"] == "node_start" and e["data"]["snapshot"]["stage"] == "Planner"]
        assert len(planners) == 2
        assert planners[1]["data"]["snapshot"]["feedback"]
    if scenario == "limit":
        assert result["iteration"] == 2
        assert result["report"]["limitations"]
    if scenario == "empty":
        assert result["errors"] == [] and result["evidence"] == []
    if scenario in ("tool_error", "timeout"):
        assert result["errors"]

async def test_cancel_isolation_and_concurrency():
    from backend.manager import RunManager, RunRejected
    from backend.config import Settings
    from backend.schemas import RunRequest
    m = RunManager(Settings(test_mode=True, max_concurrent=2))
    a = await m.start(RunRequest(question="first", mode="test", scenario="timeout"))
    b = await m.start(RunRequest(question="second", mode="test", scenario="timeout"))
    with pytest.raises(RunRejected):
        await m.start(RunRequest(question="third", mode="test"))
    await m.cancel(a["run_id"])
    assert m.snapshot(a["run_id"])["status"] == "cancelled"
    assert m.tasks[a["run_id"]].done()
    assert m.snapshot(b["run_id"])["status"] in ("queued", "running")
    await m.cancel(b["run_id"])
    copy = m.snapshot(a["run_id"])
    copy["errors"].append("modified")
    assert "modified" not in m.snapshot(a["run_id"])["errors"]

async def test_model_validation_and_provider_errors_are_not_success(monkeypatch):
    from backend.agents import RoleRunner
    original = RoleRunner.invoke
    for role, bad in [("Reporter", {"title":"x", "summary":"x", "claims":[{"text":"x", "citation_ids":["invented"]}], "limitations":[]}), ("Evaluator", {"decision":"maybe", "issues":[], "follow_up":[]}), ("Listener", RuntimeError("sensitive-config-secret"))]:
        async def broken(self, current_role, state, tools, role=role, bad=bad):
            if current_role == role:
                if isinstance(bad, Exception):
                    raise bad
                return bad
            return await original(self, current_role, state, tools)
        monkeypatch.setattr(RoleRunner, "invoke", broken)
        _, result = await run_case()
        assert result["status"] == "error"
        assert "sensitive-config-secret" not in str(result)

async def test_run_timeout_and_memory_bound():
    _, result = await run_case("timeout", run_timeout=0.05)
    assert result["status"] == "error"
    from backend.manager import RunManager
    from backend.config import Settings
    from backend.schemas import RunRequest
    m = RunManager(Settings(test_mode=True, max_runs=2))
    for _ in range(3):
        r = await m.start(RunRequest(question="cancel", mode="test", scenario="timeout"))
        await m.cancel(r["run_id"])
    assert len(m.runs) == len(m.tasks) == 2
