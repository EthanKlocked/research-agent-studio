"""Offline Exa integration: real MCP stdio and mock OpenAI wire protocol only."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from mcp import ClientSession
from backend.config import Settings
from backend.mcp_client import DocumentClient, RecoverableToolError, ToolFailure, document_environment
from backend.manager import RunManager
from backend.schemas import RunRequest
from tests.test_live_resilience import SETTINGS, install_provider, tool_call

KEY = 'fake-exa-integration-key'
FOUR = {'search_documents', 'get_section', 'web_search', 'read_page'}


def configured(**kw):
    return Settings(**SETTINGS, search_provider='exa', exa_api_key=KEY, **kw)


def test_explicit_configuration_and_narrow_child_environment(monkeypatch):
    monkeypatch.setenv('EXA_API_KEY', 'untrusted-inherited-key')
    monkeypatch.setenv('LLM_API_KEY', 'untrusted-llm-key')
    assert not Settings().general_web_enabled
    assert not Settings(search_provider='exa').general_web_enabled
    assert not Settings(exa_api_key=KEY).general_web_enabled
    assert configured().general_web_enabled
    assert KEY not in repr(configured())
    assert 'EXA_API_KEY' not in document_environment(enabled=False)
    env = document_environment(enabled=False, search_provider='exa', exa_api_key=KEY)
    assert env['EXA_API_KEY'] == KEY and env['SEARCH_PROVIDER'] == 'exa'
    assert 'LLM_API_KEY' not in env


async def test_capabilities_are_safe_generic_nullable_date():
    from backend.api import create_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(configured(test_mode=True))), base_url='http://testserver') as c:
        body = (await c.get('/api/config')).json()
    assert body['capabilities']['general_web'] is True
    assert body['capabilities']['search_provider'] == 'exa'
    assert body['dataset']['as_of'] is None
    assert 'Apple' not in body['dataset']['name']
    assert KEY not in json.dumps(body)


# Test-only stdio bootstrap installs an injected HTTP transport before registration.
# There is no production fixture flag, arbitrary endpoint override or network fallback.
BOOTSTRAP = '''
import asyncio, json, httpx
from mcp_server import server
from mcp_server.general_web import GeneralWebStore
MODE = MODE_VALUE
calls = {'search':0,'contents':0}
def handle(req):
    op=req.url.path.strip('/')
    calls[op]+=1
    payload=json.loads(req.content)
    if MODE=='quota' or (MODE=='revision_quota' and op=='search' and calls['search']>1):
        return httpx.Response(429, text='fake-exa-integration-key')
    url='https://example.com/climate'
    item={'url':url,'title':'Climate adaptation study','publishedDate':None}
    if op=='search':
        results=[dict(item,text='SEARCH SNIPPET NOT EVIDENCE')]
        if MODE=='empty': results=[]
        if MODE=='partial': results.append(dict(item,url='http://localhost/private'))
        return httpx.Response(200,json={'results':results})
    return httpx.Response(200,json={'results':[dict(item,text='Urban trees reduce heat exposure.')]})
store=GeneralWebStore(api_key='fake-exa-integration-key',transport=httpx.MockTransport(handle))
server.register_general_tools(server.mcp,store)
async def main():
    try:
        await server.mcp.run_stdio_async()
    finally:
        await store.close()
asyncio.run(main())
'''


def bootstrap(monkeypatch, mode='normal'):
    import backend.mcp_client as mc
    import mcp.client.stdio as stdio
    real_params = mc.StdioServerParameters
    real_spawn = stdio._create_platform_compatible_process
    processes, environments = [], []
    def params(**kw):
        environments.append(deepcopy(kw['env']))
        if kw['env'].get('SEARCH_PROVIDER') == 'exa':
            kw['args'] = ['-c', BOOTSTRAP.replace('MODE_VALUE', repr(mode))]
        return real_params(**kw)
    async def spawn(*a, **kw):
        p = await real_spawn(*a, **kw)
        processes.append(p)
        return p
    monkeypatch.setattr(mc, 'StdioServerParameters', params)
    monkeypatch.setattr(stdio, '_create_platform_compatible_process', spawn)
    return processes, environments


async def general_run(monkeypatch, *, mode='normal', cancel=False):
    processes, environments = bootstrap(monkeypatch, mode)
    dispatched, payloads = [], []
    import backend.mcp_client as mc
    discovered = {}
    original_load = mc.load_mcp_tools
    async def load(session):
        tools = await original_load(session)
        for tool in tools:
            discovered[tool.name] = deepcopy(tool.args_schema)
            async def forbidden(**kw):
                pytest.fail('Adapter execution bypassed bounded raw-call middleware')
            tool.coroutine = forbidden
        return tools
    monkeypatch.setattr(mc, 'load_mcp_tools', load)
    original = ClientSession.call_tool
    async def call(self, name, arguments, *a, **kw):
        dispatched.append(name)
        return await original(self, name, arguments, *a, **kw)
    monkeypatch.setattr(ClientSession, 'call_tool', call)
    entered = asyncio.Event()
    def respond(body):
        system=body['messages'][0]['content']
        state=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        payloads.append(state)
        if 'Interpret the user' in system:
            value={'interpreted_request':'Research urban climate adaptation'}
        elif 'Produce up to' in system:
            assert not body.get('tools')
            assert set(t['name'] for t in state['tool_context']['tools'])==FOUR
            assert state['dataset']['as_of'] is None
            assert len(processes)==1 and processes[0].returncode is None
            value={'plan':['Search climate studies then retrieve pages']}
        elif 'Search documents' in system:
            assert {t['function']['name'] for t in body['tools']}==FOUR
            def without_titles(v):
                if isinstance(v,dict): return {k:without_titles(x) for k,x in v.items() if k!='title'}
                if isinstance(v,list): return [without_titles(x) for x in v]
                return v
            for tool in body['tools']:
                assert tool['function']['parameters']==without_titles(discovered[tool['function']['name']])
            messages=[m for m in body['messages'] if m['role']=='tool']
            if not messages:
                if state['iteration']==2 and mode=='normal':
                    return tool_call('read_page',{'source_id':state['evidence'][0]['document_id']},0)
                return tool_call('web_search',{'query':'urban climate adaptation '+str(state['iteration'])},0)
            if len(messages)==1 and messages[0].get('name')!='read_page':
                data=json.loads(messages[0]['content'])
                if isinstance(data,list) and data and mode != 'snippets':
                    return tool_call('read_page',{'source_id':data[0]['source_id']},1)
            value={'summary':'Retrieved climate sources'}
        elif 'Write a concise' in system:
            value={'title':'Climate adaptation','summary':'Urban heat research','claims':[{'text':'Trees reduce heat exposure','citation_ids':[state['evidence'][0]['id']]}],'limitations':['Publication date unavailable']}
        else:
            value={'decision':'revise' if state['iteration']==1 else 'pass','issues':['Check coverage'] if state['iteration']==1 else [],'follow_up':[]}
        return {'content':json.dumps(value)}
    requests, clients=install_provider(monkeypatch,respond)
    if cancel:
        async def waiting(self,name,args,*a,**kw):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(ClientSession,'call_tool',waiting)
    manager=RunManager(configured())
    start=await manager.start(RunRequest(question='Urban climate adaptation',mode='live'))
    if cancel:
        await asyncio.wait_for(entered.wait(),10)
        await asyncio.wait_for(manager.cancel(start['run_id']),10)
    await asyncio.wait_for(manager.tasks[start['run_id']],20)
    state=manager.snapshot(start['run_id'])
    events=list(manager.runs[start['run_id']].events)
    assert len(processes)==1 and all(p.returncode is not None for p in processes)
    assert all(c.is_closed for c in clients)
    assert KEY not in json.dumps([state,events,requests])
    assert environments[0]['EXA_API_KEY']==KEY
    assert 'LLM_API_KEY' not in environments[0]
    assert sum(e['type']=='terminal' for e in events)==1
    return state,events,dispatched


async def test_real_general_mcp_graph_revision_registry_persistence(monkeypatch):
    state,events,calls=await general_run(monkeypatch)
    assert state['status']=='success', state['errors']
    assert state['iteration']==2 and len(state['evidence'])==1
    assert state['evidence'][0]['excerpt']=='Urban trees reduce heat exposure.'
    assert state['evidence'][0]['as_of'] is None
    assert calls==['web_search','read_page','read_page']
    assert sum(e['type']=='discovery_complete' and e['data']['purpose']=='planner_context' for e in events)==1
    assert {e['data']['tool'] for e in events if e['type']=='tool_start'}=={'web_search','read_page'}


@pytest.mark.parametrize('mode', ['quota','revision_quota'])
async def test_quota_never_falls_back_and_retains_only_evaluated_revision(monkeypatch,mode):
    state,events,calls=await general_run(monkeypatch,mode=mode)
    assert state['status']=='error'
    assert 'search_documents' not in calls
    if mode=='revision_quota':
        assert state['partial_result']=={'iteration':1,'reason':'revision_failed'}
        assert state['report'] and state['evaluation']['decision']=='revise'
        assert len(state['evidence'])==1
    else:
        assert state['report'] is None and not state['evidence']


@pytest.mark.parametrize('mode,expected',[('empty','empty'),('snippets','error'),('partial','success')])
async def test_general_empty_snippet_only_and_partial_metadata_results(monkeypatch,mode,expected):
    state,events,calls=await general_run(monkeypatch,mode=mode)
    assert state['status']==expected, state['errors']
    assert 'search_documents' not in calls
    if mode=='partial':
        assert len(state['evidence'])==1 and state['report']
        assert 'localhost' not in json.dumps(state)
    else:
        assert state['evidence']==[] and state['report'] is None
        assert calls==['web_search']
    assert 'SEARCH SNIPPET NOT EVIDENCE' not in json.dumps(state)


async def test_general_cancellation_reaps_persistent_process(monkeypatch):
    state,_,_=await general_run(monkeypatch,cancel=True)
    assert state['status']=='cancelled'


async def test_offline_mode_ignores_enabled_search_and_key(monkeypatch):
    processes,environments=bootstrap(monkeypatch)
    manager=RunManager(configured(test_mode=True))
    start=await manager.start(RunRequest(question='revenue',mode='test'))
    await manager.tasks[start['run_id']]
    assert manager.snapshot(start['run_id'])['status']=='success'
    assert all('EXA_API_KEY' not in e and 'SEARCH_PROVIDER' not in e for e in environments)
    assert all(p.returncode is not None for p in processes)


async def test_unknown_ids_cross_run_isolation_and_exact_inventory(monkeypatch):
    from backend.mcp_client import document_session
    bootstrap(monkeypatch)
    async with document_session(search_provider='exa',exa_api_key=KEY) as first:
        assert set(await first.list_tools())==FOUR
        metadata=await first.call('web_search',{'query':'climate'})
        sid=metadata[0]['source_id']
        assert 'excerpt' not in metadata[0]
        with pytest.raises(RecoverableToolError):
            await first.call('read_page',{'source_id':'https://example.com/climate'})
        evidence=await first.call('read_page',{'source_id':sid})
        assert first.validate_evidence(evidence)
        assert not first.validate_evidence({**evidence,'excerpt':'forged'})
        async with document_session(search_provider='exa',exa_api_key=KEY) as second:
            with pytest.raises(RecoverableToolError):
                await second.call('read_page',{'source_id':sid})
            assert not second.validate_evidence(evidence)
    async with document_session(enabled=False) as offline:
        assert set(await offline.list_tools())=={'search_documents','get_section'}
        with pytest.raises(ToolFailure):
            await offline.call('web_search',{'query':'climate'})
