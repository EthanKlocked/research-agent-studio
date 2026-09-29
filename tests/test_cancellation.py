"""Cancellation regressions using the real graph, fixture model and MCP process."""
import asyncio
import os

import pytest

from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest


@pytest.fixture
def mcp_processes(monkeypatch):
    import mcp.client.stdio as stdio
    processes = []
    original = stdio._create_platform_compatible_process

    async def tracked(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", tracked)
    return processes


def assert_cancelled(manager, rid):
    state = manager.snapshot(rid)
    events = list(manager.runs[rid].events)
    assert state["status"] == "cancelled", state
    assert state["finished_at"]
    assert state["errors"] == []
    assert state["report"] is None
    assert manager.tasks[rid].done()
    assert sum(e["type"] == "terminal" for e in events) == 1
    assert events[-1]["data"]["snapshot"] == state
    assert not any(e["data"]["snapshot"]["status"] == "success" for e in events)


async def assert_reaped(processes):
    assert processes, "The regression must exercise a real MCP subprocess"
    for process in processes:
        assert process.returncode is not None, "Subprocess is still running"
        try:
            returncode = await asyncio.wait_for(process.wait(), 1)
        except TimeoutError:
            raise AssertionError("Subprocess wait timed out") from None
        assert returncode is not None
        assert returncode == process.returncode


@pytest.fixture
def no_pid_probes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Process cleanup must use handles, not os.kill")
    monkeypatch.setattr(os, "kill", forbidden)
    return monkeypatch


async def test_assert_reaped_accepts_exited_handle_without_pid_probe(no_pid_probes):
    import anyio
    import sys

    async with await anyio.open_process([sys.executable, "-c", "pass"]) as process:
        await asyncio.wait_for(process.wait(), 10)
        await assert_reaped([process])


async def test_assert_reaped_rejects_live_handle_without_pid_probe(no_pid_probes):
    import anyio
    import sys

    async with await anyio.open_process([sys.executable, "-c", "import time; time.sleep(60)"]) as process:
        try:
            with pytest.raises(AssertionError):
                await assert_reaped([process])
        finally:
            # The assertion must not probe PIDs; real test teardown may signal.
            no_pid_probes.undo()
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)


async def test_assert_reaped_rejects_wait_timeout_without_pid_probe(no_pid_probes):
    class StuckHandle:
        returncode = 0
        pid = 0  # Never used: PID probes are forbidden in this test.

        async def wait(self):
            await asyncio.Event().wait()

    with pytest.raises(AssertionError, match="timed out"):
        await assert_reaped([StuckHandle()])


@pytest.mark.parametrize("phase", ["startup", "discovery", "model_wait", "cleanup_error"])
async def test_cancel_real_mcp_lifecycle(phase, monkeypatch, mcp_processes):
    from backend.agents import FixtureModel
    from langchain_core.messages import ToolMessage
    from mcp import ClientSession

    entered = asyncio.Event()
    if phase in ("startup", "cleanup_error"):
        original = ClientSession.initialize

        async def initialize(self, *args, **kwargs):
            entered.set()
            try:
                return await original(self, *args, **kwargs)
            except asyncio.CancelledError:
                if phase == "cleanup_error":
                    raise RuntimeError("cleanup masked cancellation") from None
                raise

        monkeypatch.setattr(ClientSession, "initialize", initialize)
    elif phase == "discovery":
        original = ClientSession.list_tools

        async def listing(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(ClientSession, "list_tools", listing)
    else:
        original = FixtureModel._agenerate

        async def generate(self, messages, *args, **kwargs):
            if self.role == "Researcher" and any(isinstance(m, ToolMessage) for m in messages):
                entered.set()
            return await original(self, messages, *args, **kwargs)

        monkeypatch.setattr(FixtureModel, "_agenerate", generate)

    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="cancel real MCP", mode="test", scenario="timeout"))
    rid = state["run_id"]
    try:
        await asyncio.wait_for(entered.wait(), 15)
        assert not manager.tasks[rid].done()
        await asyncio.wait_for(manager.cancel(rid), 15)
        await assert_reaped(mcp_processes)
        assert_cancelled(manager, rid)
        events = list(manager.runs[rid].events)
        if phase in ("startup", "discovery", "cleanup_error"):
            assert not any(e["type"] == "model_start" and e["data"]["role"] == "Planner" for e in events)
            assert not any(e["type"] in ("discovery_complete", "tool_start") for e in events)
        assert events[-1]["type"] == "terminal"
        before = manager.snapshot(rid)
        assert await manager.cancel(rid) == before
    finally:
        await manager.close()


async def test_timeout_is_a_timeout_not_generic_model_error(mcp_processes):
    manager = RunManager(Settings(test_mode=True, researcher_timeout=0.5))
    state = await manager.start(RunRequest(question="timeout", mode="test", scenario="timeout"))
    rid = state["run_id"]
    try:
        await asyncio.wait_for(manager.tasks[rid], 15)
        state = manager.snapshot(rid)
        await assert_reaped(mcp_processes)
        assert state["status"] == "error"
        assert "시간 제한" in state["errors"][0], state
        assert any(e["type"] == "tool_complete" for e in manager.runs[rid].events)
        assert state["report"] is None
    finally:
        await manager.close()


async def test_cancel_before_first_instruction_is_finalized_once():
    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="queued", mode="test"))
    rid = state["run_id"]
    await asyncio.gather(manager.cancel(rid), manager.cancel(rid))
    assert_cancelled(manager, rid)


@pytest.mark.parametrize("outcome", ["success", "base_group"])
async def test_cancellation_intent_wins_over_swallowed_signal(outcome, monkeypatch):
    entered = asyncio.Event()

    class Graph:
        async def ainvoke(self, state, config):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if outcome == "base_group":
                    raise BaseExceptionGroup("cleanup", [asyncio.CancelledError(), RuntimeError("cleanup")])
                return {**state, "status": "success"}

    monkeypatch.setattr("backend.manager.build_graph", lambda *args: Graph())
    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="cancel", mode="test"))
    rid = state["run_id"]
    await entered.wait()
    await manager.cancel(rid)
    assert_cancelled(manager, rid)


async def test_concurrent_cancel_does_not_interrupt_cleanup(monkeypatch):
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Graph:
        async def ainvoke(self, state, config):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

    monkeypatch.setattr("backend.manager.build_graph", lambda *args: Graph())
    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="cancel", mode="test"))
    rid = state["run_id"]
    await entered.wait()
    first = asyncio.create_task(manager.cancel(rid))
    await cleaning.wait()
    second = asyncio.create_task(manager.cancel(rid))
    await asyncio.sleep(0)
    assert manager.tasks[rid].cancelling() == 1
    assert not first.done() and not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert_cancelled(manager, rid)


async def test_provisional_node_status_does_not_prevent_cancellation(monkeypatch):
    entered = asyncio.Event()

    def build(settings, mode, scenario, publish):
        class Graph:
            async def ainvoke(self, state, config):
                await publish("node_complete", {**state, "status": "success"}, {})
                entered.set()
                await asyncio.Event().wait()
        return Graph()

    monkeypatch.setattr("backend.manager.build_graph", build)
    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="cancel", mode="test"))
    rid = state["run_id"]
    await entered.wait()
    await manager.cancel(rid)
    result = manager.snapshot(rid)
    assert result["status"] == "cancelled" and result["finished_at"]
    assert manager.tasks[rid].done()
    assert sum(e["type"] == "terminal" for e in manager.runs[rid].events) == 1
