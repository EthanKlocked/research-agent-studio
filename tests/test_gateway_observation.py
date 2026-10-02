"""Safe app-side correlation; no provider calls."""
import json
import logging

import pytest
from backend.agents import RoleRunner
from backend.config import Settings
from test_live_resilience import SETTINGS, STATE, install_provider


async def test_gateway_observation_unknown_usage_and_correlation(monkeypatch, caplog):
    install_provider(monkeypatch, lambda _: {"content": '{"interpreted_request":"ok"}'})
    caplog.set_level(logging.INFO, logger="research.model")
    runner = RoleRunner(Settings(**SETTINGS), "live", "pass")
    events = []
    async def publish(kind, state, data):
        events.append((kind, data))
    runner.publish = publish
    await runner.invoke("Listener", {**STATE, "run_id": "a" * 32}, [])
    records = [json.loads(r.message) for r in caplog.records if r.name == "research.model"]
    assert len(records) == 1
    record = records[0]
    assert record["run_id"] == "a" * 32
    assert record["role"] == "Listener"
    assert record["model_call_id"] == events[0][1]["model_call_id"]
    assert record["status"] == "success"
    assert record["input_tokens"] is None and record["output_tokens"] is None
    assert record["total_tokens"] is None and record["estimated_cost_usd"] is None
    assert record["latency_ms"] >= 0
    assert "question" not in record and "messages" not in record


async def test_gateway_observation_failure_redacts_exception(monkeypatch, caplog):
    def fail(_):
        raise RuntimeError("private-secret /Users/private question")
    install_provider(monkeypatch, fail)
    caplog.set_level(logging.INFO, logger="research.model")
    with pytest.raises(Exception):
        await RoleRunner(Settings(**SETTINGS), "live", "pass").invoke("Listener", STATE, [])
    records = [json.loads(r.message) for r in caplog.records if r.name == "research.model"]
    assert len(records) == 1 and records[0]["status"] == "error"
    assert "private-secret" not in caplog.text


def test_gateway_config_is_optional_pinned_and_bounded():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    config = root / "gateway/config.yaml"
    assert config.exists(), "optional proxy configuration missing"
    text = config.read_text(encoding="utf-8")
    assert "research-primary" in text and "research-secondary" in text
    assert "enforce_model_rate_limits" in text
    assert "num_retries: 0" in text and "max_fallbacks: 1" in text
    compose = (root / "gateway/compose.yaml").read_text(encoding="utf-8")
    assert "v1.103.2@sha256:" in compose and "127.0.0.1:4000:4000" in compose
