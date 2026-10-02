"""Opt-in: real pinned LiteLLM container + offline mock, never live providers.
RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -q
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx
import pytest
import yaml
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest

pytestmark = pytest.mark.skipif(os.getenv("RAS_GATEWAY_TEST") != "1", reason="opt-in Docker gateway integration")
ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-offline-test-only-not-a-real-key"


@pytest.fixture(scope="module")
def stack():
    image = yaml.safe_load((ROOT / "gateway/compose.mock.yaml").read_text(encoding="utf-8"))["services"]["gateway"]["image"]
    check = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert check.returncode == 0, f"Pinned gateway image/daemon unavailable. Run docker version, then docker pull {image}; rerun with RAS_GATEWAY_TEST=1. This is not a passed proxy check."
    project = "ras-gateway-test-" + uuid4().hex[:10]
    with tempfile.TemporaryDirectory() as directory:
        envfile = Path(directory) / "empty.env"
        envfile.write_text("", encoding="utf-8")
        # Same operator config, only time budgets shortened for bounded failure tests.
        config = yaml.safe_load((ROOT / "gateway/config.yaml").read_text(encoding="utf-8"))
        for deployment in config["model_list"]:
            deployment["litellm_params"]["timeout"] = 1
        config["litellm_settings"]["request_timeout"] = 1
        config["router_settings"]["timeout"] = 3
        config_path = Path(directory) / "config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        override = Path(directory) / "override.yaml"
        override.write_text(yaml.safe_dump({"services": {"gateway": {"volumes": [str(config_path) + ":/app/config.yaml:ro"]}}}), encoding="utf-8")
        command = ["docker", "compose", "--env-file", str(envfile), "-p", project, "-f", str(ROOT / "gateway/compose.mock.yaml"), "-f", str(override)]
        def compose(*args):
            result = subprocess.run([*command, *args], check=True, capture_output=True, text=True, encoding="utf-8", timeout=180)
            return result.stdout + result.stderr if args[0] == "logs" else result.stdout
        try:
            compose("up", "-d", "--pull", "never")
            gateway = "http://" + compose("port", "gateway", "4000").strip()
            upstream = "http://" + compose("port", "upstream", "8080").strip()
            with httpx.Client(timeout=30, trust_env=False) as client:
                deadline = time.monotonic() + 120
                while True:
                    try:
                        if client.get(gateway + "/health/liveliness").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() > deadline:
                        raise AssertionError("Gateway did not become healthy; inspect isolated Compose startup")
                    time.sleep(.25)
                yield [client, gateway, upstream, compose]
        finally:
            compose("down", "--volumes", "--remove-orphans")


def control(stack, scenario):
    client, _, upstream, _ = stack
    client.post(upstream + "/control", json={"scenario": scenario}).raise_for_status()


def attempts(stack):
    return stack[0].get(stack[2]).json()["attempts"]


def completion(stack, model="research-primary", key=KEY):
    headers = {"Authorization": "Bearer " + key} if key else {}
    return stack[0].post(stack[1] + "/v1/chat/completions", headers=headers,
                         json={"model": model, "messages": [{"role": "user", "content": "offline-private-prompt-marker"}]})


def test_optional_header_contract(stack):
    stack[3]("restart", "gateway")
    wait_healthy(stack)
    for scenario, model_name, fallbacks in [("normal", "openai/mock-primary", "0"), ("fail-503", "openai/mock-secondary", "1")]:
        control(stack, scenario)
        response = completion(stack)
        assert response.status_code == 200
        assert response.headers["x-litellm-model-name"] == model_name
        assert response.headers["x-litellm-attempted-fallbacks"] == fallbacks
        assert response.headers["x-ratelimit-remaining-requests"] == "29"
    stack[3]("restart", "gateway")
    wait_healthy(stack)


def test_auth_and_aliases(stack):
    control(stack, "normal")
    assert completion(stack, key=None).status_code == 401
    assert completion(stack, key="wrong-key").status_code == 400  # malformed, missing sk- prefix
    # This pinned no-DB proxy rejects a non-master key with 400 (not 401).
    assert completion(stack, key="sk-wrong-offline-key").status_code == 400
    assert attempts(stack) == []
    for alias, upstream in [("research-primary", "mock-primary"), ("research-secondary", "mock-secondary")]:
        response = completion(stack, alias)
        assert response.status_code == 200, response.text
        assert response.json()["model"] == alias  # normal route exposes the public alias
        assert response.json()["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        assert response.headers.get("x-litellm-call-id")
        assert response.headers["x-litellm-model-id"] == ("01" if alias == "research-primary" else "02") * 32
    assert [a["model"] for a in attempts(stack)] == ["mock-primary", "mock-secondary"]
    assert all(a["auth_ok"] for a in attempts(stack))


@pytest.mark.parametrize("code", [401, 429, 503])
def test_fallback_actual_upstream_count(stack, code):
    control(stack, f"fail-{code}")
    response = completion(stack)
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "mock-secondary"
    assert response.headers["x-litellm-model-id"] == "02" * 32
    assert [a["model"] for a in attempts(stack)] == ["mock-primary", "mock-secondary"]


def settings(stack, **kwargs):
    return Settings(provider="openai-compatible", model="research-primary", api_key=KEY,
                    base_url=stack[1] + "/v1", gateway_observation=True, gateway_model_names={"research-primary": "openai/mock-primary", "research-secondary": "openai/mock-secondary"}, **kwargs)


@pytest.mark.parametrize("fallback", [False, True])
async def test_real_graph_mcp_and_safe_usage(stack, caplog, monkeypatch, fallback):
    monkeypatch.setenv("RESEARCH_PUBLIC_SOURCES", "0")
    control(stack, "fail-503" if fallback else "normal")
    caplog.set_level(logging.INFO, logger="research.model")
    manager = RunManager(settings(stack, token_prices={"research-primary": {"input": 2, "output": 4}, "research-secondary": {"input": 3, "output": 6}}))
    state = await manager.start(RunRequest(question="revenue", mode="live"))
    await manager.tasks[state["run_id"]]
    final = manager.snapshot(state["run_id"])
    assert final["status"] == "success", final["errors"]
    assert final["report"] and final["evidence"]
    records = [json.loads(r.message) for r in caplog.records if r.name == "research.model"]
    starts = [e for e in manager.runs[state["run_id"]].events if e["type"] == "model_start"]
    assert len(records) == len(starts) == 7
    assert len(attempts(stack)) == (14 if fallback else 7)
    assert {r["model_call_id"] for r in records} == {e["data"]["model_call_id"] for e in starts}
    assert {r["role"] for r in records} == {"Listener", "Planner", "Researcher", "Reporter", "Evaluator"}
    assert all(r["run_id"] == state["run_id"] and r["gateway_call_id"] and r["gateway_model_id"] for r in records)
    assert all(r["served_by"] == ("research-secondary" if fallback else "research-primary") and r["fallback"] is fallback for r in records)
    completes = [e["data"] for e in manager.runs[state["run_id"]].events if e["type"] == "model_complete"]
    assert len(completes) == 7
    assert all(e["observation"]["served_by"] == records[0]["served_by"] and e["observation"]["fallback"] is fallback for e in completes)
    assert len({r["gateway_call_id"] for r in records}) == 7
    assert all(r["total_tokens"] == 18 and r["input_tokens"] == 11 and r["output_tokens"] == 7 for r in records)
    expected_cost = (11 * (3 if fallback else 2) + 7 * (6 if fallback else 4)) / 1_000_000
    assert all(r["estimated_cost_usd"] == expected_cost for r in records)
    assert all(r["gateway_model_name"] == ("openai/mock-secondary" if fallback else "openai/mock-primary") and r["attempted_fallbacks"] == int(fallback) for r in records)
    assert all(type(r["rate_limit_remaining_requests"]) is int for r in records)
    assert all(e["observation"]["gateway_model_name"] == records[0]["gateway_model_name"] for e in completes)
    assert final["cost_summary"]["estimated_cost_usd"] == pytest.approx(7 * expected_cost)
    assert final["cost_summary"]["model_requests"] == final["cost_summary"]["priced_requests"] == 7
    assert final["cost_summary"]["unknown_requests"] == 0
    assert KEY not in caplog.text


async def test_missing_usage_stays_unknown(stack, caplog):
    from backend.agents import RoleRunner
    control(stack, "no-usage")
    caplog.set_level(logging.INFO, logger="research.model")
    state = dict(question="offline", interpreted_request="", plan=[], evidence=[], report=None, feedback=[], iteration=0)
    await RoleRunner(settings(stack), "live", "pass").invoke("Listener", state, [])
    record = next(json.loads(r.message) for r in caplog.records if r.name == "research.model")
    assert record["total_tokens"] is None and record["input_tokens"] is None
    assert record["usage_source"] == "unknown"


@pytest.mark.parametrize("scenario,reasoning,residual", [("reasoning", 3, 0), ("residual", None, 4)])
async def test_usage_detail_contract_through_proxy(stack, caplog, scenario, reasoning, residual):
    from backend.agents import RoleRunner
    control(stack, scenario)
    state = dict(question="offline", interpreted_request="", plan=[], evidence=[], report=None, feedback=[], iteration=0)
    await RoleRunner(settings(stack, token_prices={"research-primary": {"input": 2, "output": 4}}), "live", "pass").invoke("Listener", state, [])
    record = next(json.loads(r.message) for r in caplog.records if r.name == "research.model")
    assert record["reasoning_tokens"] == reasoning
    assert record["unexplained_token_residual"] == residual
    assert record["output_tokens"] == 7
    assert record["estimated_cost_usd"] == (0.00005 if residual == 0 else None)


def test_timeout_fallback_is_bounded(stack):
    control(stack, "slow-primary")
    start = time.monotonic()
    response = completion(stack)
    assert response.status_code == 200, response.text
    assert time.monotonic() - start < 25
    assert [a["model"] for a in attempts(stack)] == ["mock-primary", "mock-secondary"]


def test_both_upstreams_timeout_without_retry_explosion(stack):
    control(stack, "slow")
    start = time.monotonic()
    response = completion(stack)
    assert response.status_code == 408
    assert time.monotonic() - start < 25
    assert [a["model"] for a in attempts(stack)] == ["mock-primary", "mock-secondary"]


@pytest.mark.parametrize("cancel", [False, True])
async def test_run_deadline_and_cancel_during_fallback(stack, cancel, caplog):
    control(stack, "fallback-slow")
    caplog.set_level(logging.INFO, logger="research.model")
    manager = RunManager(settings(stack, run_timeout=10 if cancel else 1))
    state = await manager.start(RunRequest(question="offline", mode="live"))
    run_id = state["run_id"]
    start = time.monotonic()
    if cancel:
        async with asyncio.timeout(5):
            while len(attempts(stack)) < 2:
                await asyncio.sleep(.05)
        await manager.cancel(run_id)
    await manager.tasks[run_id]
    assert time.monotonic() - start < 5
    final = manager.snapshot(run_id)
    assert final["status"] == ("cancelled" if cancel else "error")
    if not cancel:
        assert "timeout" in str(final["errors"])
    assert len(attempts(stack)) <= 2
    records = [json.loads(r.message) for r in caplog.records if r.name == "research.model"]
    assert len(records) == 1 and records[0]["status"] == "cancelled"


def wait_healthy(stack):
    # Docker Desktop may reassign an ephemeral published port on restart.
    stack[1] = "http://" + stack[3]("port", "gateway", "4000").strip()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if stack[0].get(stack[1] + "/health/liveliness").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.25)
    raise AssertionError("Restarted gateway did not become healthy")


def test_real_rpm_limiter_rejects_before_upstream(stack):
    control(stack, "normal")
    # Restart clears per-process counters; measure the exact threshold.
    stack[3]("restart", "gateway")
    wait_healthy(stack)
    statuses = []
    for _ in range(31):
        before = len(attempts(stack))
        response = completion(stack, "research-secondary")
        statuses.append(response.status_code)
        if response.status_code == 429:
            assert len(attempts(stack)) == before
            break
        assert response.status_code == 200, response.text
    assert statuses == [200] * 30 + [429]
    assert len(attempts(stack)) == 30


def test_proxy_logs_do_not_echo_upstream_error(stack):
    # Self-contained even with -k proxy_logs: reset limits then trigger failure.
    stack[3]("restart", "gateway")
    wait_healthy(stack)
    control(stack, "fail-503")
    assert completion(stack).status_code == 200
    assert [a["model"] for a in attempts(stack)] == ["mock-primary", "mock-secondary"]
    logs = stack[3]("logs", "--no-color", "gateway")
    assert "private-marker" not in logs
    assert "offline-private-prompt-marker" not in logs
    assert "Interpret the user's" not in logs
    assert KEY not in logs and "offline-upstream-only" not in logs


def test_operator_compose_starts_with_mock_endpoints(stack, tmp_path):
    # Exercise the operator file, changing only host port and test network wiring.
    project = "ras-gateway-operator-" + uuid4().hex[:10]
    test_project = json.loads(stack[3]("config", "--format", "json"))["name"]
    override = tmp_path / "test-wiring.yaml"
    override.write_text('services:\n  gateway:\n    ports: !override ["127.0.0.1::4000"]\nnetworks:\n  default:\n    external: true\n    name: ' + test_project + '_offline\n', encoding="utf-8")
    envfile = tmp_path / "empty.env"
    envfile.write_text("", encoding="utf-8")
    env = {**os.environ, "LITELLM_MASTER_KEY": KEY,
           "PRIMARY_MODEL": "openai/mock-primary", "SECONDARY_MODEL": "openai/mock-secondary",
           "PRIMARY_BASE_URL": "http://upstream:8080/v1", "SECONDARY_BASE_URL": "http://upstream:8080/v1",
           "PRIMARY_API_KEY": "offline-upstream-only", "SECONDARY_API_KEY": "offline-upstream-only"}
    command = ["docker", "compose", "--env-file", str(envfile), "-p", project,
               "-f", str(ROOT / "gateway/compose.yaml"), "-f", str(override)]
    def compose(*args, environment=env):
        return subprocess.run([*command, *args], env=environment, check=True, capture_output=True, text=True, encoding="utf-8", timeout=180).stdout
    with pytest.raises(subprocess.CalledProcessError):
        compose("config", "--quiet", environment={**env, "LITELLM_MASTER_KEY": ""})
    compose("config", "--quiet")
    try:
        compose("up", "-d", "--wait", "--wait-timeout", "120", "--pull", "never")
        url = "http://" + compose("port", "gateway", "4000").strip()
        control(stack, "slow-primary")
        started = time.monotonic()
        response = stack[0].post(url + "/v1/chat/completions", headers={"Authorization": "Bearer " + KEY}, json={"model": "research-primary", "messages": [{"role": "user", "content": "offline operator path"}]})
        assert response.status_code == 200
        assert 10 < time.monotonic() - started < 30
        assert response.headers["x-litellm-model-id"] == "01" * 32
        assert attempts(stack) == [{"model": "mock-primary", "auth_ok": True}]
    finally:
        compose("down", "--volumes", "--remove-orphans")
