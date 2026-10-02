"""Runtime feedback regressions; provider data is synthetic, not live evidence."""
import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
import pytest
from backend.config import Settings
from backend.model_observation import record_model_call


def observe(caplog, *, usage=None, deployment="02" * 32, model="research-primary", gateway=True, prices=None, **metadata):
    response = SimpleNamespace(result=[SimpleNamespace(response_metadata={
        "headers": {"x-litellm-model-id": deployment, "x-litellm-model-name": "private/raw-model"},
        "model_name": "private/raw-model", "token_usage": usage or {}, **metadata})])
    settings = Settings(gateway_observation=gateway, token_prices=prices or {})
    result = record_model_call(run_id=None, role="Listener", call_id="a" * 32, model=model,
                              started=monotonic(), status="success", response=response, settings=settings)
    assert result == json.loads(caplog.records[-1].message)
    assert "private/raw-model" not in caplog.text
    return result


@pytest.mark.parametrize("deployment,requested,enabled,served,fallback", [
    ("01" * 32, "research-primary", True, "research-primary", False),
    ("02" * 32, "research-primary", True, "research-secondary", True),
    ("02" * 32, "research-secondary", True, "research-secondary", False),
    ("f" * 64, "research-primary", True, None, None),
    ("", "research-primary", True, None, None),
    ("02" * 32, "research-primary", False, None, None),
    ("02" * 32, "other-alias", True, "research-secondary", None),
])
def test_served_alias_requires_explicit_known_deployment(caplog, deployment, requested, enabled, served, fallback):
    data = observe(caplog, deployment=deployment, model=requested, gateway=enabled)
    assert data["served_by"] == served
    assert data["fallback"] is fallback


@pytest.mark.parametrize("usage,reasoning,residual", [
    ({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "completion_tokens_details": {"reasoning_tokens": 3}}, 3, 0),
    ({"prompt_tokens": 100000, "completion_tokens": 20369, "total_tokens": 128307}, None, 7938),
    ({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 21, "completion_tokens_details": {"reasoning_tokens": 3}}, 3, 3),
    ({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 17}, None, -1),
    ({"total_tokens": 18}, None, None),
    ({"prompt_tokens": 10, "total_tokens": 18}, None, None),
    ({"total_tokens": 0, "completion_tokens_details": {"reasoning_tokens": 0}}, 0, None),
    ({"completion_tokens_details": {"reasoning_tokens": 3}}, 3, None),
    ({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "completion_tokens_details": {"reasoning_tokens": True}}, None, 0),
    ({"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "completion_tokens_details": {"reasoning_tokens": 0}}, 0, 0),
])
def test_explicit_reasoning_is_not_inferred_from_residual(caplog, usage, reasoning, residual):
    data = observe(caplog, usage=usage)
    assert data["reasoning_tokens"] == reasoning
    assert data["unexplained_token_residual"] == residual


@pytest.mark.parametrize("deployment,usage,price,expected", [
    ("02" * 32, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "completion_tokens_details": {"reasoning_tokens": 20}}, {"input": 2, "output": 4}, 0.0004),
    ("02" * 32, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, {"input": 0, "output": 0}, 0),
    ("f" * 64, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, {"input": 2, "output": 4}, None),
    ("02" * 32, {"total_tokens": 150}, {"input": 2, "output": 4}, None),
    ("02" * 32, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 170}, {"input": 2, "output": 4}, None),
    ("02" * 32, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, None, None),
    ("02" * 32, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, {"input": 1e308, "output": 1e308}, None),
])
def test_estimate_uses_served_price_without_double_counting(caplog, deployment, usage, price, expected):
    prices = {"research-primary": {"input": 999, "output": 999}}
    if price is not None:
        prices["research-secondary"] = price
    data = observe(caplog, deployment=deployment, usage=usage, prices=prices)
    assert data["estimated_cost_usd"] == expected
    assert data["billing_cost_usd"] is None


@pytest.mark.parametrize("prices", [[], {"private/model": {"input": 1, "output": 2}}, {"research-primary": {"input": -1, "output": 2}}, {"research-primary": {"input": True, "output": 2}}, {"research-primary": {"input": float("inf"), "output": 2}}, {"research-primary": {"input": 1}}, {"research-primary": {"input": "1", "output": 2}}, {"research-primary": {"input": 10 ** 400, "output": 2}}])
def test_invalid_prices_fail_closed(prices):
    with pytest.raises(ValueError, match="LLM_TOKEN_PRICES_JSON"):
        Settings(token_prices=prices)


def test_settings_read_only_explicit_price_config(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("LLM_GATEWAY_OBSERVATION", "1")
    monkeypatch.setenv("LLM_TOKEN_PRICES_JSON", '{"research-secondary":{"input":2,"output":4}}')
    monkeypatch.setenv("LLM_GATEWAY_MODEL_NAMES_JSON", '{"research-secondary":"openai/mock-secondary"}')
    settings = Settings.from_env()
    assert settings.gateway_model_names == {"research-secondary": "openai/mock-secondary"}
    assert settings.gateway_observation
    assert settings.token_prices == {"research-secondary": {"input": 2, "output": 4}}
    monkeypatch.setenv("LLM_TOKEN_PRICES_JSON", "not-json")
    with pytest.raises(ValueError, match="LLM_TOKEN_PRICES_JSON"):
        Settings.from_env()


@pytest.mark.parametrize("headers,expected", [
    ({"x-litellm-model-name": "openai/mock-secondary", "x-litellm-attempted-fallbacks": "1", "x-ratelimit-remaining-requests": "29"}, ("openai/mock-secondary", 1, 29)),
    ({"x-litellm-model-name": "private/secret", "x-litellm-attempted-fallbacks": "-1", "x-ratelimit-remaining-requests": "1.5"}, (None, None, None)),
    ({"x-litellm-model-name": "openai/mock-primary", "x-litellm-attempted-fallbacks": "0", "x-ratelimit-remaining-requests": "0"}, (None, 0, 0)),
    ({"x-litellm-attempted-fallbacks": "9" * 500, "x-ratelimit-remaining-requests": True}, (None, None, None)),
    ({}, (None, None, None)),
])
def test_optional_headers_are_explicit_bounded_and_model_name_optin(caplog, headers, expected):
    settings = Settings(gateway_observation=True, gateway_model_names={"research-secondary": "openai/mock-secondary"})
    response = SimpleNamespace(result=[SimpleNamespace(response_metadata={"headers": {"x-litellm-model-id": "02" * 32, **headers}})])
    data = record_model_call(run_id=None, role="Listener", call_id="a" * 32, model="research-primary", started=monotonic(), status="success", response=response, settings=settings)
    assert (data["gateway_model_name"], data["attempted_fallbacks"], data["rate_limit_remaining_requests"]) == expected
    assert "private/secret" not in caplog.text


@pytest.mark.parametrize("names", [[], {"bad": "openai/name"}, {"research-primary": "https://secret.invalid?key=secret"}, {"research-primary": "private name"}, {"research-primary": "a" * 129}])
def test_model_name_allowlist_rejects_unbounded_or_non_model_values(names):
    with pytest.raises(ValueError, match="LLM_GATEWAY_MODEL_NAMES_JSON"):
        Settings(gateway_model_names=names)


def test_gateway_timeout_profile_covers_two_attempts_and_repair():
    import yaml
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "gateway/config.yaml").read_text(encoding="utf-8"))
    attempts = [d["litellm_params"]["timeout"] for d in config["model_list"]]
    assert attempts == [60, 60]
    assert config["litellm_settings"]["request_timeout"] == 60
    router = config["router_settings"]["timeout"]
    assert router > sum(attempts)
    from dotenv import dotenv_values
    profile = dotenv_values(root / "gateway/app.env.example")
    request = float(profile["LLM_REQUEST_TIMEOUT"])
    assert request > router
    for role in ["LISTENER", "PLANNER", "RESEARCHER", "REPORTER", "EVALUATOR"]:
        assert float(profile[role + "_TIMEOUT"]) > 2 * request
    assert float(profile["RUN_TIMEOUT"]) > float(profile["RESEARCHER_TIMEOUT"])
