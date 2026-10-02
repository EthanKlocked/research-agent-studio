"""Truthful progress and metadata-only Planner context; no live providers."""
import asyncio
import json
import re

import pytest
from mcp import ClientSession
from mcp.types import ListToolsResult, Tool

from backend.agents import RoleRunner
from backend.config import Settings
from tests.test_live_resilience import GOOD, SEARCH, SETTINGS, STATE, install_provider, run_provider


async def test_real_inventory_precedes_planning_and_never_grants_planner_tools(monkeypatch):
    discovered = {}
    original = ClientSession.list_tools
    async def listing(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        discovered.update({t.name: t for t in result.tools})
        return result
    monkeypatch.setattr(ClientSession, 'list_tools', listing)
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state['status'] == 'success'
    planner = next(r for r in requests if 'Produce up to' in r['messages'][0]['content'])
    payload = json.loads(planner['messages'][1]['content'])
    assert 'tool_context' in payload
    context = payload['tool_context']
    assert not planner.get('tools')
    assert context['source'] == 'mcp_discovery'
    assert context['executable_by_planner'] is False
    assert context['budgets'] == {'max_tool_calls':12, 'max_tool_corrections':2, 'mcp_timeout_seconds':10}
    assert context['coverage'] == payload['dataset']
    assert [t['name'] for t in context['tools']] == sorted(discovered)
    for tool in context['tools']:
        raw = discovered[tool['name']]
        assert tool['description'] == raw.description
        assert tool['input_schema']['properties'].keys() == raw.inputSchema['properties'].keys()
        for field, schema in tool['input_schema']['properties'].items():
            assert schema['type'] == raw.inputSchema['properties'][field]['type']
    kinds = [e['type'] for e in events]
    discovery = next(i for i,e in enumerate(events) if e['type']=='discovery_complete' and e['data']['purpose']=='planner_context')
    planning = next(i for i,e in enumerate(events) if e['type']=='model_start' and e['data']['role']=='Planner')
    assert discovery < planning
    assert kinds[-1] == 'terminal'
    assert sum(k=='terminal' for k in kinds)==1
    assert all('tool_context' not in e['data']['snapshot'] for e in events)
    starts = {e['data']['tool_call_id']:i for i,e in enumerate(events) if e['type']=='tool_start'}
    assert len(starts)==2
    for i,e in enumerate(events):
        if e['type']=='tool_complete':
            assert starts[e['data']['tool_call_id']] < i
    assert all(re.fullmatch('[0-9a-f]{32}', key) for key in starts)
    model_starts = [e for e in events if e['type']=='model_start']
    model_ends = [e for e in events if e['type']=='model_complete']
    assert len(model_starts)==len(requests)==len(model_ends)
    assert {e['data']['model_call_id'] for e in model_starts} == {e['data']['model_call_id'] for e in model_ends}


async def test_discovery_mismatch_fails_before_planning(monkeypatch):
    async def listing(self, *args, **kwargs):
        return ListToolsResult(tools=[Tool(name='secret', inputSchema={'type':'object'})])
    monkeypatch.setattr(ClientSession,'list_tools',listing)
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state['status']=='error'
    assert not any('Produce up to' in r['messages'][0]['content'] for r in requests)
    assert not any(e['type']=='discovery_complete' for e in events)
    assert not any(e['type']=='tool_start' for e in events)
    assert 'secret' not in json.dumps(events)


async def test_repair_progress_tracks_actual_calls_not_scheduled_work(monkeypatch):
    replies = iter(['{"interpreted_request":42}', '{"interpreted_request":"ok"}'])
    requests, _ = install_provider(monkeypatch, lambda _: {'content':next(replies)})
    runner = RoleRunner(Settings(**SETTINGS), 'live','pass')
    events = []
    async def publish(kind, state, data):
        events.append((kind,data))
    runner.publish = publish
    assert await runner.invoke('Listener',STATE,[]) == {'interpreted_request':'ok'}
    assert [k for k,d in events] == ['model_start','model_complete','validation_start','validation_error','repair_start','model_start','model_complete','validation_start','validation_complete']
    assert len(requests)==2
    assert [d['attempt'] for k,d in events if k=='model_start']==[1,2]
    assert all(set(d) <= {'role', 'attempt', 'scope', 'model_call_id', 'observation'} for k,d in events)
    observations = [d['observation'] for k,d in events if k == 'model_complete']
    assert len(observations) == 2
    assert all(o['served_by'] is None and o['fallback'] is None for o in observations)
    assert all(set(o) == {'run_id', 'role', 'model_call_id', 'model', 'gateway_call_id', 'gateway_model_id',
                           'served_by', 'fallback', 'status', 'latency_ms', 'input_tokens', 'output_tokens',
                           'total_tokens', 'reasoning_tokens', 'unexplained_token_residual', 'usage_source',
                           'estimated_cost_usd', 'billing_cost_usd', 'gateway_model_name', 'attempted_fallbacks', 'rate_limit_remaining_requests'} for o in observations)


async def test_provider_failure_has_no_completion_validation_or_repair(monkeypatch):
    def fail(_):
        raise ConnectionError('secret-provider-error')
    install_provider(monkeypatch, fail)
    runner = RoleRunner(Settings(**SETTINGS), 'live','pass')
    events=[]
    async def publish(kind,state,data): events.append((kind,data))
    runner.publish=publish
    with pytest.raises(Exception):
        await runner.invoke('Listener',STATE,[])
    assert [k for k,d in events] == ['model_start','model_error']
    assert 'secret' not in json.dumps(events)


async def test_fatal_tool_attempt_is_correlated_without_provider_details(monkeypatch):
    state, events, _ = await run_provider(monkeypatch, [('private-secret', {})])
    assert state['status']=='error'
    start=next(e for e in events if e['type']=='tool_start')
    error=next(e for e in events if e['type']=='tool_error')
    assert error['data']['tool_call_id']==start['data']['tool_call_id']
    assert error['data']['tool']=='unknown'
    assert 'private-secret' not in json.dumps(events)
    assert not any(e['type']=='tool_complete' for e in events)


async def test_report_citation_validation_has_its_own_progress(monkeypatch):
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state['status']=='success'
    citations=[e['type'] for e in events if e['data'].get('scope')=='citations']
    assert citations==['validation_start','validation_complete']
    planner=next(r for r in requests if 'Produce up to' in r['messages'][0]['content'])
    assert 'tool_context' in planner['messages'][0]['content']
    assert 'untrusted' in planner['messages'][0]['content']


async def test_planner_metadata_is_cached_after_session_closure(monkeypatch):
    from backend.agents import FixtureModel
    from backend.manager import RunManager
    from backend.schemas import RunRequest
    import mcp.client.stdio as stdio
    processes, payloads, dispatched = [], [], []
    original_spawn = stdio._create_platform_compatible_process
    original_generate = FixtureModel._agenerate
    original_call = ClientSession.call_tool
    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        return process
    async def call(self, name, arguments, *args, **kwargs):
        dispatched.append(name)
        return await original_call(self, name, arguments, *args, **kwargs)
    async def generate(self, messages, *args, **kwargs):
        if self.role == 'Planner':
            assert all(p.returncode is not None for p in processes)
            payloads.append(json.loads(next(m.content for m in messages if m.type=='human')))
            if len(payloads)==1:
                assert len(processes)==1 and not dispatched
        return await original_generate(self, messages, *args, **kwargs)
    monkeypatch.setattr(stdio, '_create_platform_compatible_process', spawn)
    monkeypatch.setattr(ClientSession, 'call_tool', call)
    monkeypatch.setattr(FixtureModel, '_agenerate', generate)
    manager=RunManager(Settings(test_mode=True,max_tool_calls=8,max_tool_corrections=1))
    state=await manager.start(RunRequest(question='revenue risk', mode='test', scenario='revise'))
    await manager.tasks[state['run_id']]
    assert manager.snapshot(state['run_id'])['status']=='success'
    assert len(payloads)==2 and len(processes)==3
    assert payloads[0]['tool_context']==payloads[1]['tool_context']
    assert payloads[0]['tool_context']['budgets']['max_tool_calls']==8
    assert payloads[0]['tool_context']['budgets']['max_tool_corrections']==1
    events=list(manager.runs[state['run_id']].events)
    assert sum(e['type']=='discovery_complete' and e['data']['purpose']=='planner_context' for e in events)==1
    assert all(p.returncode is not None for p in processes)


async def test_waiting_model_has_only_real_start_and_no_fabricated_progress(monkeypatch):
    from backend.agents import FixtureModel
    entered=asyncio.Event()
    async def wait(self,*args,**kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(FixtureModel,'_agenerate',wait)
    runner=RoleRunner(Settings(test_mode=True),'test','pass')
    events=[]
    async def publish(kind,state,data): events.append((kind,data))
    runner.publish=publish
    task=asyncio.create_task(runner.invoke('Listener',STATE,[]))
    await asyncio.wait_for(entered.wait(),2)
    assert [k for k,d in events]==['model_start']
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert [k for k,d in events]==['model_start']


def test_metadata_sanitization_is_bounded_structural_and_nonmutating():
    from backend.mcp_client import planner_tool_metadata
    from types import SimpleNamespace
    schema={'type':'object','properties':{'query':{'type':'string','maxLength':300,'default':'private-secret','examples':['private-secret'],'description':'private-secret'},'private-secret':{'type':'string'}},'required':['query','private-secret'],'$id':'private-secret'}
    tools=[SimpleNamespace(name='search_documents',description='Search\x00 documents\n'+'x'*2000,args_schema=schema)]
    result=planner_tool_metadata(tools)
    text=json.dumps(result)
    assert 'private-secret' not in text
    assert '\\u0000' not in text
    assert len(result[0]['description'])<=600
    assert result[0]['input_schema']=={'type':'object','properties':{'query':{'type':'string','maxLength':300}},'required':['query']}
    assert schema['properties']['query']['default']=='private-secret'
