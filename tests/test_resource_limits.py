import json
import pytest

async def test_provider_clients_closed_after_role_failure(monkeypatch):
    import httpx
    from langchain_openai import ChatOpenAI
    from backend.agents import RoleRunner
    from backend.config import Settings
    clients = []
    def model(**kwargs):
        def reject(request):
            return httpx.Response(401, json={"error":{"message":"test rejection"}})
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(reject))
        kwargs["http_async_client"] = httpx.AsyncClient(transport=httpx.MockTransport(reject))
        clients.extend([kwargs["http_client"], kwargs["http_async_client"]])
        return ChatOpenAI(**kwargs)
    monkeypatch.setattr("backend.agents.ChatOpenAI", model)
    runner = RoleRunner(Settings(provider="openai", model="placeholder", api_key="placeholder", base_url="http://127.0.0.1:9999/v1"), "live", "pass")
    with pytest.raises(Exception):
        await runner.invoke("Listener", dict(question="x", interpreted_request="", plan=[], evidence=[], report=None, feedback=[], iteration=0), [])
    assert all(client.is_closed for client in clients)

async def test_chunked_body_is_bounded_without_content_length():
    import httpx
    from backend.api import create_app
    from backend.config import Settings
    async def chunks():
        for _ in range(20):
            yield b"x" * 1000
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings())), base_url="http://localhost") as client:
        response = await client.post("/api/runs", content=chunks(), headers={"content-type":"application/json"})
    assert response.status_code == 413
