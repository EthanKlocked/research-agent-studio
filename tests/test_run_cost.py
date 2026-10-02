"""Run cost is authoritative snapshot data, not a sum of retained/replayed events."""
from collections import deque
import pytest
from backend.config import Settings
from backend.manager import RunManager, RunRecord


def run_manager(mode="live"):
    manager = RunManager(Settings(max_events=2))
    state = {"run_id": "a" * 32, "mode": mode, "last_seq": 0, "status": "running"}
    manager.runs[state["run_id"]] = RunRecord(state, deque(maxlen=2))
    return manager, state


async def emit(manager, state, kind, call="b" * 32, cost=None):
    await manager.emit(state["run_id"], kind, state, {"model_call_id": call, "observation": {"estimated_cost_usd": cost}})
    return manager.snapshot(state["run_id"]).get("cost_summary")


async def test_run_cost_partial_total_survives_eviction_and_deduplicates():
    manager, state = run_manager()
    first = await emit(manager, state, "model_start")
    assert first == {"model_requests": 1, "priced_requests": 0, "unknown_requests": 1,
                     "known_estimated_cost_usd": None, "estimated_cost_usd": None, "estimate_status": "unknown"}
    complete = await emit(manager, state, "model_complete", cost=0.125)
    assert complete["estimated_cost_usd"] == 0.125
    assert complete["estimate_status"] == "complete"
    await emit(manager, state, "model_complete", cost=999)  # duplicate must not count twice or replace
    await emit(manager, state, "model_start", call="c" * 32)
    await emit(manager, state, "model_error", call="c" * 32)
    await emit(manager, state, "node_complete")  # graph state has no cost summary
    partial = manager.snapshot(state["run_id"])["cost_summary"]
    assert partial == {"model_requests": 2, "priced_requests": 1, "unknown_requests": 1,
                       "known_estimated_cost_usd": 0.125, "estimated_cost_usd": None, "estimate_status": "partial"}
    assert len(manager.runs[state["run_id"]].events) == 2
    assert manager.runs[state["run_id"]].events[-1]["data"]["snapshot"]["cost_summary"] == partial
    await manager.emit(state["run_id"], "terminal", {**state, "status": "cancelled"})
    assert manager.snapshot(state["run_id"])["cost_summary"] == partial
    await emit(manager, state, "model_complete", call="c" * 32, cost=100)
    assert manager.snapshot(state["run_id"])["cost_summary"] == partial


async def test_explicit_free_price_and_new_run_are_distinct_from_unknown():
    manager, state = run_manager()
    result = await emit(manager, state, "model_complete", cost=0)
    assert result["estimated_cost_usd"] == 0 and result["priced_requests"] == 1
    other = {**state, "run_id": "d" * 32}
    manager.runs[other["run_id"]] = RunRecord(other, deque(maxlen=2))
    result = await emit(manager, other, "model_start")
    assert result["model_requests"] == 1 and result["estimated_cost_usd"] is None


@pytest.mark.parametrize("cost", [None, -1, True, float("inf"), float("nan"), "0.1"])
async def test_invalid_or_missing_cost_stays_unknown(cost):
    manager, state = run_manager()
    result = await emit(manager, state, "model_complete", cost=cost)
    assert result["estimated_cost_usd"] is None
    assert result["known_estimated_cost_usd"] is None
    assert result["unknown_requests"] == 1


async def test_fixture_mode_never_claims_real_cost():
    manager, state = run_manager("test")
    assert await emit(manager, state, "model_complete", cost=0.1) is None
