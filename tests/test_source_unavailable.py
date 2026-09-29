"""Offline optional-source failure contract through real FastMCP and graph."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
import json

import httpx
import pytest

from backend.mcp_client import DocumentClient, ToolFailure
from mcp_server import server
from mcp_server.public_sources import PublicSourceStore

PDF_ID = 'apple-official-fy2024-q4'
ARGS = {'document_id': PDF_ID, 'section_id': 'operations'}
UNAVAILABLE = {**ARGS, 'retrieval_status': 'unavailable', 'reason': 'public_source_unavailable'}

class DispatchSession:
    async def list_tools(self, cursor=None):
        from mcp.types import ListToolsResult
        return ListToolsResult(tools=await server.mcp.list_tools())

    async def call_tool(self, name, args):
        result = await server.mcp.call_tool(name, args)
        content, structured = result if isinstance(result, tuple) else (result, None)
        return SimpleNamespace(isError=False, content=content, structuredContent=structured)


def failing_store(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('PRIVATE_TRANSPORT_DETAIL', request=request)
    async def decoder(body):
        raise AssertionError('not reached')
    monkeypatch.setattr(server, 'PUBLIC_STORE', PublicSourceStore(
        enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=decoder))
    return calls


@pytest.mark.asyncio
async def test_public_failure_is_typed_safe_non_evidence_and_negative_cached(monkeypatch):
    calls = failing_store(monkeypatch)
    client = DocumentClient(DispatchSession())
    for section in ['operations', 'product-revenue', 'operations']:
        value = await client.call('get_section', {**ARGS, 'section_id': section})
        assert value == {**UNAVAILABLE, 'section_id': section}
    assert len(calls) == 1
    assert client.corrections == 0
    assert not client.unresolved_error
    with pytest.raises(ToolFailure):
        await client.call('unknown_tool', {})
    client.max_tool_calls = client.calls
    with pytest.raises(ToolFailure):
        await client.call('get_section', ARGS)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'document_id': 'apple-fy2024-q4'}, {'section_id': 'product-revenue'},
    {'reason': 'PRIVATE_TRANSPORT_DETAIL'}, {'excerpt': 'fake evidence'},
])
async def test_client_rejects_forged_unavailable_contract(change):
    class Session:
        async def call_tool(self, name, args):
            return SimpleNamespace(isError=False, structuredContent={**UNAVAILABLE, **change})
    with pytest.raises(ToolFailure):
        await DocumentClient(Session()).call('get_section', ARGS)


@pytest.mark.asyncio
async def test_unavailable_cannot_clear_unresolved_input_correction():
    from backend.mcp_client import RecoverableToolError
    class Session:
        async def call_tool(self, name, args):
            return SimpleNamespace(isError=False, structuredContent=UNAVAILABLE)
    client = DocumentClient(Session())
    with pytest.raises(RecoverableToolError):
        await client.call('get_section', {'document_id': 'unknown', 'section_id': 'missing'})
    assert await client.call('get_section', ARGS) == UNAVAILABLE
    assert client.unresolved_error


@pytest.mark.asyncio
@pytest.mark.parametrize('local_evidence', [True, False])
@pytest.mark.parametrize('scenario', ['pass', 'limit'])
async def test_graph_optional_failure_is_limitation_not_evidence(monkeypatch, local_evidence, scenario):
    from backend import workflow
    from backend.agents import RoleRunner, FixtureModel
    from tests.test_workflow import run_case
    calls = failing_store(monkeypatch)
    original_search = server.search_documents
    # Real create_agent fixture model, real graph and real FastMCP dispatch;
    # injected upstream fails offline, never a live-provider claim.
    class Session(DispatchSession):
        async def call_tool(self, name, args):
            if name == 'search_documents':
                hits = [ARGS, {**ARGS, 'section_id': 'product-revenue'}]
                if local_evidence:
                    hits += original_search('risk', 5)[-1:]
                return SimpleNamespace(isError=False, structuredContent={'result': hits})
            return await super().call_tool(name, args)
    @asynccontextmanager
    async def session(**kwargs):
        yield DocumentClient(Session())
    monkeypatch.setattr(workflow, 'document_session', session)
    payloads = []
    original_generate = FixtureModel._generate
    def generate(self, messages, *args, **kwargs):
        from langchain_core.messages import HumanMessage
        payload = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
        payloads.append((self.role, payload))
        return original_generate(self, messages, **kwargs)
    monkeypatch.setattr(FixtureModel, '_generate', generate)
    original_invoke = RoleRunner.invoke
    async def invoke(self, role, *args, **kwargs):
        output = await original_invoke(self, role, *args, **kwargs)
        if role == 'Reporter':
            output['limitations'] = [f'Existing limitation {i}' for i in range(8)]
        return output
    monkeypatch.setattr(RoleRunner, 'invoke', invoke)
    manager, result = await run_case(scenario)
    assert len(calls) == 1
    assert 'PRIVATE_TRANSPORT_DETAIL' not in str(result)
    assert len(result['unavailable_sources']) == 2
    assert all(e.get('retrieval_status') != 'unavailable' for e in result['evidence'])
    if local_evidence:
        assert result['status'] == ('limit_reached' if scenario == 'limit' else 'success'), result
        assert len(result['unavailable_sources']) == 2
        for role in ['Reporter', 'Evaluator']:
            assert next(p for r, p in payloads if r == role)['unavailable_sources'] == result['unavailable_sources']
        assert any(PDF_ID in text for text in result['report']['limitations'])
        assert all(PDF_ID not in c for claim in result['report']['claims'] for c in claim['citation_ids'])
    else:
        assert result['status'] == 'error', result
        assert result['report'] is None
        assert not any(r == 'Reporter' for r, p in payloads)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers,body', [
    (302, {'location': 'https://evil.test/'}, b''),
    (200, {'content-type': 'text/html'}, b'blocked'),
    (200, {'content-type': 'application/pdf', 'content-length': '999999999'}, b'%PDF-'),
    (200, {'content-type': 'application/pdf', 'content-encoding': 'gzip'}, b''),
    (200, {'content-type': 'application/pdf'}, b'not-pdf'),
])
async def test_disabled_source_and_security_guards_remain_fatal(monkeypatch, status, headers, body):
    monkeypatch.setattr(server, 'PUBLIC_STORE', PublicSourceStore(enabled=False))
    with pytest.raises(ToolFailure):
        await DocumentClient(DispatchSession()).call('get_section', ARGS)
    async def decoder(body):
        return ''
    monkeypatch.setattr(server, 'PUBLIC_STORE', PublicSourceStore(enabled=True,
        transport=httpx.MockTransport(lambda r: httpx.Response(status, headers=headers, content=body)),
        pdf_decoder=decoder))
    with pytest.raises(ToolFailure):
        await DocumentClient(DispatchSession()).call('get_section', ARGS)
