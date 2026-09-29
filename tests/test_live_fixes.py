"""Offline regressions: mock HTTP provider, real agent/graph/MCP."""
import json
import pytest
from backend.agents import RoleRunner
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest
from mcp_server.server import search_documents
from test_live_resilience import SETTINGS, STATE, install_provider, run_provider, SEARCH, DATA


def test_search_metadata_requires_retrieval():
    hits = search_documents("revenue")
    assert hits and all("excerpt" not in hit and "keywords" not in hit for hit in hits)
    assert all(hit["document_id"] and hit["section_id"] for hit in hits)


async def test_search_hits_without_retrieval_is_not_empty(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [SEARCH])
    assert state["status"] == "error"
    assert "Researcher/retrieval_incomplete" in state["errors"][0]
    assert state["evidence"] == []


@pytest.mark.parametrize("role,valid,field", [
    ("Planner", {"plan":["short"]}, "plan"),
    ("Evaluator", {"decision":"pass", "issues":[], "follow_up":[]}, "issues"),
])
async def test_schema_retry_once_with_sanitized_feedback(monkeypatch, role, valid, field):
    bad = {**valid, field:["private-secret"*30], "private-secret-key":"private-secret-value"}
    responses = iter([bad, valid])
    requests, clients = install_provider(monkeypatch, lambda _: {"content":json.dumps(next(responses))})
    assert await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke(role, STATE, []) == valid
    assert len(requests) == 2
    prompt = requests[0]["messages"][0]["content"]
    assert f"{field}[]" in prompt and "300 characters" in prompt
    retry = json.dumps(requests[1])
    assert "private-secret" not in retry
    assert "validation_feedback" in retry and "string_too_long" in retry
    assert all(c.is_closed for c in clients)


async def test_exhausted_validation_has_safe_role_category(monkeypatch):
    requests, clients = install_provider(monkeypatch, lambda _: {"content":'{"interpreted_request":42}'})
    manager = RunManager(Settings(**SETTINGS))
    state = await manager.start(RunRequest(question="revenue"))
    await manager.tasks[state["run_id"]]
    final = manager.snapshot(state["run_id"])
    assert final["status"] == "error"
    assert "Listener/validation" in final["errors"][0]
    assert len(requests) == 2 and all(c.is_closed for c in clients)


async def test_all_roles_receive_dataset_scope(monkeypatch):
    from test_live_resilience import GOOD
    state, _, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state["status"] == "success"
    for request in requests:
        payload = json.loads(next(m["content"] for m in request["messages"] if m["role"] == "user"))
        scope = payload["dataset"]
        assert scope["name"] == DATA["name"] and scope["as_of"] == DATA["as_of"]
        assert {d["document_id"] for d in scope["available_documents"]} == {s["document_id"] for s in DATA["sections"]}
        assert "excerpt" not in json.dumps(scope)
        assert "completed historical quarter" in scope["period_note"]
        assert {d["published_at"] for d in scope["available_documents"]} == {s["published_at"] for s in DATA["sections"]}


async def test_configured_output_tokens_reach_provider(monkeypatch):
    requests, _ = install_provider(monkeypatch, lambda _: {"content":'{"interpreted_request":"ok"}'})
    await RoleRunner(Settings(**SETTINGS, max_output_tokens=8192), "live", "pass").invoke("Listener", STATE, [])
    assert requests[0].get("max_completion_tokens", requests[0].get("max_tokens")) == 8192


@pytest.mark.parametrize("value", ["0", "-1", "abc", "65537"])
def test_invalid_output_token_env_rejected(monkeypatch, value):
    monkeypatch.setattr("backend.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", value)
    with pytest.raises(ValueError, match="LLM_MAX_OUTPUT_TOKENS"):
        Settings.from_env()


@pytest.mark.parametrize("value", [None, "", " ", "\t\n "])
def test_blank_or_missing_output_token_env_uses_default(monkeypatch, value):
    monkeypatch.setattr("backend.config.load_dotenv", lambda *a, **kw: None)
    if value is None:
        monkeypatch.delenv("LLM_MAX_OUTPUT_TOKENS", raising=False)
    else:
        monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", value)
    assert Settings.from_env().max_output_tokens == 8192


def test_output_token_env(monkeypatch):
    monkeypatch.setattr("backend.config.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "8192")
    assert Settings.from_env().max_output_tokens == 8192


async def test_length_finish_reason_is_not_json_validation(monkeypatch):
    requests, clients = install_provider(monkeypatch, lambda _: {"content":"", "_finish_reason":"length"})
    manager = RunManager(Settings(**SETTINGS))
    state = await manager.start(RunRequest(question="revenue"))
    await manager.tasks[state["run_id"]]
    final = manager.snapshot(state["run_id"])
    assert final["status"] == "error"
    assert "Listener/output_limit" in final["errors"][0]
    assert len(requests) == 1 and all(c.is_closed for c in clients)

async def test_json_repair_does_not_echo_invalid_output(monkeypatch):
    responses = iter(["private-secret-not-json", '{"interpreted_request":"ok"}'])
    requests, _ = install_provider(monkeypatch, lambda _: {"content":next(responses)})
    assert await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Listener", STATE, []) == {"interpreted_request":"ok"}
    assert len(requests) == 2 and "private-secret" not in json.dumps(requests[1])


async def test_length_tool_call_never_executes_tools_or_retries(monkeypatch):
    from langchain_core.tools import tool
    from test_live_resilience import tool_call
    called = []
    @tool
    async def search_documents(query: str) -> list:
        """Search fixture."""
        called.append(query)
        return []
    requests, clients = install_provider(monkeypatch, lambda _: {**tool_call("search_documents", {"query":"revenue"}, 0), "_finish_reason":"length"})
    from backend.errors import OutputLimit
    with pytest.raises(OutputLimit):
        await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Researcher", STATE, [search_documents])
    assert not called and len(requests) == 1 and all(c.is_closed for c in clients)


async def test_provider_failure_not_retried_or_logged_raw(monkeypatch, caplog):
    def respond(_):
        raise RuntimeError("private-secret https://secret.invalid/?token=secret")
    requests, clients = install_provider(monkeypatch, respond)
    manager = RunManager(Settings(**SETTINGS))
    state = await manager.start(RunRequest(question="revenue"))
    await manager.tasks[state["run_id"]]
    final = manager.snapshot(state["run_id"])
    assert "Listener/provider_or_execution" in final["errors"][0]
    assert "role=Listener category=provider_or_execution" in caplog.text
    assert "private-secret" not in caplog.text + json.dumps(list(manager.runs[state["run_id"]].events))
    assert len(requests) == 1 and all(c.is_closed for c in clients)
