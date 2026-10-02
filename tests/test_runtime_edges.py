"""Offline runtime edges: actual MCP dispatch, bounded recovery, API replay."""
import json
from datetime import datetime, timezone
import httpx
import pytest
from backend.agents import ROLE_PROMPTS, RoleRunner
from backend.manager import RunManager
from backend.config import Settings
from backend.schemas import RunRequest
from tests.test_live_resilience import SETTINGS, STATE, install_provider, tool_call
from tests.test_general_integration import bootstrap, configured
from tests.test_runtime_context import finish


@pytest.mark.parametrize('role', list(ROLE_PROMPTS))
async def test_clock_in_real_model_wire_and_same_day_provenance(monkeypatch, role):
    evidence = {'id':'d:s','title':'Today source','url':'https://example.com/source','published_at':'2026-10-02','as_of':'2026-09-30','excerpt':'Fixture fact','provenance':'fixture'}
    context = {'started_at':'2026-10-02T00:01:00+09:00','current_date':'2026-10-02','timezone':'UTC+09:00'}
    outputs = {'Listener':{'interpreted_request':'today'},'Planner':{'plan':['today']},'Researcher':{'summary':'today'},'Reporter':{'title':'today','summary':'today','claims':[{'text':'Fixture fact','citation_ids':['d:s']}],'limitations':[]},'Evaluator':{'decision':'pass','issues':[],'follow_up':[]}}
    requests, clients = install_provider(monkeypatch, lambda _: {'content':json.dumps(outputs[role])})
    await RoleRunner(Settings(**SETTINGS),'live','pass').invoke(role,STATE|{'run_context':context,'evidence':[evidence]},[])
    payload = json.loads(next(m['content'] for m in requests[0]['messages'] if m['role']=='user'))
    assert payload['run_context'] == context
    assert payload['evidence'][0]['published_at'] == '2026-10-02'
    assert payload['evidence'][0]['as_of'] == '2026-09-30'
    assert 'A date equal to current_date is not future' in requests[0]['messages'][0]['content']
    assert all(c.is_closed for c in clients)


async def test_naive_clock_rejected_before_run_or_task_creation():
    manager = RunManager(Settings(test_mode=True), clock=lambda:datetime(2026,10,2))
    with pytest.raises(ValueError,match='timezone-aware'):
        await manager.start(RunRequest(question='x',mode='test'))
    assert not manager.runs and not manager.tasks


@pytest.mark.parametrize('category', ['auth','quota','timeout','security','oversize','invalid_input','unavailable'])
async def test_provider_categories_remain_fatal_and_safe(monkeypatch, category):
    from mcp import ClientSession
    from mcp.types import CallToolResult
    bootstrap(monkeypatch)
    async def fail(*args, **kw):
        return CallToolResult(isError=True,structuredContent={'web_failure':{'category':category}},content=[])
    monkeypatch.setattr(ClientSession,'call_tool',fail)
    def respond(body):
        system=body['messages'][0]['content']
        if 'Interpret the user' in system: return {'content':'{"interpreted_request":"facts"}'}
        if 'Produce up to' in system: return {'content':'{"plan":["facts"]}'}
        return tool_call('web_search',{'query':'secret-query'},0)
    install_provider(monkeypatch,respond)
    final, events = await finish(RunManager(configured()))
    assert final['status']=='error' and f'web_category={category}' in final['errors'][0]
    assert 'secret-query' not in json.dumps(events)
    assert not final['web_budget_exhausted']


@pytest.mark.parametrize('loop', [False,True])
async def test_read_budget_on_revision_retains_evidence_and_caps_retries(monkeypatch, loop):
    import tests.test_general_integration as integration
    # Lower the actual run store limit, not a fake error string. Read first page;
    # second unique URL at revision cannot consume another paid request.
    script = integration.BOOTSTRAP.replace("url='https://example.com/climate'", "url='https://example.com/climate'+str(calls['search']) if op=='search' else payload['ids'][0]")
    script = script.replace("transport=httpx.MockTransport(handle))", "transport=httpx.MockTransport(handle),read_limit=1)")
    monkeypatch.setattr(integration,'BOOTSTRAP',script)
    processes,_ = bootstrap(monkeypatch)
    def respond(body):
        system=body['messages'][0]['content']
        state=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        if 'Interpret the user' in system: value={'interpreted_request':'climate'}
        elif 'Produce up to' in system: value={'plan':['Check climate']}
        elif 'Search documents' in system:
            messages=[m for m in body['messages'] if m['role']=='tool']
            if not messages:
                assert state['remaining_run_web_budget']['read']==(1 if state['iteration']==1 else 0)
                return tool_call('web_search',{'query':str(state['iteration'])},0)
            sid=json.loads(messages[0]['content'])[0]['source_id']
            if len(messages)==1 or (loop and state['iteration']==2):
                return tool_call('read_page',{'source_id':sid},len(messages))
            if state['iteration']==2:
                assert json.loads(messages[-1]['content'])['error']['code']=='web_budget_exhausted'
            value={'summary':'Evidence only'}
        elif 'Write a concise' in system:
            value={'title':'Climate','summary':'Partial','claims':[{'text':'Trees reduce heat exposure','citation_ids':[state['evidence'][0]['id']]}],'limitations':[]}
        else: value={'decision':'revise','issues':['More evidence needed'],'follow_up':[]}
        return {'content':json.dumps(value)}
    requests,clients=install_provider(monkeypatch,respond)
    final,events=await finish(RunManager(configured()))
    assert final['status']==('error' if loop else 'budget_exhausted'), final['errors']
    assert len(final['evidence'])==1 and final['report']
    assert final['iteration']==2
    assert final['evaluation']['decision']=='revise'
    assert final['web_budget_exhausted']==['read']
    if loop:
        assert final['partial_result']['iteration']==1
        assert sum(e['type']=='tool_start' and e['data']['snapshot']['iteration']==2 for e in events)==13
    assert all(p.returncode is not None for p in processes) and all(c.is_closed for c in clients)


async def test_unsupported_general_enabled_api_snapshot_and_replay(monkeypatch):
    from backend.api import create_app
    processes,_=bootstrap(monkeypatch)
    requests,clients=install_provider(monkeypatch,lambda _: {'content':json.dumps({'interpreted_request':'No personalized decisions','request_support':'unsupported','unsupported_reason':'개인 맞춤 투자는 지원하지 않습니다. 사실 조사를 요청해 주세요.'})})
    app=create_app(configured())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        response=await client.post('/api/runs',json={'question':'What should I buy with my retirement savings?'})
        assert response.status_code==202, response.text
        rid=response.json()['run_id']
        await app.state.manager.tasks[rid]
        state=(await client.get('/api/runs/'+rid)).json()
        events=(await client.get('/api/runs/'+rid+'/events')).text
        assert state['status']=='unsupported' and state['finished_at']
        assert '"unsupported"' in events and '"terminal"' in events
        assert '"tool_start"' not in events and '"discovery_start"' not in events
        assert state['run_context']['timezone']=='UTC'
    assert len(requests)==1 and all(c.is_closed for c in clients)
    assert all(p.returncode is not None for p in processes)


async def test_unsupported_does_not_depend_on_mcp_startup(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unsupported request must not start MCP')
    monkeypatch.setattr('backend.manager.document_session', forbidden)
    install_provider(monkeypatch, lambda _: {'content':json.dumps({'interpreted_request':'Personalized action','request_support':'unsupported','unsupported_reason':'개인 맞춤 투자 대신 사실 조사를 요청해 주세요.'})})
    final, _ = await finish(RunManager(configured()))
    assert final['status']=='unsupported' and final['errors']==[]


async def test_non_web_tool_failure_keeps_generic_reason(monkeypatch):
    from tests.test_live_resilience import run_provider
    final,events,_ = await run_provider(monkeypatch,[('forbidden-tool',{})])
    assert final['status']=='error'
    error=next(e for e in events if e['type']=='tool_error')
    assert error['data']['reason']=='자료 조회 도구가 실패했습니다.'
    assert error['data']['web_category']=='none'
