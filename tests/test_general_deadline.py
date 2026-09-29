"""Offline real provider-stream regressions through FastMCP dispatch."""
import asyncio
import inspect
import time

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from mcp_server import general_web
from mcp_server.server import register_general_tools


class Drip(httpx.SyncByteStream, httpx.AsyncByteStream):
    """Dual transport fixture reproduces the old worker and async implementation."""
    def __init__(self):
        self.entered = asyncio.Event()
        self.closed = False
        self.consumed = 0
        self.loop = asyncio.get_running_loop()

    def __iter__(self):
        self.loop.call_soon_threadsafe(self.entered.set)
        for _ in range(100):
            time.sleep(.01)
            self.consumed += 1
            yield b" "

    async def __aiter__(self):
        self.entered.set()
        for _ in range(100):
            await asyncio.sleep(.01)
            self.consumed += 1
            yield b" "

    def close(self):
        self.closed = True

    async def aclose(self):
        self.closed = True


async def close_store(store):
    if inspect.iscoroutinefunction(store.close):
        await store.close()
    else:
        await asyncio.to_thread(store.close)


def provider():
    stream = Drip()
    store = general_web.GeneralWebStore(
        api_key="offline-test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    server = FastMCP("deadline-regression")
    register_general_tools(server, store)
    return server, store, stream


async def test_slow_drip_obeys_absolute_deadline_and_closes(monkeypatch):
    monkeypatch.setattr(general_web, "REQUEST_TIMEOUT", .02)
    server, store, stream = provider()
    start = time.monotonic()
    try:
        result = await server.call_tool("web_search", {"query": "offline"})
        assert result.isError
        assert result.structuredContent == {"web_failure": {"category": "timeout"}}
        elapsed = time.monotonic() - start
        assert elapsed < .3, f"20ms deadline took {elapsed:.3f}s; consumed={stream.consumed}"
        assert stream.closed and stream.consumed < 100
        assert not store._lock.locked()
    finally:
        await close_store(store)
    assert store._client.is_closed


async def test_cancel_active_provider_closes_stream_before_return():
    server, store, stream = provider()
    task = asyncio.create_task(server.call_tool("web_search", {"query": "offline"}))
    try:
        await asyncio.wait_for(stream.entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, .3)
        assert stream.closed, "cancelled MCP call left active provider stream/worker"
        consumed = stream.consumed
        await asyncio.sleep(.03)
        assert stream.consumed == consumed
        assert not store._lock.locked()
        await asyncio.wait_for(close_store(store), .3)
        assert store._client.is_closed
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await close_store(store)
