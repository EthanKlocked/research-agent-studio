import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def test_dataset_original_summaries_provenance():
    data = json.loads((Path(__file__).resolve().parents[1] / "data/apple_fy2024.json").read_text())
    assert data["acquired_at"] == "2026-09-29"
    assert "Original factual summaries" in data["scope"]
    assert len({s["id"] for s in data["sections"]}) == len(data["sections"])
    assert any("sec.gov" in s["url"] for s in data["sections"])
    assert any(s["section_id"] == "annual" for s in data["sections"])
    for s in data["sections"]:
        assert all(s[k] for k in ("published_at", "as_of", "url", "excerpt"))
        assert len(s["excerpt"]) < 1200


def test_settings_invalid_endpoint_does_not_raise():
    from backend.config import Settings
    for url in ("http://[malformed", "file:///etc/passwd", "http://remote.example", "https://name:pass@example.com", "https://example.com/?key=x"):
        assert not Settings(provider="openai", model="placeholder", api_key="placeholder", base_url=url).configured


def test_provider_adapter_explicit_settings_without_network(monkeypatch):
    from backend.agents import AgentFactory
    from backend.config import Settings
    from langchain_openai import ChatOpenAI
    settings = Settings(provider="openai-compatible", model="test-placeholder-model", api_key="test-placeholder-key", base_url="http://127.0.0.1:9999/v1")
    captured = {}
    def capture(**kwargs):
        captured.update(kwargs)
        return ChatOpenAI(**kwargs)
    monkeypatch.setattr("backend.agents.ChatOpenAI", capture)
    AgentFactory(settings, "live", "pass").create("Listener", [])
    assert captured["api_key"] == "test-placeholder-key"
    assert captured["base_url"] == "http://127.0.0.1:9999/v1"
    assert captured["max_retries"] == 0
    assert captured["organization"] == ""
    assert captured["http_async_client"].trust_env is False
    with pytest.raises(ValueError):
        AgentFactory(settings, "live", "pass").create("Reporter", [lambda:None])


async def test_provider_real_adapter_mock_transport_success_and_failure(monkeypatch):
    import httpx
    from langchain_openai import ChatOpenAI
    from backend.agents import RoleRunner
    from backend.config import Settings
    settings = Settings(provider="openai-compatible", model="placeholder", api_key="placeholder", base_url="http://127.0.0.1:9999/v1")
    state = dict(question="Apple revenue", interpreted_request="", plan=[], evidence=[], report=None, feedback=[], iteration=0)
    for status in (200, 401):
        calls = []
        def transport(request):
            calls.append(request)
            if status != 200:
                return httpx.Response(status, json={"error":{"message":"private-provider-error", "type":"authentication_error", "code":"invalid_api_key"}})
            return httpx.Response(200, json={"id":"test-response", "object":"chat.completion", "created":0, "model":"placeholder", "choices":[{"index":0,"message":{"role":"assistant","content":'{"interpreted_request":"Apple historical revenue"}'},"finish_reason":"stop"}]})
        def model(**kwargs):
            kwargs["http_async_client"] = httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)
            kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(transport), trust_env=False)
            return ChatOpenAI(**kwargs)
        monkeypatch.setattr("backend.agents.ChatOpenAI", model)
        runner = RoleRunner(settings, "live", "pass")
        if status == 200:
            assert (await runner.invoke("Listener", state, []))["interpreted_request"] == "Apple historical revenue"
        else:
            with pytest.raises(Exception):
                await runner.invoke("Listener", state, [])
        assert len(calls) == 1


async def test_active_cancel_during_mcp_and_call_budget():
    from backend.manager import RunManager
    from backend.config import Settings
    from backend.schemas import RunRequest
    from backend.mcp_client import document_session, ToolFailure
    m = RunManager(Settings(test_mode=True))
    r = await m.start(RunRequest(question="cancel active",mode="test",scenario="timeout"))
    for _ in range(100):
        if any(e["type"] == "tool_complete" for e in m.runs[r["run_id"]].events):
            break
        await asyncio.sleep(0.03)
    assert any(e["type"] == "tool_complete" for e in m.runs[r["run_id"]].events)
    await asyncio.wait_for(m.cancel(r["run_id"]), 5)
    assert m.snapshot(r["run_id"])["status"] == "cancelled"
    count = len(m.runs[r["run_id"]].events)
    await asyncio.sleep(0.05)
    assert len(m.runs[r["run_id"]].events) == count
    async with document_session() as client:
        for _ in range(12):
            await client.call("search_documents", {"query":"revenue"})
        with pytest.raises(ToolFailure):
            await client.call("search_documents", {"query":"revenue"})


def test_static_serving_and_request_limits(tmp_path):
    from backend.api import create_app
    from backend.config import Settings
    (tmp_path / "index.html").write_text("<html>test front</html>")
    with TestClient(create_app(Settings(test_mode=True), frontend_dir=tmp_path)) as c:
        assert c.get("/").text == "<html>test front</html>"
        assert c.get("/api/missing").status_code == 404
        assert c.post("/api/runs", content=b"x"*16001).status_code == 413
        assert c.post("/api/runs", headers={"content-length":"invalid"}, content="{}").status_code == 400
        assert c.get("/", headers={"host":"evil.example"}).status_code == 400


def test_replay_with_bounded_events():
    from backend.api import create_app
    from backend.config import Settings
    with TestClient(create_app(Settings(test_mode=True, max_events=3))) as c:
        r = c.post("/api/runs", json={"question":"Apple revenue", "mode":"test"}).json()
        c.get(f"/api/runs/{r['run_id']}/events")
        snapshot = c.get(f"/api/runs/{r['run_id']}").json()
        replay = c.get(f"/api/runs/{r['run_id']}/events").text
        events = [json.loads(line[6:]) for line in replay.splitlines() if line.startswith("data: ")]
        assert len(events) == 3
        assert events[-1]["data"]["snapshot"] == snapshot
