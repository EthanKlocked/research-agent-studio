"""Offline feedback regressions: mock model wire and real MCP subprocess."""
import json
from copy import deepcopy
import pytest
from backend.agents import RoleRunner, ROLE_PROMPTS
from backend.config import Settings
from backend.errors import error_category, OutputValidation
from backend.mcp_client import document_session, ToolFailure
from backend.schemas import validate_citations
from tests.test_live_resilience import STATE, SETTINGS, install_provider
from tests.test_general_boundaries import meta, page
from tests.test_general_integration import bootstrap, KEY, general_run


def report(ids):
    return {'title':'KOSPI','summary':'Summary','claims':[{'text':f'Claim {i}', 'citation_ids':[sid]} for i,sid in enumerate(ids)],'limitations':[]}


async def test_seven_claims_document_ids_repair_to_exact_evidence_ids(monkeypatch):
    evidence = [page(meta(i)) for i in range(7)]
    state = deepcopy(STATE) | {'evidence': evidence}
    before = deepcopy(state)
    outputs = iter([report([e['document_id'] for e in evidence]), report([e['id'] for e in evidence])])
    requests, clients = install_provider(monkeypatch, lambda _: {'content':json.dumps(next(outputs))})
    output = await RoleRunner(Settings(**SETTINGS), 'live', 'pass').invoke('Reporter', state, [])
    assert output == report([e['id'] for e in evidence])
    assert len(requests) == 2
    for request in requests:
        payload = json.loads(next(m['content'] for m in request['messages'] if m['role']=='user'))
        assert all(set(e) == {'id','url','title','published_at','as_of','excerpt','provenance'} for e in payload['evidence'])
        assert 'exact' in request['messages'][0]['content'] and 'evidence[].id' in request['messages'][0]['content']
    assert state == before and all(c.is_closed for c in clients)


@pytest.mark.parametrize('suffix', ['', ':page:page', ':forged'])
async def test_no_alias_or_forged_citation_acceptance_after_one_repair(monkeypatch, suffix):
    e = page(meta())
    requests, _ = install_provider(monkeypatch, lambda _: {'content':json.dumps(report([e['document_id']+suffix]))})
    with pytest.raises(OutputValidation) as caught:
        await RoleRunner(Settings(**SETTINGS), 'live','pass').invoke('Reporter', deepcopy(STATE)|{'evidence':[e]}, [])
    assert error_category(caught.value) == 'validation' and len(requests) == 2


def test_citation_validator_classifies_failure_without_relaxing_identity():
    e=page(meta())
    for bad in [e['document_id'], e['id']+':forged']:
        with pytest.raises(ValueError) as caught:
            validate_citations(report([bad]), [e])
        assert error_category(caught.value) == 'validation'
    validate_citations(report([e['id']]), [e])
    with pytest.raises(ValueError) as caught:
        validate_citations(report([e['id']]), [e], validator=lambda _:False)
    assert error_category(caught.value) == 'validation'


@pytest.mark.parametrize('mode,category', [('normal','budget'),('quota','quota')])
async def test_web_failure_category_survives_real_mcp(monkeypatch, mode, category):
    bootstrap(monkeypatch, mode)
    async with document_session(search_provider='exa', exa_api_key=KEY, max_tool_calls=20) as client:
        if mode=='normal':
            for i in range(6):
                await client.call('web_search', {'query':f'query-{i}'})
        with pytest.raises(ToolFailure) as caught:
            await client.call('web_search', {'query':'private-query'})
        assert getattr(caught.value, 'web_category', None) == category
        assert KEY not in str(caught.value) and 'private-query' not in str(caught.value)


async def test_quota_logs_allowlisted_category_not_payload(monkeypatch, caplog):
    state, events, calls = await general_run(monkeypatch, mode='quota')
    assert state['status']=='error' and calls == ['web_search']
    assert 'web_category=quota' in caplog.text
    assert KEY not in caplog.text + json.dumps(events)


async def test_authoritative_run_budget_survives_revision_reset_and_cache(monkeypatch):
    bootstrap(monkeypatch)
    async with document_session(search_provider='exa', exa_api_key=KEY) as client:
        assert await client.remaining_web_budget() == {'search':6,'read':8,'status':'available'}
        hits = await client.call('web_search', {'query':'climate'})
        await client.call('read_page', {'source_id':hits[0]['source_id']})
        client.reset_budget()
        await client.call('web_search', {'query':'climate'})
        assert await client.remaining_web_budget() == {'search':5,'read':7,'status':'available'}


async def test_revision_planner_gets_actual_remaining_budget(monkeypatch):
    seen=[]
    original=RoleRunner.invoke
    async def invoke(self, role, state, tools, **kw):
        if role=='Planner': seen.append(deepcopy(getattr(self,'web_budget',None)))
        return await original(self,role,state,tools,**kw)
    monkeypatch.setattr(RoleRunner,'invoke',invoke)
    state,_,_=await general_run(monkeypatch)
    assert state['status']=='success'
    assert seen==[{'search':6,'read':8,'status':'available'}, {'search':5,'read':7,'status':'available'}]


async def test_planner_payload_remaining_and_reuse_instruction(monkeypatch):
    requests,_=install_provider(monkeypatch,lambda _: {'content':'{"plan":["Reuse evidence"]}'})
    runner=RoleRunner(Settings(**SETTINGS),'live','pass')
    runner.tool_inventory=[]
    runner.web_budget={'search':0,'read':0,'status':'available'}
    await runner.invoke('Planner',deepcopy(STATE)|{'iteration':2},[])
    payload=json.loads(next(m['content'] for m in requests[0]['messages'] if m['role']=='user'))
    assert payload['tool_context']['remaining_run_web_budget']==runner.web_budget
    assert 'reuse' in ROLE_PROMPTS['Planner'].lower() and 'exhausted' in ROLE_PROMPTS['Planner']


async def test_revision_reuses_evidence_without_any_new_tools(monkeypatch):
    original=RoleRunner.invoke
    async def invoke(self, role, state, tools, **kw):
        if role=='Researcher' and state['iteration']==2:
            return {'summary':'Reuse existing evidence; no further requests needed'}
        return await original(self,role,state,tools,**kw)
    monkeypatch.setattr(RoleRunner,'invoke',invoke)
    state,_,calls=await general_run(monkeypatch)
    assert state['status']=='success', state['errors']
    assert calls==['web_search','read_page']


async def test_citation_repair_events_are_scoped_and_share_schema_attempt_limit(monkeypatch):
    e=page(meta())
    outputs=iter(['not-json', json.dumps(report([e['document_id']]))])
    requests,_=install_provider(monkeypatch, lambda _: {'content':next(outputs)})
    runner=RoleRunner(Settings(**SETTINGS),'live','pass')
    events=[]
    async def publish(kind,state,data): events.append((kind,data))
    runner.publish=publish
    with pytest.raises(OutputValidation):
        await runner.invoke('Reporter',deepcopy(STATE)|{'evidence':[e]},[])
    assert len(requests)==2
    assert sum(kind=='repair_start' for kind,_ in events)==1
    assert [data['scope'] for kind,data in events if kind=='validation_error']==['output_schema','citations']


@pytest.mark.parametrize('category', ['budget','quota','auth','timeout','security','oversize','invalid_input','unavailable','private-secret', ['secret']])
async def test_failure_category_is_closed_and_never_parsed_from_prose(category):
    from types import SimpleNamespace
    from backend.mcp_client import DocumentClient
    from backend.errors import safe_web_category
    class Session:
        async def call_tool(self,*args):
            return SimpleNamespace(isError=True, structuredContent={'web_failure':{'category':category}},content=[])
    client=DocumentClient(Session(),general_web=True)
    with pytest.raises(ToolFailure) as caught:
        await client.call('web_search',{'query':'private-query'})
    expected=category if type(category) is str and category in {'budget','quota','auth','timeout','security','oversize','invalid_input','unavailable'} else 'unavailable'
    assert safe_web_category(caught.value)==expected
    class Prose:
        async def call_tool(self,*args):
            return SimpleNamespace(isError=True, structuredContent=None,content=[SimpleNamespace(type='text',text='quota private-secret')])
    with pytest.raises(ToolFailure) as caught:
        await DocumentClient(Prose(),general_web=True).call('web_search',{'query':'x'})
    assert safe_web_category(caught.value)=='none'


@pytest.mark.parametrize('operation,category', [('search','quota'),('contents','quota'),('contents','budget')])
async def test_mock_mcp_read_failures_and_budget_snapshot(operation,category):
    import httpx
    from mcp.server.fastmcp import FastMCP
    from mcp_server.server import register_general_tools
    from mcp_server.general_web import GeneralWebStore
    calls=[]
    def handle(request):
        op=request.url.path.strip('/')
        calls.append(op)
        if op==operation and category=='quota':
            return httpx.Response(402,text='private-secret')
        return httpx.Response(200,json={'results':[{'url':'https://example.com/article','title':'Title'}]})
    store=GeneralWebStore(api_key='fake-only',transport=httpx.MockTransport(handle),read_limit=0 if category=='budget' else 8)
    server=FastMCP('offline-feedback',log_level='CRITICAL')
    register_general_tools(server,store)
    try:
        search=await server.call_tool('web_search',{'query':'private-query'})
        result=search
        if operation=='contents':
            sid=search.structuredContent['result'][0]['source_id']
            result=await server.call_tool('read_page',{'source_id':sid})
        assert result.isError and result.structuredContent=={'web_failure':{'category':category}}
        assert 'private-' not in result.model_dump_json()
        budget=store.remaining_budget()
        if category=='quota':
            assert budget=={'search':0,'read':0,'status':'quota'}
            again=await server.call_tool('web_search',{'query':'different'})
            assert again.structuredContent=={'web_failure':{'category':'quota'}}
        else:
            assert budget=={'search':5,'read':0,'status':'available'}
            assert calls==['search']
    finally:
        await store.close()


@pytest.mark.parametrize('budget', [
    {'search':7,'read':8,'status':'available'},
    {'search':True,'read':8,'status':'available'},
    {'search':6,'read':8,'status':'private-secret'},
    {'search':6,'read':8,'status':'quota'},
    {'search':6,'read':8,'status':'available','secret':'value'},
])
async def test_malformed_budget_is_explicitly_exhausted(budget):
    from types import SimpleNamespace
    from backend.mcp_client import DocumentClient
    class Session:
        async def read_resource(self,uri):
            return SimpleNamespace(contents=[SimpleNamespace(text=json.dumps(budget))])
    assert await DocumentClient(Session(),general_web=True).remaining_web_budget()=={'search':0,'read':0,'status':'unavailable'}


async def test_reporter_terminal_validation_is_safe_and_explicit(monkeypatch,caplog):
    import tests.test_general_integration as integration
    install=integration.install_provider
    def broken_provider(mp,respond):
        def broken(body):
            if 'Write a concise' in body['messages'][0]['content']:
                return {'content':json.dumps(report(['private-secret']))}
            return respond(body)
        return install(mp,broken)
    monkeypatch.setattr(integration,'install_provider',broken_provider)
    state,events,calls=await general_run(monkeypatch)
    assert state['status']=='error' and '[Reporter/validation]' in state['errors'][0]
    assert '인용' in state['errors'][0]
    assert 'category=validation' in caplog.text
    assert 'private-secret' not in caplog.text + json.dumps(events)
    assert sum(e['type']=='repair_start' for e in events)==1
    assert calls==['web_search','read_page']


async def test_unreadable_budget_fails_closed_without_guessing():
    from backend.mcp_client import DocumentClient
    class Broken:
        async def read_resource(self, uri): raise RuntimeError('private-secret')
    client=DocumentClient(Broken(),general_web=True)
    assert await client.remaining_web_budget()=={'search':0,'read':0,'status':'unavailable'}
