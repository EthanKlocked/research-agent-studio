"""Mock provider protocol, real ChatOpenAI/create_agent/graph/MCP; no live LLM."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

from backend.agents import RoleRunner
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest

SETTINGS = dict(provider="openai-compatible", model="mock-model", api_key="mock-key", base_url="http://127.0.0.1:9999/v1")
STATE = dict(question="revenue", interpreted_request="", plan=[], evidence=[], report=None, feedback=[], iteration=0)


def install_provider(monkeypatch, respond):
    requests, clients = [], []
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        message = respond(body)
        finish_reason = message.pop("_finish_reason", "tool_calls" if message.get("tool_calls") else "stop")
        return httpx.Response(200, json={"id":"mock", "object":"chat.completion", "created":0, "model":"mock-model", "choices":[{"index":0,"message":{"role":"assistant", **message},"finish_reason":finish_reason}]})
    def model(**kwargs):
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(transport), trust_env=False)
        kwargs["http_async_client"] = httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)
        clients.extend([kwargs["http_client"], kwargs["http_async_client"]])
        return ChatOpenAI(**kwargs)
    monkeypatch.setattr("backend.agents.ChatOpenAI", model)
    return requests, clients


@pytest.mark.parametrize("wrapper", [lambda s:s, lambda s:' \n```json\n'+s+'\n``` \n', lambda s:'```\n'+s+'\n```'])
async def test_single_object_output(monkeypatch, wrapper):
    requests, clients = install_provider(monkeypatch, lambda _: {"content":wrapper('{"interpreted_request":"ok"}')})
    assert await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Listener", STATE, []) == {"interpreted_request":"ok"}
    assert all(c.is_closed for c in clients)
    assert "response_format" not in requests[0]


@pytest.mark.parametrize("content", ['[]','null','{} {}','prose {"interpreted_request":"ok"}', '```json\n{}\n``` trailing', '```json\n{}\n```\n```json\n{}\n```', '{"interpreted_request":', '```python\n{}\n```', 'x'*24001, [{"type":"text", "text":"{}"}]])
async def test_invalid_output_rejected(monkeypatch, content):
    install_provider(monkeypatch, lambda _: {"content":content})
    with pytest.raises((ValueError, TypeError)):
        await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Listener", STATE, [])


def tool_call(name, args, index):
    return {"content":None, "tool_calls":[{"id":f"call-{index}", "type":"function", "function":{"name":name,"arguments":json.dumps(args)}}]}


async def run_provider(monkeypatch, sequence, cancel_event=None, **settings):
    def respond(body):
        system = body["messages"][0]["content"]
        state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
        if "Interpret the user's" in system:
            value = {"interpreted_request":"historical revenue"}
        elif "Produce up to" in system:
            value = {"plan":["revenue"]}
        elif "Search documents" in system:
            count = sum(m["role"] == "tool" for m in body["messages"])
            if count < len(sequence):
                name, args = sequence[count]
                return tool_call(name, args, count)
            value = {"summary":"done"}
        elif "Write a concise" in system:
            value = {"title":"report", "summary":"summary", "claims":[{"text":"revenue", "citation_ids":[state["evidence"][0]["id"]]}], "limitations":[]}
        else:
            value = {"decision":"pass", "issues":[], "follow_up":[]}
        return {"content":"```json\n"+json.dumps(value)+"\n```"}
    requests, clients = install_provider(monkeypatch, respond)
    manager = RunManager(Settings(**SETTINGS, **settings))
    state = await manager.start(RunRequest(question="revenue", mode="live"))
    if cancel_event is not None:
        await asyncio.wait_for(cancel_event.wait(), 10)
        await manager.cancel(state["run_id"])
    await manager.tasks[state["run_id"]]
    assert all(c.is_closed for c in clients)
    return manager.snapshot(state["run_id"]), list(manager.runs[state["run_id"]].events), requests


async def test_unknown_tool_name_is_not_public(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [("private-secret", {})])
    assert state["status"] == "error"
    assert "private-secret" not in json.dumps(events)


@pytest.mark.parametrize("failure", ["remote_error", "transport", "timeout", "cancel"])
async def test_provider_real_stdio_fatal_failures(monkeypatch, failure):
    from mcp import ClientSession
    from mcp.types import CallToolResult, TextContent
    original = ClientSession.call_tool
    calls = []
    entered = asyncio.Event()
    async def fail(self, name, arguments, *args, **kwargs):
        calls.append(name)
        # Actual MCP initialize already succeeded before this injection.
        if failure == "remote_error":
            return CallToolResult(isError=True, content=[TextContent(type="text", text="Unknown document private-secret")])
        if failure == "transport":
            raise ConnectionError("private-secret")
        if failure == "cancel":
            entered.set()
            await asyncio.Event().wait()
        await asyncio.sleep(10)
        return await original(self, name, arguments, *args, **kwargs)
    monkeypatch.setattr(ClientSession, "call_tool", fail)
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD], cancel_event=entered if failure == "cancel" else None, mcp_timeout=2 if failure == "timeout" else 10)
    assert state["status"] == ("cancelled" if failure == "cancel" else "error"), state
    assert calls == ["search_documents"]
    assert state["report"] is None and state["evidence"] == []
    assert not any(e["type"] in ("tool_error", "tool_complete") for e in events)
    assert "private-secret" not in json.dumps(events)


@pytest.mark.parametrize("role,value", [("Listener", {"interpreted_request":42}), ("Evaluator", {"decision":"maybe", "issues":[], "follow_up":[]}), ("Reporter", {"title":"x", "summary":"x", "claims":[{"text":"x", "citation_ids":["invented"]}], "limitations":[]})])
async def test_fenced_output_still_requires_schema_and_citations(monkeypatch, role, value):
    from backend.schemas import ROLE_SCHEMAS, validate_citations
    install_provider(monkeypatch, lambda _: {"content":"```json\n"+json.dumps(value)+"\n```"})
    with pytest.raises(ValueError):
        raw = await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke(role, STATE, [])
        validated = ROLE_SCHEMAS[role].model_validate(raw).model_dump()
        validate_citations(validated, [])


async def test_search_alone_cannot_clear_failed_retrieval(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [GOOD, BAD, SEARCH])
    assert state["status"] == "error"
    assert state["evidence"] == []


@pytest.mark.parametrize("args", [{"query":"x"*301}, {"query":""}, {"query":"revenue", "limit":True}, {"query":"revenue", "limit":6}, {"query":"revenue", "limit":"2"}])
async def test_invalid_attempts_share_total_budget(monkeypatch, args):
    state, events, _ = await run_provider(monkeypatch, [("search_documents",args), GOOD], max_tool_calls=1)
    assert state["status"] == "error"
    assert sum(e["type"] == "tool_error" for e in events) == 1
    assert not any(e["type"] == "tool_complete" for e in events)


async def test_two_corrections_can_succeed(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [BAD, SEARCH, BAD, GOOD])
    assert state["status"] == "success"
    assert sum(e["type"] == "tool_error" for e in events) == 2


async def test_normal_empty_search_is_not_an_error(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [("search_documents", {"query":"nonexistentxyz"})])
    assert state["status"] == "empty"
    assert not any(e["type"] == "tool_error" for e in events)
    assert any(e["type"] == "tool_complete" and e["data"]["count"] == 0 for e in events)


DATA = json.loads((Path(__file__).resolve().parents[1]/"data/apple_fy2024.json").read_text(encoding="utf-8"))
GOOD = ("get_section", {k:DATA["sections"][0][k] for k in ("document_id","section_id")})
BAD = ("get_section", {"document_id":"private-secret", "section_id":"missing"})
SEARCH = ("search_documents", {"query":"revenue"})


@pytest.mark.parametrize("prefix", [[], [BAD], [("search_documents", {"query":42})], [("get_section", {})], [("search_documents", {"query":"revenue", "extra":"private-secret"})]])
async def test_real_stdio_provider_correction(monkeypatch, prefix):
    state, events, requests = await run_provider(monkeypatch, prefix+[SEARCH, GOOD])
    assert state["status"] == "success", state
    assert len(state["evidence"]) == 1
    errors = [e for e in events if e["type"] == "tool_error"]
    assert len(errors) == len(prefix)
    for event in errors:
        assert event["data"]["reason"] == "입력 오류로 재조회가 필요합니다."
        assert set(event["data"]) == {"tool", "reason", "snapshot"}
    assert "private-secret" not in json.dumps(events)
    tool_messages = [m for r in requests for m in r["messages"] if m["role"] == "tool"]
    assert tool_messages
    if prefix:
        assert any(json.loads(m["content"]).get("error") for m in tool_messages if isinstance(json.loads(m["content"]), dict))


@pytest.mark.parametrize("sequence,settings", [([BAD],{}), ([GOOD,BAD],{}), ([BAD,BAD,BAD,GOOD],{}), ([BAD,SEARCH,GOOD],{"max_tool_calls":2}), ([BAD,GOOD],{"max_tool_corrections":0}), ([("shell", {"command":"private-secret"}),GOOD],{})])
async def test_unresolved_exhausted_and_unknown_are_fatal(monkeypatch, sequence, settings):
    state, events, requests = await run_provider(monkeypatch, sequence, **settings)
    assert state["status"] == "error", state
    assert state["report"] is None
    assert not state["evidence"]
    assert "private-secret" not in json.dumps(events)


def test_default_tool_budgets():
    settings = Settings()
    assert (settings.max_tool_calls, settings.max_tool_corrections, settings.mcp_timeout) == (12,2,10)
