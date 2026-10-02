"""Observation fields stay bounded even for adversarial response metadata."""
import json
import logging
from types import SimpleNamespace
from time import monotonic
import pytest
from backend.model_observation import record_model_call


def test_metrics_visible_without_root_logging(capsys):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "from backend.model_observation import record_model_call; from time import monotonic; record_model_call(run_id=None, role='Listener', call_id='a'*32, model='research-primary', started=monotonic(), status='success')"], capture_output=True, text=True, encoding="utf-8", check=True)
    assert '"model_call_id"' in result.stderr


@pytest.mark.parametrize("usage", [{}, {"total_tokens": 0}, {"total_tokens": True}, {"total_tokens": -1}, {"total_tokens": "18"}])
def test_unknown_usage_is_never_silent_zero(usage, caplog):
    caplog.set_level(logging.INFO, logger="research.model")
    response = SimpleNamespace(result=[SimpleNamespace(response_metadata={"token_usage": usage, "headers": {"x-litellm-call-id": "private-secret /Users/private"}})])
    record_model_call(run_id="private-path", role="Listener", call_id="a"*32,
                      model="secret-model /private", started=monotonic(), status="success", response=response)
    data = json.loads(caplog.records[-1].message)
    assert data["total_tokens"] is None and data["gateway_call_id"] is None
    assert data["run_id"] is None and data["model"] == "configured-model"
    assert "private" not in caplog.text and "secret-model" not in caplog.text


def test_gateway_deployment_hash_correlates_without_endpoint(caplog):
    caplog.set_level(logging.INFO, logger="research.model")
    response = SimpleNamespace(result=[SimpleNamespace(response_metadata={"headers": {"x-litellm-model-id": "f" * 64, "x-litellm-model-api-base": "https://private.invalid"}})])
    record_model_call(run_id=None, role="Listener", call_id="a"*32,
                      model="research-primary", started=monotonic(), status="success", response=response)
    data = json.loads(caplog.records[-1].message)
    assert data["gateway_model_id"] == "f" * 64
    assert "private.invalid" not in caplog.text
