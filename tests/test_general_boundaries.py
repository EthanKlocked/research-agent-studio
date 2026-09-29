"""General-research admission and lifecycle regressions, all offline."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from mcp import ClientSession
from mcp.types import ListToolsResult, Tool

from backend.agents import ROLE_PROMPTS
from backend.mcp_client import DocumentClient, ToolFailure
from backend.schemas import validate_citations
from tests.test_general_integration import KEY, FOUR, bootstrap, configured
from backend.manager import RunManager
from backend.schemas import RunRequest


def test_general_role_instructions_do_not_force_financial_or_historical_scope():
    assert 'Include historical scope' not in ROLE_PROMPTS['Reporter']
    assert 'never invent product-level net income' not in ROLE_PROMPTS['Reporter']
    assert 'Use English keywords' not in ROLE_PROMPTS['Researcher']
    assert 'published_at' in ROLE_PROMPTS['Reporter']


@pytest.mark.parametrize('failure', [False, True])
def test_server_main_explicit_optin_and_closes_store(monkeypatch, failure):
    from mcp_server import server, general_web
    from tests.test_general_web import store
    s, requests = store()
    registered=[]
    monkeypatch.setenv('SEARCH_PROVIDER','exa')
    monkeypatch.setenv('EXA_API_KEY',KEY)
    monkeypatch.setattr(general_web,'GeneralWebStore',lambda **kw:s)
    monkeypatch.setattr(server,'register_general_tools',lambda target,store:registered.append((target,store)))
    async def run(**kw):
        assert registered==[(server.mcp,s)]
        if failure:
            raise RuntimeError('stop')
    monkeypatch.setattr(server.mcp,'run_stdio_async',run)
    if failure:
        with pytest.raises(RuntimeError): server.main()
    else:
        server.main()
    assert s._client.is_closed and not requests


@pytest.mark.parametrize('provider,key',[('',KEY),('other',KEY),('exa','')])
def test_server_missing_config_never_registers_or_constructs_provider(monkeypatch,provider,key):
    from mcp_server import server, general_web
    monkeypatch.setenv('SEARCH_PROVIDER',provider)
    monkeypatch.setenv('EXA_API_KEY',key)
    monkeypatch.setattr(general_web,'GeneralWebStore',lambda **kw:pytest.fail('disabled provider constructed'))
    monkeypatch.setattr(server,'register_general_tools',lambda *a:pytest.fail('disabled provider registered'))
    async def run():
        pass
    monkeypatch.setattr(server.mcp,'run_stdio_async',run)
    server.main()


@pytest.mark.parametrize('names',[['search_documents','get_section'],list(FOUR)+['shell'],list(FOUR)+['read_page']])
async def test_general_inventory_requires_exact_four(names):
    class Session:
        async def list_tools(self,**kw):
            return ListToolsResult(tools=[Tool(name=n,inputSchema={'type':'object'}) for n in names])
    with pytest.raises(ToolFailure):
        await DocumentClient(Session(),general_web=True).load_tools()


def meta(i=0):
    return {'source_id':'gw_'+format(i,'032x'),'url':f'https://example.com/{i}',
            'title':'Climate research','published_at':None,'retrieval_status':'metadata_only'}


def page(m):
    return {k:m[k] for k in ('url','title','published_at')} | {'id':m['source_id']+':page',
        'document_id':m['source_id'],'section_id':'page','as_of':None,
        'excerpt':'Retrieved climate content','provenance':'exa_contents'}


class Session:
    def __init__(self,values): self.values=iter(values)
    async def call_tool(self,name,args):
        return SimpleNamespace(isError=False, structuredContent={'result':deepcopy(next(self.values))})


@pytest.mark.parametrize('mutation',[
    {'id':'forged'}, {'document_id':'gw_'+'f'*32}, {'section_id':'snippet'},
    {'url':'https://other.example.org'}, {'url':'http://localhost'},
    {'provenance':'search_snippet'}, {'as_of':'2026-01-01'}, {'published_at':'invalid'},
    {'excerpt':'x'*12001}, {'excerpt':''}, {'extra':'invented'},
])
async def test_source_bound_admission_rejects_forged_results(mutation):
    m=meta()
    bad=page(m)|mutation
    client=DocumentClient(Session([[m],bad]),general_web=True)
    await client.call('web_search',{'query':'climate'})
    with pytest.raises(ToolFailure):
        await client.call('read_page',{'source_id':m['source_id']})
    assert not client.validate_evidence(bad)


@pytest.mark.parametrize('value',[[meta()]*6,[meta()|{'excerpt':'snippet'}],[meta()|{'source_id':'url'}]])
async def test_search_result_bounds_and_metadata_only_shape(value):
    client=DocumentClient(Session([value]),general_web=True)
    with pytest.raises(ToolFailure):
        await client.call('web_search',{'query':'climate'})
    assert not client._sources and not client._evidence


async def test_cached_evidence_is_immutable_and_source_bound_citations_reject_metadata():
    m=meta(); e=page(m)
    client=DocumentClient(Session([[m],e,e|{'excerpt':'changed'}]),general_web=True)
    await client.call('web_search',{'query':'climate'})
    output=await client.call('read_page',{'source_id':m['source_id']})
    report={'claims':[{'citation_ids':[e['id']]}]}
    validate_citations(report,[output],validator=client.validate_evidence)
    output['excerpt']='forged'
    with pytest.raises(ValueError):
        validate_citations(report,[output],validator=client.validate_evidence)
    with pytest.raises(ValueError):
        validate_citations(report,[m|{'id':e['id']}],validator=client.validate_evidence)
    with pytest.raises(ToolFailure):
        await client.call('read_page',{'source_id':m['source_id']})
    assert client.validate_evidence(e)


async def test_general_evidence_registry_enforces_eight_read_ceiling_across_revisions():
    sources=[meta(i) for i in range(9)]
    values=[sources[:5],sources[5:]]+[page(m) for m in sources]
    client=DocumentClient(Session(values),general_web=True,max_tool_calls=12)
    await client.call('web_search',{'query':'one'})
    await client.call('web_search',{'query':'two'})
    for m in sources[:8]:
        await client.call('read_page',{'source_id':m['source_id']})
    client.reset_budget()
    with pytest.raises(ToolFailure):
        await client.call('read_page',{'source_id':sources[-1]['source_id']})
    assert len(client._evidence)==8


async def test_persistent_discovery_cancellation_reaps_child_without_model(monkeypatch):
    processes,_=bootstrap(monkeypatch)
    entered=asyncio.Event()
    async def listing(self,*a,**kw):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(ClientSession,'list_tools',listing)
    from tests.test_live_resilience import install_provider
    install_provider(monkeypatch,lambda body:{'content':'{"interpreted_request":"climate"}'})
    manager=RunManager(configured())
    start=await manager.start(RunRequest(question='climate'))
    await asyncio.wait_for(entered.wait(),10)
    await asyncio.wait_for(manager.cancel(start['run_id']),10)
    assert manager.snapshot(start['run_id'])['status']=='cancelled'
    assert len(processes)==1 and processes[0].returncode is not None
    events=list(manager.runs[start['run_id']].events)
    assert not any(e['type']=='discovery_complete' for e in events)
    assert not any(e['type']=='model_start' and e['data']['role']=='Planner' for e in events)
