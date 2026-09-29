"""Real MCP discovery and mock-provider wire parity; no live model/network."""
import asyncio
import importlib.util

import pytest
from mcp import ClientSession
from mcp.types import ListToolsResult, Tool

from backend.mcp_client import ALLOWED, DocumentClient
from tests.test_live_resilience import GOOD, SEARCH, run_provider


async def test_model_contract_matches_real_mcp_and_dispatches_once(monkeypatch):
    advertised, dispatched = {}, []
    original_list, original_call = ClientSession.list_tools, ClientSession.call_tool
    from backend import mcp_client
    original_load = mcp_client.load_mcp_tools
    loaded = []

    async def loading(session):
        tools = await original_load(session)
        loaded.extend(tools)
        async def forbidden_dispatch(**kwargs):
            pytest.fail('Adapter execution must never bypass DocumentClient')
        for tool in tools:
            tool.coroutine = forbidden_dispatch
        return tools

    monkeypatch.setattr(mcp_client, 'load_mcp_tools', loading)

    async def listing(self, *args, **kwargs):
        result = await original_list(self, *args, **kwargs)
        advertised.update({t.name: t for t in result.tools})
        return result

    async def calling(self, name, arguments, *args, **kwargs):
        dispatched.append((name, arguments))
        return await original_call(self, name, arguments, *args, **kwargs)

    monkeypatch.setattr(ClientSession, 'list_tools', listing)
    monkeypatch.setattr(ClientSession, 'call_tool', calling)
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state['status'] == 'success'
    assert set(advertised) == ALLOWED
    assert {t.name for t in loaded} == ALLOWED
    for tool in loaded:
        assert tool.description == advertised[tool.name].description
        assert tool.args_schema == advertised[tool.name].inputSchema
    assert any(r.get('tools') for r in requests)
    for request in requests:
        for tool in request.get('tools', []):
            actual = tool['function']
            source = advertised[actual['name']]
            assert actual['description'] == source.description
            # LangChain's OpenAI wire conversion removes JSON Schema titles only.
            def without_titles(value):
                if isinstance(value, dict):
                    return {k: without_titles(v) for k, v in value.items() if k != 'title'}
                if isinstance(value, list):
                    return [without_titles(v) for v in value]
                return value
            assert actual['parameters'] == without_titles(source.inputSchema)
    assert dispatched == [('search_documents', {**SEARCH[1], 'limit': 5}), GOOD]
    assert sum(e['type'] == 'tool_complete' for e in events) == 2


@pytest.mark.parametrize('inventory', [[], ['search_documents'], ['search_documents', 'get_section', 'private-secret'], ['search_documents', 'get_section', 'get_section']])
async def test_inventory_rejected_before_research_model(monkeypatch, inventory):
    async def listing(self, *args, **kwargs):
        return ListToolsResult(tools=[Tool(name=n, description='test', inputSchema={'type': 'object', 'properties': {}}) for n in inventory])
    monkeypatch.setattr(ClientSession, 'list_tools', listing)
    state, events, requests = await run_provider(monkeypatch, [SEARCH, GOOD])
    assert state['status'] == 'error'
    assert not any('Search documents' in r['messages'][0]['content'] for r in requests)
    assert not any(e['type'] == 'tool_start' for e in events)
    assert 'private-secret' not in str(events)


async def test_discovery_pagination_is_bounded_and_does_not_spend_calls():
    class Session:
        cursors = []
        async def list_tools(self, cursor=None):
            self.cursors.append(cursor)
            name = 'search_documents' if cursor is None else 'get_section'
            return ListToolsResult(tools=[Tool(name=name, inputSchema={'type': 'object'})], nextCursor='page2' if cursor is None else None)
    client = DocumentClient(Session())
    assert hasattr(client, 'load_tools'), 'Discovery must load server-owned LangChain tools'
    assert {t.name for t in await client.load_tools()} == ALLOWED
    assert client.session.cursors == [None, 'page2']
    assert client.calls == client.corrections == 0


async def test_discovery_timeout_and_cancellation_propagate():
    entered = asyncio.Event()
    class Session:
        async def list_tools(self, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    client = DocumentClient(Session(), timeout=0.01)
    assert hasattr(client, 'load_tools')
    with pytest.raises(TimeoutError):
        await client.load_tools()
    entered.clear()
    client.timeout = 10
    task = asyncio.create_task(client.load_tools())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_concurrent_raw_calls_preserve_lock_budget_and_error_order():
    from types import SimpleNamespace
    from backend.mcp_client import RecoverableToolError, ToolFailure
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Session:
        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            entered.set()
            await release.wait()
            return SimpleNamespace(isError=False, structuredContent={'id': 'retrieved'})

    client = DocumentClient(Session(), max_tool_calls=2)
    retrieval = asyncio.create_task(client.call(*GOOD))
    await entered.wait()
    invalid = asyncio.create_task(client.call('get_section', {}))
    await asyncio.sleep(0)
    assert not invalid.done(), 'Raw validation must share the execution lock'
    assert client.calls == 1
    release.set()
    assert await retrieval == {'id': 'retrieved'}
    with pytest.raises(RecoverableToolError):
        await invalid
    assert client.unresolved_error
    assert (client.calls, client.corrections) == (2, 1)
    with pytest.raises(ToolFailure):
        await client.call(*GOOD)
    assert calls == [GOOD]


def test_shared_constraints_and_dataset_are_single_sources():
    assert importlib.util.find_spec('mcp_server.tool_schemas') is not None
    assert importlib.util.find_spec('mcp_server.dataset') is not None
    from mcp_server import dataset, server, tool_schemas
    from backend import mcp_client, agents
    assert mcp_client.SearchArguments is tool_schemas.SearchArguments
    assert mcp_client.SectionArguments is tool_schemas.SectionArguments
    assert mcp_client.SECTION_IDS is dataset.SECTION_IDS
    assert server.SECTIONS is dataset.SECTIONS
    assert server.DATA is dataset.DATA
    assert agents.get_dataset_scope is dataset.get_dataset_scope
    assert mcp_client.get_dataset_scope is dataset.get_dataset_scope
    import inspect
    for name in ('search_documents', 'get_section_tool'):
        signature = inspect.signature(getattr(server, name))
        schema = tool_schemas.SearchArguments if name == 'search_documents' else tool_schemas.SectionArguments
        for field, value in schema.model_fields.items():
            annotation = signature.parameters[field].annotation
            from pydantic import TypeAdapter
            expected = TypeAdapter(annotation).json_schema()
            actual = schema.model_json_schema()['properties'][field]
            assert all(actual[key] == val for key, val in expected.items())
