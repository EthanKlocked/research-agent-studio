"""Offline scope contracts: model decision, not heuristics or tool-error mapping."""
import json

import pytest
from pydantic import ValidationError

from backend.agents import RoleRunner
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import Interpretation, RunRequest
from test_live_resilience import SETTINGS, install_provider


def test_scope_is_closed_typed_and_legacy_interpretations_remain_valid():
    assert Interpretation.model_validate({"interpreted_request": "legacy"})
    for scope in ("in_scope", "partial", "unknown", "out_of_scope"):
        value = Interpretation.model_validate({"interpreted_request": "topic", "scope": scope})
        assert value.scope == scope
    for invalid in (True, "unsupported", {"status": "out_of_scope"}):
        with pytest.raises(ValidationError):
            Interpretation.model_validate({"interpreted_request": "topic", "scope": invalid})


async def test_explicit_live_scope_stops_before_discovery_and_tools(monkeypatch):
    monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", "0")
    requests, clients = install_provider(monkeypatch, lambda _: {"content": json.dumps({
        "interpreted_request": "오늘 서울 날씨는 허용된 역사적 기업 자료로 답할 수 없습니다.",
        "scope": "out_of_scope",
    })})
    async def forbidden(*args, **kwargs):
        pytest.fail("Out-of-scope request must stop before MCP discovery")
    monkeypatch.setattr("backend.mcp_client.DocumentClient.load_tools", forbidden)
    manager = RunManager(Settings(**SETTINGS))
    initial = await manager.start(RunRequest(question="오늘 서울 날씨는?"))
    await manager.tasks[initial["run_id"]]
    final = manager.snapshot(initial["run_id"])
    assert final["status"] == "out_of_scope", final["errors"]
    assert final["stage"] == "Listener" and final["iteration"] == 0
    assert final["errors"] == [] and final["report"] is None and not final["evidence"]
    assert final["finished_at"]
    events = list(manager.runs[initial["run_id"]].events)
    assert sum(e["type"] == "terminal" for e in events) == 1
    assert events[-1]["data"]["snapshot"] == final
    assert not any(e["type"] in ("tool_error", "discovery_start", "tool_start") for e in events)
    assert len(requests) == 1 and all(c.is_closed for c in clients)
    system = requests[0]["messages"][0]["content"]
    assert "out_of_scope" in system and "partial" in system and "unknown" in system
    payload = json.loads(next(m["content"] for m in requests[0]["messages"] if m["role"] == "user"))
    assert payload["dataset"]["available_documents"]


@pytest.mark.parametrize("scope", [None, "unknown", "in_scope", "partial"])
async def test_non_rejected_scope_continues_historical_fixture(monkeypatch, scope):
    original = RoleRunner.invoke
    async def invoke(self, role, state, tools, middleware=()):
        value = await original(self, role, state, tools, middleware)
        if role == "Listener" and scope is not None:
            value["scope"] = scope
        return value
    monkeypatch.setattr(RoleRunner, "invoke", invoke)
    manager = RunManager(Settings(test_mode=True))
    initial = await manager.start(RunRequest(question="historical revenue plus unavailable comparison", mode="test"))
    await manager.tasks[initial["run_id"]]
    final = manager.snapshot(initial["run_id"])
    assert final["status"] == "success", final["errors"]
    assert final["report"] and final["evidence"]
    assert "scope" not in final  # transient classification, existing snapshot shape


async def test_general_enabled_does_not_apply_closed_corpus_rejection(monkeypatch):
    # Exercise real graph routing without any general-web network session.
    from backend.workflow import build_graph
    from test_live_resilience import STATE
    stages = []
    async def invoke(self, role, state, tools, middleware=()):
        stages.append(role)
        if role == "Listener":
            return {"interpreted_request": "general topic", "scope": "out_of_scope"}
        raise RuntimeError("stop after routing")
    monkeypatch.setattr(RoleRunner, "invoke", invoke)
    class Inventory:
        async def remaining_web_budget(self):
            return {"search":6, "read":8, "status":"available"}
        async def load_tools(self):
            return []
    monkeypatch.setattr("backend.workflow.planner_tool_metadata", lambda tools: [])
    async def publish(*args):
        pass
    graph = build_graph(Settings(**SETTINGS, search_provider="exa", exa_api_key="test-only"),
                        "live", "pass", publish, persistent_client=Inventory())
    with pytest.raises(RuntimeError, match="stop after routing"):
        await graph.ainvoke({**STATE, "status": "queued", "stage": None})
    assert stages == ["Listener", "Planner"]


@pytest.mark.parametrize("scope", ["partial", "unknown", "out_of_scope_invalid"])
async def test_scope_cannot_hide_provider_failures_or_invalid_output(monkeypatch, scope):
    def respond(body):
        if "Interpret the user's" in body["messages"][0]["content"]:
            return {"content": json.dumps({"interpreted_request": "topic", "scope": scope})}
        raise ConnectionError("private transport detail")
    requests, clients = install_provider(monkeypatch, respond)
    monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", "0")
    manager = RunManager(Settings(**SETTINGS))
    initial = await manager.start(RunRequest(question="topic"))
    await manager.tasks[initial["run_id"]]
    final = manager.snapshot(initial["run_id"])
    assert final["status"] == "error" and final["errors"]
    assert "private transport detail" not in str(final)
    assert ("Listener/validation" in final["errors"][0]) == (scope == "out_of_scope_invalid")
    assert all(c.is_closed for c in clients)


async def test_missing_classification_and_no_tool_use_still_is_tool_error(monkeypatch):
    from test_live_resilience import run_provider
    final, events, _ = await run_provider(monkeypatch, [])
    assert final["status"] == "error"
    assert "Researcher/tool" in final["errors"][0]
    assert events[-1]["type"] == "terminal"
