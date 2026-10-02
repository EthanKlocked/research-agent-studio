"""Offline Windows-reported runtime regressions; not Windows/live execution."""
from datetime import datetime, timezone
from time import monotonic
from types import SimpleNamespace
import pytest
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest
from backend.model_observation import record_model_call


def observation(settings, usage, deployment="02" * 32):
    return record_model_call(run_id=None, role="Researcher", call_id="a" * 32,
        model="research-primary", started=monotonic(), status="success", settings=settings,
        response=SimpleNamespace(result=[SimpleNamespace(response_metadata={"token_usage":usage,
            "headers":{"x-litellm-model-id":deployment}})]))


@pytest.mark.parametrize("gateway,label", [(False,"configured-model"),(True,"research-secondary")])
@pytest.mark.parametrize("residual,expected", [(0,0.0004),(20,0.00048),(-1,None)])
def test_opt_in_residual_output_rate_and_no_double_reasoning(gateway,label,residual,expected):
    settings=Settings(gateway_observation=gateway,residual_pricing="output",token_prices={label:{"input":2,"output":4}})
    data=observation(settings,{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150+residual,
        "completion_tokens_details":{"reasoning_tokens":30}})
    assert data["estimated_cost_usd"] == expected
    assert data["reasoning_tokens"] == 30
    assert data["cost_assumption"] == ("residual_at_output_rate" if residual > 0 else None)
    assert data["input_output_estimated_cost_usd"] == (0.0004 if residual >= 0 else None)


def test_default_residual_unknown_but_covered_subtotal_explicit():
    data=observation(Settings(token_prices={"configured-model":{"input":2,"output":4}}),
        {"prompt_tokens":100,"completion_tokens":50,"total_tokens":170})
    assert data["estimated_cost_usd"] is None
    assert data["input_output_estimated_cost_usd"] == 0.0004
    assert data["cost_assumption"] is None


@pytest.mark.parametrize("usage", [{},{"total_tokens":170},{"prompt_tokens":100,"completion_tokens":50,"total_tokens":0}])
def test_opt_in_does_not_price_missing_usage(usage):
    assert observation(Settings(residual_pricing="output",token_prices={"configured-model":{"input":2,"output":4}}),usage)["estimated_cost_usd"] is None


def test_unknown_served_alias_never_uses_requested_price():
    settings=Settings(gateway_observation=True,residual_pricing="output",token_prices={"research-primary":{"input":2,"output":4}})
    assert observation(settings,{"prompt_tokens":100,"completion_tokens":50,"total_tokens":170},"f"*64)["estimated_cost_usd"] is None


@pytest.mark.parametrize("kwargs,field", [({"run_timezone":"Not/AZone"},"RUN_TIMEZONE"),({"residual_pricing":"reasoning"},"LLM_RESIDUAL_PRICING"),({"gateway_router_timeout":float('nan')},"LLM_GATEWAY_ROUTER_TIMEOUT")])
def test_invalid_config_is_safe(kwargs,field):
    with pytest.raises(ValueError,match=field): Settings(**kwargs)


def test_settings_env(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED","1")
    monkeypatch.setenv("RUN_TIMEZONE","Asia/Seoul")
    monkeypatch.setenv("LLM_RESIDUAL_PRICING","output")
    monkeypatch.setenv("LLM_GATEWAY_ROUTER_TIMEOUT","125")
    s=Settings.from_env()
    assert (s.run_timezone,s.residual_pricing,s.gateway_router_timeout)==("Asia/Seoul","output",125)


@pytest.mark.parametrize("zone,instant,date,offset", [
    ("Asia/Seoul","2026-10-01T15:01:00+00:00","2026-10-02","+09:00"),
    ("Asia/Seoul","2026-10-01T23:59:00+00:00","2026-10-02","+09:00"),
    ("America/New_York","2026-03-08T06:59:00+00:00","2026-03-08","-05:00"),
    ("America/New_York","2026-03-08T07:01:00+00:00","2026-03-08","-04:00"),
])
async def test_configured_clock_conversion(zone,instant,date,offset):
    manager=RunManager(Settings(test_mode=True,run_timezone=zone),clock=lambda:datetime.fromisoformat(instant))
    initial=await manager.start(RunRequest(question="today",mode="test"))
    try:
        c=initial["run_context"]
        assert c["timezone"] == zone and c["current_date"] == date
        assert c["started_at"].endswith(offset)
    finally: await manager.close()


def test_default_clock_uses_server_local(monkeypatch):
    import backend.manager as module
    from datetime import timedelta
    local=datetime(2026,10,2,0,1,tzinfo=timezone(timedelta(hours=9)))
    class Clock:
        @staticmethod
        def now(tz=None):
            assert tz is None, "default must query server local clock, not UTC"
            return local
    monkeypatch.setattr(module,"datetime",Clock)
    assert RunManager(Settings()).clock() == local


@pytest.mark.parametrize("router,deadline,warn", [(125,60,True),(125,130,False),(None,60,True)])
def test_gateway_startup_warning(caplog,router,deadline,warn):
    from fastapi.testclient import TestClient
    from backend.api import create_app
    settings=Settings(gateway_observation=True,gateway_router_timeout=router,model_timeout=deadline,
        listener_timeout=270,planner_timeout=270,evaluator_timeout=270,reporter_timeout=270,
        base_url="https://secret.invalid",api_key="secret-test-marker")
    with TestClient(create_app(settings)): pass
    assert ("gateway timeout" in caplog.text.lower()) == warn
    assert "secret" not in caplog.text
    if warn:
        assert "gateway/app.env.example" in caplog.text
        if router is None: assert "125" not in caplog.text


def test_bounded_history_atomic_snapshot():
    from fastapi.testclient import TestClient
    from backend.api import create_app
    with TestClient(create_app(Settings(test_mode=True,max_events=3))) as client:
        initial=client.post('/api/runs',json={"question":"Apple risk","mode":"test"}).json()
        rid=initial['run_id']
        client.get(f'/api/runs/{rid}/events')
        restored=client.get(f'/api/runs/{rid}?include_events=true').json()
        events=restored['retained_events']
        assert len(events)==3 and events[-1]['seq']==restored['last_seq']
        assert len({e['seq'] for e in events})==3
        assert all('retained_events' not in e['data']['snapshot'] for e in events)
        assert 'retained_events' not in client.get(f'/api/runs/{rid}').json()


def test_tzdata_works_without_os_timezone_database():
    import subprocess, sys
    result = subprocess.run([sys.executable, "-c", "from zoneinfo import reset_tzpath, ZoneInfo; reset_tzpath([]); ZoneInfo.clear_cache(); from backend.config import Settings; assert Settings(run_timezone='Asia/Seoul').run_timezone == 'Asia/Seoul'"], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("policy,total,expected", [("unknown",170,None),("output",170,0.00048),("output",150,0.0004)])
async def test_pinned_openai_adapter_preserves_raw_usage(policy,total,expected):
    import httpx
    from langchain_openai import ChatOpenAI
    usage={"prompt_tokens":100,"completion_tokens":50,"total_tokens":total,"completion_tokens_details":{"reasoning_tokens":30}}
    def wire(request):
        return httpx.Response(200,json={"id":"offline","object":"chat.completion","created":0,"model":"mock","choices":[{"index":0,"message":{"role":"assistant","content":"offline"},"finish_reason":"stop"}],"usage":usage})
    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as client:
        model=ChatOpenAI(model="mock",api_key="offline-only",base_url="http://127.0.0.1:9999/v1",http_async_client=client,max_retries=0)
        message=await model.ainvoke("offline")
        actual=message.response_metadata["token_usage"]
        assert {k:actual[k] for k in ("prompt_tokens","completion_tokens","total_tokens")} == {k:usage[k] for k in ("prompt_tokens","completion_tokens","total_tokens")}
        assert actual["completion_tokens_details"]["reasoning_tokens"] == 30
        # The pinned SDK adds nullable schema fields; it does not reconcile counts.
        data=record_model_call(run_id=None,role="Listener",call_id="a"*32,model="mock",started=monotonic(),status="success",response=SimpleNamespace(result=[message]),settings=Settings(residual_pricing=policy,token_prices={"configured-model":{"input":2,"output":4}}))
        assert data["estimated_cost_usd"] == expected
        assert data["reasoning_tokens"] == 30
    assert client.is_closed


def test_researcher_batching_guidance_keeps_dependencies_and_budgets():
    from backend.agents import ROLE_PROMPTS
    prompt=ROLE_PROMPTS['Researcher']
    for boundary in ['Batch independent', 'wait for search results', 'registered IDs', 'remaining', 'tool-call']:
        assert boundary in prompt
