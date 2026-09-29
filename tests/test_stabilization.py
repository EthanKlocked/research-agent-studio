"""Offline stabilization contracts; no live provider or credentials."""
import asyncio
import json
import pytest
from backend.agents import RoleRunner, ROLE_PROMPTS
from backend.config import Settings
from backend.errors import error_category
from backend.manager import RunManager, safe_error
from backend.mcp_client import ToolFailure
from backend.schemas import RunRequest
from test_live_resilience import STATE


def test_scope_policy_distinguishes_unavailable_from_missing_evidence():
    for role in ('Reporter', 'Evaluator'):
        prompt = ROLE_PROMPTS[role]
        assert 'dataset' in prompt and 'limitations' in prompt
        assert 'out-of-scope' in prompt and 'in-scope' in prompt
    assert 'Do not revise solely' in ROLE_PROMPTS['Evaluator']
    assert 'unsupported claims' in ROLE_PROMPTS['Evaluator']


def test_timeout_env_is_separate_and_bounded(monkeypatch):
    monkeypatch.setattr('backend.config.load_dotenv', lambda *a, **kw: None)
    env = {'LLM_REQUEST_TIMEOUT': '11', 'LISTENER_TIMEOUT': '21', 'PLANNER_TIMEOUT': '22', 'RESEARCHER_TIMEOUT': '123', 'REPORTER_TIMEOUT': '24', 'EVALUATOR_TIMEOUT': '25', 'RUN_TIMEOUT': '456'}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    s = Settings.from_env()
    assert s.model_timeout == 11
    assert [s.role_timeout(r) for r in ('Listener','Planner','Researcher','Reporter','Evaluator')] == [21,22,123,24,25]
    assert s.run_timeout == 456


@pytest.mark.parametrize('value', ['nan','inf','0','-1','abc','7201'])
def test_invalid_timeout_env_rejected(monkeypatch, value):
    monkeypatch.setattr('backend.config.load_dotenv', lambda *a, **kw: None)
    monkeypatch.setenv('RESEARCHER_TIMEOUT', value)
    with pytest.raises(ValueError, match='RESEARCHER_TIMEOUT'):
        Settings.from_env()


async def test_whole_role_budget_is_not_request_budget(monkeypatch):
    from langchain_core.messages import AIMessage
    class Agent:
        async def ainvoke(self, *a, **kw):
            await asyncio.sleep(.04)
            return {'messages':[AIMessage(content='{"summary":"done"}')]}
    runner = RoleRunner(Settings(test_mode=True, model_timeout=.01), 'test','pass')
    monkeypatch.setattr(runner.factory, 'create', lambda *a, **kw: Agent())
    assert await runner.invoke('Researcher', STATE, []) == {'summary':'done'}


async def test_role_timeout_bounds_whole_call(monkeypatch):
    class Agent:
        async def ainvoke(self, *a, **kw):
            await asyncio.sleep(10)
    runner = RoleRunner(Settings(test_mode=True, researcher_timeout=.01), 'test','pass')
    monkeypatch.setattr(runner.factory, 'create', lambda *a, **kw: Agent())
    with pytest.raises(TimeoutError):
        await runner.invoke('Researcher', STATE, [])


@pytest.mark.parametrize('reverse', [False, True])
def test_mixed_group_prioritizes_timeout(reverse):
    errors = [ToolFailure('secret'), TimeoutError('secret')]
    if reverse:
        errors.reverse()
    exc = ExceptionGroup('secret', [ValueError('secret'), ExceptionGroup('secret', errors)])
    assert error_category(exc) == 'timeout'
    assert safe_error(exc) == safe_error(TimeoutError())


@pytest.mark.parametrize('role', ['Planner','Researcher','Reporter','Evaluator'])
async def test_revision_failure_retains_previous_validated_report(monkeypatch, caplog, role):
    original = RoleRunner.invoke
    async def fail(self, current_role, state, tools, **kwargs):
        if state['iteration'] == 2 and current_role == role:
            raise ExceptionGroup('private-secret', [ToolFailure('private-secret'), TimeoutError('private-secret')])
        return await original(self, current_role, state, tools, **kwargs)
    monkeypatch.setattr(RoleRunner, 'invoke', fail)
    manager = RunManager(Settings(test_mode=True))
    initial = await manager.start(RunRequest(question='revenue risk', mode='test', scenario='revise'))
    await manager.tasks[initial['run_id']]
    final = manager.snapshot(initial['run_id'])
    assert final['status'] == 'error'
    assert final['partial_result'] == {'iteration':1, 'reason':'revision_failed'}
    previous = final['revisions'][0]
    assert final['report']['claims'] == previous['report']['claims']
    assert final['report']['summary'] == previous['report']['summary']
    assert final['report']['limitations'][-1] == '후속 수정 실행이 실패하여 이전 검증 보고서를 보존했습니다. 평가 통과가 아니며 미해결 이슈가 남아 있습니다.'
    assert final['evaluation'] == previous['evaluation']
    assert final['evaluation']['decision'] == 'revise'
    assert 'category=timeout' in caplog.text
    assert 'classes=ExceptionGroup' in caplog.text
    assert '>ToolFailure>TimeoutError' in caplog.text
    assert 'private-secret' not in caplog.text + json.dumps(final)
    assert list(manager.runs[initial['run_id']].events)[-1]['type'] == 'terminal'

async def test_failure_restores_exact_evidence_checkpoint(monkeypatch):
    import backend.manager as module
    class Graph:
        async def ainvoke(self, state, **kwargs):
            report = {'title':'old','summary':'old','claims':[{'text':'old','citation_ids':['a']}], 'limitations':[]}
            evaluation = {'decision':'revise','issues':['missing'], 'follow_up':[]}
            state.update(stage='Evaluator', iteration=1, report=report, evidence=[{'id':'a','excerpt':'original'}], evaluation=evaluation,
                         revisions=[{'iteration':1,'report':report,'evidence_ids':['a'],'evaluation':evaluation}])
            await publish('node_complete', state, {})
            state.update(stage='Evaluator', iteration=2, report={**report,'summary':'new'}, evidence=[{'id':'a','excerpt':'overwritten'}, {'id':'b'}])
            await publish('node_start', state, {})
            raise TimeoutError()
    def build(settings, mode, scenario, callback):
        nonlocal publish
        publish = callback
        return Graph()
    publish = None
    monkeypatch.setattr(module, 'build_graph', build)
    manager = RunManager(Settings(test_mode=True))
    initial = await manager.start(RunRequest(question='x', mode='test'))
    await manager.tasks[initial['run_id']]
    final = manager.snapshot(initial['run_id'])
    assert final['evidence'] == [{'id':'a','excerpt':'original'}]


def test_safe_class_logging_bounds_cycles_and_custom_names():
    from backend.errors import safe_exception_classes
    custom = type('private-secret\nforged', (Exception,), {})('secret')
    assert safe_exception_classes(custom) == 'Exception'
    cause = ToolFailure('secret')
    cause.__cause__ = cause
    assert safe_exception_classes(cause) == 'ToolFailure'
    assert len(safe_exception_classes(ExceptionGroup('secret', [ValueError('secret') for _ in range(100)])).split('>')) <= 16
    deep = ValueError('secret')
    for _ in range(100):
        deep = ExceptionGroup('secret', [deep])
    assert len(safe_exception_classes(deep).split('>')) <= 9


def test_timeout_in_wrapped_cause_and_provider_types():
    import httpx
    from openai import APITimeoutError
    for timeout in [httpx.ReadTimeout('secret'), APITimeoutError(request=httpx.Request('GET', 'https://invalid.test'))]:
        wrapped = ToolFailure('secret')
        wrapped.__cause__ = timeout
        assert error_category(wrapped) == 'timeout'


async def test_explicit_cancel_after_first_revision_stays_cancelled(monkeypatch):
    entered = asyncio.Event()
    original = RoleRunner.invoke
    async def waiting(self, role, state, tools, **kwargs):
        if role == 'Planner' and state['iteration'] == 2:
            entered.set()
            await asyncio.Event().wait()
        return await original(self, role, state, tools, **kwargs)
    monkeypatch.setattr(RoleRunner, 'invoke', waiting)
    manager = RunManager(Settings(test_mode=True))
    initial = await manager.start(RunRequest(question='x', mode='test', scenario='revise'))
    await asyncio.wait_for(entered.wait(), 10)
    final = await manager.cancel(initial['run_id'])
    assert final['status'] == 'cancelled'
    assert final['errors'] == [] and final.get('partial_result') is None


async def test_http_timeout_configuration_reaches_model(monkeypatch):
    from backend.agents import AgentFactory
    from test_live_resilience import SETTINGS
    values = []
    def model(**kwargs):
        values.append(kwargs['timeout'])
        raise RuntimeError('stop before any network')
    monkeypatch.setattr('backend.agents.ChatOpenAI', model)
    factory = AgentFactory(Settings(**SETTINGS, model_timeout=17, researcher_timeout=180), 'live', 'pass')
    try:
        with pytest.raises(RuntimeError):
            factory.create('Researcher', [])
    finally:
        await factory.close()
    assert values == [17]
