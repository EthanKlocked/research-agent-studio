import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def make_app(test_mode=True, **kwargs):
    from backend.api import create_app
    from backend.config import Settings
    return create_app(Settings(test_mode=test_mode, **kwargs))

def test_configuration_gates_validation_and_no_leak():
    with TestClient(make_app(False)) as c:
        config = c.get("/api/config").json()
        assert config["configured"] is False
        assert config["test_mode_available"] is False
        assert c.post("/api/runs", json={"question":"x", "mode":"live"}).status_code == 409
        assert c.post("/api/runs", json={"question":"x", "mode":"test"}).status_code == 403
        for body in [{"question":""}, {"question":"x"*2001}, {"question":"x", "scenario":"unknown"}, {"question":"x", "endpoint":"https://bad"}]:
            assert c.post("/api/runs", json=body).status_code == 422
        assert c.get("/api/runs/nope").status_code == 404
        assert "api_key" not in str(config)

def test_events_terminal_and_snapshot_recovery():
    with TestClient(make_app()) as c:
        r = c.post("/api/runs", json={"question":"Apple Q4 performance risk", "mode":"test", "scenario":"revise"})
        assert r.status_code == 202
        rid = r.json()["run_id"]
        response = c.get(f"/api/runs/{rid}/events?after=0")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "terminal"
        assert sum(e["type"] == "terminal" for e in events) == 1
        assert {"model_start", "model_complete", "validation_start", "validation_complete", "discovery_start", "discovery_complete"} <= {e["type"] for e in events}
        # Provisional evaluator success must not hide branch/terminal delivery.
        success = next(i for i,e in enumerate(events) if e["data"]["snapshot"]["status"] == "success")
        assert not events[success]["data"]["snapshot"]["finished_at"]
        assert any(e["type"] == "branch" for e in events[success + 1:])
        cursor = next(e["seq"] for e in events if e["type"] == "model_start")
        replay = c.get(f"/api/runs/{rid}/events?after={cursor}")
        replayed = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
        assert replayed == [e for e in events if e["seq"] > cursor]
        assert all("snapshot" in e["data"] for e in events)
        snapshot = c.get(f"/api/runs/{rid}").json()
        assert snapshot == events[-1]["data"]["snapshot"]
        recovered = c.get(f"/api/runs/{rid}/events?after={events[-2]['seq']}")
        assert '"type":"terminal"' in recovered.text
        assert c.get(f"/api/runs/{rid}/events?after={snapshot['last_seq']}").text == ""
        assert set(snapshot) == {"run_id","question","mode","status","stage","iteration","started_at","finished_at","last_seq","interpreted_request","plan","evidence","report","revisions","evaluation","feedback","errors","partial_result","unavailable_sources","cost_summary"}
        assert snapshot["partial_result"] is None

@pytest.mark.asyncio
async def test_role_scope_resolves_public_optin_after_import(monkeypatch):
    from backend.agents import RoleRunner
    from backend.config import Settings
    from backend.mcp_client import DATA, get_dataset_scope
    from mcp_server.public_sources import PUBLIC_SECTION_IDS
    from test_live_resilience import SETTINGS, STATE, install_provider
    requests, _ = install_provider(monkeypatch, lambda _: {"content": '{"interpreted_request":"ok"}'})
    for enabled in ("0", "1", "0"):
        monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", enabled)
        await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Listener", STATE, [])
        scope = json.loads(next(m["content"] for m in requests[-1]["messages"] if m["role"] == "user"))["dataset"]
        assert scope == get_dataset_scope()
        expected_ids = {(s["document_id"], s["section_id"]) for s in DATA["sections"]}
        assert {(s["document_id"], s["section_id"]) for s in scope["available_documents"]} == expected_ids | (PUBLIC_SECTION_IDS if enabled == "1" else set())


@pytest.mark.asyncio
async def test_test_mode_keeps_scope_and_real_mcp_offline_with_public_optin(monkeypatch):
    from contextlib import asynccontextmanager
    from backend import mcp_client
    from backend.agents import FixtureModel
    from backend.config import Settings
    from backend.manager import RunManager
    from backend.schemas import RunRequest
    from langchain_core.messages import HumanMessage
    monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", "1")
    scopes, environments = [], []
    original_generate, original_stdio = FixtureModel._generate, mcp_client.stdio_client
    def generate(self, messages, *args, **kwargs):
        scopes.append(json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))["dataset"])
        return original_generate(self, messages, *args, **kwargs)
    @asynccontextmanager
    async def stdio(params, **kwargs):
        environments.append(params.env)
        assert params.env.get("RESEARCH_PUBLIC_SOURCES") != "1", "test subprocess must not enable network"
        async with original_stdio(params, **kwargs) as streams:
            yield streams
    monkeypatch.setattr(FixtureModel, "_generate", generate)
    monkeypatch.setattr(mcp_client, "stdio_client", stdio)
    manager = RunManager(Settings(test_mode=True))
    initial = await manager.start(RunRequest(question="revenue", mode="test", scenario="pass"))
    await manager.tasks[initial["run_id"]]
    final = manager.snapshot(initial["run_id"])
    assert final["status"] == "success", final["errors"]
    assert environments and scopes
    assert all(s["public_sources_enabled"] is False for s in scopes)
    bundled = {(s["document_id"], s["section_id"]) for s in mcp_client.DATA["sections"]}
    assert all({(d["document_id"], d["section_id"]) for d in s["available_documents"]} == bundled for s in scopes)
    assert {(e["document_id"], e["section_id"]) for e in final["evidence"]} <= bundled


@pytest.mark.parametrize("value", ["", "  \t "])
def test_blank_pdf_parser_override_defaults_in_parent_and_server(monkeypatch, value):
    import httpx
    from backend import mcp_client
    from mcp_server import public_sources
    from test_public_sources import OPERATIONS
    monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", "1")
    monkeypatch.setenv("RESEARCH_PDFTOTEXT", value)
    lookups = []
    def which(name):
        lookups.append(name)
        return "/usr/bin/pdftotext" if name == "pdftotext" else None
    monkeypatch.setattr(mcp_client.shutil, "which", which)
    assert Path(mcp_client.document_environment()["RESEARCH_PDFTOTEXT"]).resolve() == Path("/usr/bin/pdftotext").resolve()
    async def decode(body, executable):
        assert Path(executable).resolve() == Path("/usr/bin/pdftotext").resolve()
        return OPERATIONS
    monkeypatch.setattr(public_sources, "_pdf_text", decode)
    store = public_sources.PublicSourceStore(enabled=True, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type":"application/pdf"}, content=b"%PDF-test")))
    assert "14,736" in store.get_section("apple-official-fy2024-q4", "operations")["excerpt"]
    assert lookups == ["pdftotext", "pdftotext"]


def test_failed_revision_api_and_sse_preserve_exact_partial_contract(monkeypatch):
    from backend.agents import RoleRunner
    original = RoleRunner.invoke
    async def invoke(self, role, state, tools, middleware=()):
        if role == "Planner" and state["iteration"] == 2:
            raise TimeoutError("private provider details")
        return await original(self, role, state, tools, middleware)
    monkeypatch.setattr(RoleRunner, "invoke", invoke)
    with TestClient(make_app()) as client:
        initial = client.post("/api/runs", json={"question":"revenue risk", "mode":"test", "scenario":"revise"}).json()
        assert initial["partial_result"] is None
        rid = initial["run_id"]
        response = client.get(f"/api/runs/{rid}/events")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        final = client.get(f"/api/runs/{rid}").json()
        assert final == events[-1]["data"]["snapshot"]
        assert events[-1]["type"] == "terminal"
        assert final["status"] == "error"
        assert final["partial_result"] == {"iteration":1, "reason":"revision_failed"}
        assert final["iteration"] == 2
        assert final["evaluation"] == final["revisions"][0]["evaluation"]
        assert final["evaluation"]["decision"] == "revise"
        assert final["report"]["claims"] == final["revisions"][0]["report"]["claims"]
        assert final["report"]["claims"] and final["evidence"]
        assert len(final["errors"]) == 1 and "Planner/timeout" in final["errors"][0]
        assert "private provider details" not in response.text


def test_out_of_scope_api_replay_and_snapshot_are_final_without_tool_error(monkeypatch):
    from backend.agents import RoleRunner
    async def invoke(self, role, state, tools, middleware=()):
        assert role == "Listener"
        return {"interpreted_request": "허용된 자료 밖의 질문", "scope": "out_of_scope"}
    monkeypatch.setattr(RoleRunner, "invoke", invoke)
    with TestClient(make_app()) as client:
        initial = client.post("/api/runs", json={"question": "오늘 날씨", "mode": "test"}).json()
        rid = initial["run_id"]
        response = client.get(f"/api/runs/{rid}/events")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        final = client.get(f"/api/runs/{rid}").json()
        assert final["status"] == "out_of_scope" and final["finished_at"]
        assert final["errors"] == [] and final["report"] is None
        assert [e["type"] for e in events] == ["node_start", "node_complete", "terminal"]
        assert not events[-2]["data"]["snapshot"]["finished_at"]
        assert final == events[-1]["data"]["snapshot"]
        replay = client.get(f"/api/runs/{rid}/events?after={events[-2]['seq']}")
        assert '"type":"terminal"' in replay.text
        assert client.get(f"/api/runs/{rid}/events?after={final['last_seq']}").text == ""


def test_api_cancellation_and_cross_origin_rejection():
    with TestClient(make_app()) as c:
        assert c.post("/api/runs", headers={"origin":"https://evil.example"}, json={"question":"x","mode":"test"}).status_code == 403
        r = c.post("/api/runs", json={"question":"x","mode":"test","scenario":"timeout"}).json()
        assert c.post(f"/api/runs/{r['run_id']}/cancel").json()["status"] == "cancelled"
        assert c.post(f"/api/runs/{r['run_id']}/cancel").json()["status"] == "cancelled"
