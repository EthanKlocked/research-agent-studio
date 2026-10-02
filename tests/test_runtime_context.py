"""Runtime feedback: deterministic clocks and offline provider/MCP protocol."""
import json
from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError
from backend.agents import RoleRunner
from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import Interpretation, RunRequest
from tests.test_live_resilience import SETTINGS, install_provider, tool_call
from tests.test_general_integration import bootstrap, configured


async def finish(manager, question='오늘 자료를 조사해 주세요'):
    initial = await manager.start(RunRequest(question=question, mode='live'))
    await manager.tasks[initial['run_id']]
    return manager.snapshot(initial['run_id']), list(manager.runs[initial['run_id']].events)


async def test_stable_aware_clock_all_roles_and_revisions(monkeypatch):
    from backend.agents import FixtureModel
    seen = []
    original = FixtureModel._generate
    def generate(self, messages, *args, **kw):
        from langchain_core.messages import HumanMessage
        payload = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
        seen.append((self.role, payload))
        return original(self, messages, **kw)
    monkeypatch.setattr(FixtureModel, '_generate', generate)
    clock_calls = []
    def clock():
        clock_calls.append(True)
        return datetime(2026, 10, 2, 0, 1, tzinfo=timezone(timedelta(hours=9)))
    manager = RunManager(Settings(test_mode=True), clock=clock)
    initial = await manager.start(RunRequest(question='today', mode='test', scenario='revise'))
    await manager.tasks[initial['run_id']]
    final = manager.snapshot(initial['run_id'])
    assert final['status'] == 'success'
    context = final['run_context']
    assert context == {'started_at':'2026-10-02T00:01:00+09:00', 'current_date':'2026-10-02', 'timezone':'UTC+09:00'}
    assert len(clock_calls) == 1
    assert {role for role, _ in seen} == {'Listener','Planner','Researcher','Reporter','Evaluator'}
    assert all(payload['run_context'] == context for _, payload in seen)
    assert any(payload['iteration'] == 2 for _, payload in seen)
    assert all(e['as_of'] == '2024-09-28' for e in final['evidence'])


@pytest.mark.parametrize('support', ['unsupported', 'supported', 'partial', 'unknown'])
async def test_listener_support_is_explicit_not_keyword_ban(monkeypatch, support):
    def respond(body):
        if 'Interpret the user' in body['messages'][0]['content']:
            return {'content':json.dumps({'interpreted_request':'Personalized stock picks versus factual company research',
                'request_support':support, 'unsupported_reason':'개인 맞춤 종목 추천은 제공하지 않습니다. 기업 공시의 사실 비교는 조사할 수 있습니다.' if support=='unsupported' else None})}
        raise ConnectionError('stop after supported routing')
    requests, clients = install_provider(monkeypatch, respond)
    manager = RunManager(Settings(**SETTINGS))
    final, events = await finish(manager, 'stock recommendation market company facts')
    if support == 'unsupported':
        assert final['status'] == 'unsupported'
        assert final['unsupported_reason'] and final['errors'] == []
        assert final['report'] is None and final['evaluation'] is None and final['evidence'] == []
        assert final['stage'] == 'Listener' and final['iteration'] == 0
        assert len(requests) == 1
        assert not any(e['type'] in ('discovery_start','tool_start') for e in events)
    else:
        assert final['status'] == 'error' and final['stage'] == 'Planner'
    assert events[-1]['type'] == 'terminal' and final['finished_at']
    assert all(c.is_closed for c in clients)


def test_unsupported_explanation_required_and_legacy_preserved():
    assert Interpretation.model_validate({'interpreted_request':'legacy'}).request_support == 'unknown'
    for reason in (None, '', '   '):
        with pytest.raises(ValidationError):
            Interpretation.model_validate({'interpreted_request':'topic','request_support':'unsupported','unsupported_reason':reason})


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('decision', ['pass', 'revise'])
async def test_local_budget_is_recoverable_but_never_research_success(monkeypatch, existing, decision):
    processes, _ = bootstrap(monkeypatch)
    def respond(body):
        system = body['messages'][0]['content']
        payload = json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        if 'Interpret the user' in system:
            value = {'interpreted_request':'climate'}
        elif 'Produce up to' in system:
            value = {'plan':['Research climate']}
        elif 'Search documents' in system:
            assert payload['remaining_run_web_budget'] == {'search':6,'read':8,'status':'available'}
            messages = [m for m in body['messages'] if m['role']=='tool']
            n = len(messages)
            if existing and n == 1:
                sid = json.loads(messages[0]['content'])[0]['source_id']
                return tool_call('read_page', {'source_id':sid}, n)
            if n < (8 if existing else 7):
                return tool_call('web_search', {'query':f'climate {n}'}, n)
            last = json.loads(messages[-1]['content'])
            assert last['error']['code'] == 'web_budget_exhausted'
            assert last['remaining_run_web_budget'] == {'search':0,'read':7 if existing else 8,'status':'available'}
            value = {'summary':'Use existing evidence only; search budget exhausted'}
        elif 'Write a concise' in system:
            assert payload['web_budget_exhausted'] == ['search']
            value = {'title':'Limited climate evidence','summary':'Partial research','claims':[{'text':'Trees reduce heat exposure','citation_ids':[payload['evidence'][0]['id']]}],'limitations':[]}
        else:
            value = {'decision':decision,'issues':['Coverage incomplete'] if decision=='revise' else [],'follow_up':[]}
        return {'content':json.dumps(value)}
    requests, clients = install_provider(monkeypatch, respond)
    final, events = await finish(RunManager(configured()))
    assert final['status'] == 'budget_exhausted', final['errors']
    assert final['web_budget_exhausted'] == ['search'] and final['errors'] == []
    assert final['iteration'] == 1
    assert bool(final['evidence']) == existing
    assert bool(final['report']) == existing
    if existing:
        assert '예산' in final['report']['limitations'][0]
    assert any(e['type']=='tool_error' and e['data'].get('web_category')=='budget' and e['data'].get('recoverable') for e in events)
    assert all(p.returncode is not None for p in processes)
    assert all(c.is_closed for c in clients)


async def test_quota_user_reason_is_safe_not_empty(monkeypatch):
    from tests.test_general_integration import general_run
    final, events, _ = await general_run(monkeypatch, mode='quota')
    assert final['status'] == 'error'
    assert 'web_category=quota' in final['errors'][0]
    assert '할당량' in final['errors'][0]
    assert any(e['data'].get('web_category') == 'quota' for e in events if e['type']=='tool_error')
