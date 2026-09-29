"""Offline HTTP/parser fixtures, never evidence of live Apple access."""
import importlib.util

import pytest

# Minimal factual rows, not a committed scraped document.
OPERATIONS = """Apple Inc.
CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)
(In millions, except number of shares and per-share amounts)
Three Months Ended              Twelve Months Ended
September 28, September 30, September 28, September 30,
2024 2023 2024 2023
Net sales:
Products $ 69,958 $ 67,184 $ 294,866 $ 298,085
Services 24,972 22,314 96,169 85,200
Total net sales (1)
94,930 89,498 391,035 383,285
Cost of sales:
Products 44,566 42,586 185,233 189,282
Services 6,485 6,485 25,119 24,855
Total cost of sales 51,051 49,071 210,352 214,137
Gross margin 43,879 40,427 180,683 169,148
Net income $ 14,736 $ 22,956 $ 93,736 $ 96,995
Net sales by category:
iPhone $ 46,222 $ 43,805 $ 201,183 $ 200,583
Mac 7,744 7,614 29,984 29,357
iPad 6,950 6,443 26,694 28,300
Wearables, Home and Accessories 9,042 9,322 37,005 39,845
Services 24,972 22,314 96,169 85,200
Total net sales $ 94,930 $ 89,498 $ 391,035 $ 383,285
\fUNRELATED NEXT PAGE
"""


def source_module():
    assert importlib.util.find_spec('mcp_server.public_sources') is not None, 'public source implementation missing'
    from mcp_server import public_sources
    return public_sources


def test_extract_financial_facts_preserves_columns_and_lineage():
    mod = source_module()
    sections = mod.extract_financials(OPERATIONS)
    assert set(sections) == {'operations', 'product-revenue'}
    assert 'USD millions' in sections['operations']
    assert 'FY2024 Q4' in sections['operations']
    assert 'FY2023 Q4' in sections['operations']
    assert 'FY2024 annual' in sections['operations']
    assert '14,736' in sections['operations']
    assert '43,879' in sections['operations']
    assert '46,222' in sections['product-revenue']
    assert 'UNRELATED' not in ''.join(sections.values())
    assert max(map(len, sections.values())) < 3000


@pytest.mark.parametrize('text', ['', OPERATIONS.replace('2024 2023 2024 2023', '2025 2024 2025 2024'), OPERATIONS.replace('Gross margin', 'Unknown metric')])
def test_changed_or_missing_financial_layout_is_explicit_error(text):
    mod = source_module()
    with pytest.raises(mod.PublicSourceError, match='layout'):
        mod.extract_financials(text)


@pytest.mark.parametrize('path', ['parser', 'store'])
def test_malformed_long_financial_row_is_bounded_in_isolated_process(path):
    import subprocess
    import sys
    from pathlib import Path

    # A thread/async timeout cannot interrupt synchronous regex backtracking.
    # Keep the regression itself killable, including the store's locked path.
    script = """
import sys
import httpx
from mcp_server import public_sources as mod
text = sys.stdin.read()
def rejected(call):
    try:
        call()
    except mod.PublicSourceError as exc:
        assert 'layout' in str(exc), str(exc)
    else:
        raise AssertionError('malformed financial row accepted')
if sys.argv[1] == 'parser':
    rejected(lambda: mod.extract_financials(text))
else:
    mod.PARSE_SECONDS = 0.02
    calls = []
    async def decoder(body):
        return text
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=decoder)
    for section in ('operations', 'product-revenue'):
        rejected(lambda: store.get_section('apple-official-fy2024-q4', section))
    assert len(calls) == 1
    assert not store._cache
    assert store._lock.acquire(blocking=False), 'failed parser retained cache lock'
    store._lock.release()
print('rejected')
"""
    text = OPERATIONS.replace('Products $ 69,958 $ 67,184 $ 294,866 $ 298,085',
                              'Products ' + '9' * 1000 + 'X', 1)
    process = subprocess.Popen(
        [sys.executable, '-c', script, path], cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8',
    )
    try:
        try:
            stdout, stderr = process.communicate(text, timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(f'{path} exceeded the 2-second malformed-row deadline') from exc
        assert process.returncode == 0, stderr
        assert stdout.strip() == 'rejected'
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


@pytest.mark.parametrize('columns', ['1234', '1 2 3', '1 2 3 4 5', '1 2 3 4X',
                                    '1 2 3 4,', '1 2 3 1,,234'])
def test_financial_rows_require_exactly_four_numeric_columns(columns):
    mod = source_module()
    text = OPERATIONS.replace('Products $ 69,958 $ 67,184 $ 294,866 $ 298,085',
                              'Products ' + columns, 1)
    with pytest.raises(mod.PublicSourceError, match='layout'):
        mod.extract_financials(text)


@pytest.mark.parametrize('columns', [' $ 69,958 $67,184 294,866 $ 298,085',
                                    '\t69,958\t67,184\t294,866\t298,085',
                                    ' (1)\n  $ 69,958 $ 67,184 $ 294,866 $ 298,085'])
def test_financial_row_layout_preserves_all_four_values(columns):
    mod = source_module()
    text = OPERATIONS.replace('Products $ 69,958 $ 67,184 $ 294,866 $ 298,085',
                              'Products' + columns, 1)
    sections = mod.extract_financials(text)
    assert 'Products: 69,958 | 67,184 | 294,866 | 298,085' in sections['operations']
    assert 'Total net sales: 94,930 | 89,498 | 391,035 | 383,285' in sections['operations']
    assert 'iPhone: 46,222 | 43,805 | 201,183 | 200,583' in sections['product-revenue']
    assert '2024-09-28' in sections['operations']
    assert '2023-09-30' in sections['operations']


def test_newsroom_extraction_ignores_scripts_and_requires_result_paragraph():
    mod = source_module()
    text = '<script>quarterly revenue fake</script><p>Apple today announced financial results for its fiscal 2024 fourth quarter. The Company posted quarterly revenue of $94.9 billion.</p><p>Navigation</p>'
    result = mod.extract_newsroom(text)
    assert '$94.9 billion' in result
    assert 'fake' not in result
    assert 'Navigation' not in result
    with pytest.raises(mod.PublicSourceError, match='layout'):
        mod.extract_newsroom('<html>Access denied</html>')


import asyncio
import hashlib
import httpx

PDF_ID = 'apple-official-fy2024-q4'
NEWS_ID = 'apple-official-q4-2024-newsroom'


def store_class():
    mod = source_module()
    assert hasattr(mod, 'PublicSourceStore'), 'bounded public source store missing'
    return mod


async def fixture_decoder(body):
    assert body.startswith(b'%PDF-')
    return OPERATIONS


def test_cache_retains_lineage_without_repeated_http_or_mutable_results():
    mod = store_class()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=fixture_decoder)
    first = store.get_section(PDF_ID, 'operations')
    assert first['url'] == mod.FINANCIAL_URL
    assert first['published_at'] == '2024-10-31'
    assert first['source_kind'] == 'official_public_document'
    assert first['source_sha256'] == hashlib.sha256(b'%PDF-test').hexdigest()
    assert first['retrieved_at'].endswith('+00:00')
    assert first['source_bytes'] == 9
    assert first['source_locator'] == 'PDF page 1: statements of operations'
    first['excerpt'] = 'modified'
    assert store.get_section(PDF_ID, 'operations')['excerpt'] != 'modified'
    assert '46,222' in store.get_section(PDF_ID, 'product-revenue')['excerpt']
    assert len(calls) == 1
    assert str(calls[0].url) == mod.FINANCIAL_URL
    assert calls[0].method == 'GET'


@pytest.mark.parametrize('document,section', [('https://evil.test/file', 'operations'), ('../../etc/passwd', 'operations'), (PDF_ID, '../operations')])
def test_unknown_source_never_calls_http(document, section):
    mod = store_class()
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: pytest.fail('network called')))
    with pytest.raises(ValueError, match='Unknown'):
        store.get_section(document, section)


def test_disabled_store_never_calls_http():
    mod = store_class()
    store = mod.PublicSourceStore(enabled=False, transport=httpx.MockTransport(lambda r: pytest.fail('network called')))
    with pytest.raises(mod.PublicSourceError, match='disabled'):
        store.get_section(PDF_ID, 'operations')


@pytest.mark.parametrize('status,headers,body,reason', [
    (302, {'location': 'https://evil.test/', 'content-type': 'application/pdf'}, b'', 'HTTP 302'),
    (403, {}, b'denied', 'HTTP 403'),
    (429, {}, b'limited', 'HTTP 429'),
    (200, {'content-type': 'text/html'}, b'<html>blocked</html>', 'content type'),
    (200, {'content-type': 'application/pdf', 'content-length': '999999999'}, b'%PDF-', 'byte limit'),
    (200, {'content-type': 'application/pdf', 'content-encoding': 'gzip'}, b'', 'encoding'),
    (200, {'content-type': 'application/pdf'}, b'not a pdf', 'PDF signature'),
])
def test_failed_sources_are_explicit_and_not_retried(status, headers, body, reason):
    mod = store_class()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, content=body)
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=fixture_decoder)
    for _ in range(3):
        with pytest.raises(mod.PublicSourceError, match=reason):
            store.get_section(PDF_ID, 'operations')
    assert len(calls) == 1


def test_stream_without_content_length_is_byte_bounded():
    mod = store_class()
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'%PDF-'
            yield b'x' * mod.MAX_SOURCE_BYTES
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-type': 'application/pdf'}, stream=Chunks())))
    with pytest.raises(mod.PublicSourceError, match='byte limit'):
        store.get_section(PDF_ID, 'operations')


def test_slow_stream_has_total_deadline(monkeypatch):
    mod = store_class()
    monkeypatch.setattr(mod, 'FETCH_SECONDS', 0.02)
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b'x'
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-type': 'application/pdf'}, stream=Slow())))
    with pytest.raises(mod.PublicSourceError, match='timeout'):
        store.get_section(PDF_ID, 'operations')


def test_network_failure_is_not_an_empty_result():
    mod = store_class()
    def handler(request):
        raise httpx.ConnectError('private transport details', request=request)
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler))
    with pytest.raises(mod.PublicSourceError, match='network failure') as error:
        store.get_section(PDF_ID, 'operations')
    assert 'private transport details' not in str(error.value)


def test_two_document_cache_has_at_most_two_requests():
    mod = store_class()
    calls = []
    html = b'<p>Apple today announced financial results for its fiscal 2024 fourth quarter. The Company posted quarterly revenue of $94.9 billion.</p>'
    def handler(request):
        calls.append(request)
        pdf = str(request.url) == mod.FINANCIAL_URL
        return httpx.Response(200, headers={'content-type': 'application/pdf' if pdf else 'text/html'}, content=b'%PDF-test' if pdf else html)
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=fixture_decoder)
    for _ in range(3):
        assert store.get_section(NEWS_ID, 'results')['excerpt']
        assert store.get_section(PDF_ID, 'operations')['excerpt']
        assert store.get_section(PDF_ID, 'product-revenue')['excerpt']
    assert len(calls) == 2


def test_missing_pdf_parser_fails_explicitly_without_http(monkeypatch):
    mod = store_class()
    monkeypatch.delenv('RESEARCH_PDFTOTEXT', raising=False)
    monkeypatch.setattr(mod.shutil, 'which', lambda name: None)
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: pytest.fail('network called')))
    with pytest.raises(mod.PublicSourceError, match='pdftotext unavailable'):
        store.get_section(PDF_ID, 'operations')



def test_server_search_returns_public_catalog_not_unfetched_evidence(monkeypatch):
    mod = store_class()
    from mcp_server import server
    assert hasattr(server, 'PUBLIC_STORE'), 'MCP public source integration missing'
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')), pdf_decoder=fixture_decoder)
    monkeypatch.setattr(server, 'PUBLIC_STORE', store)
    hits = server.search_documents('product revenue', 5)
    assert hits[0]['source_kind'] == 'official_public_document'
    assert all('excerpt' not in hit for hit in hits)
    item = next(hit for hit in hits if hit['section_id'] == 'product-revenue')
    assert item['retrieval_status'] == 'not_fetched'
    assert '46,222' in server.get_section(item['document_id'], item['section_id'])['excerpt']


def test_disabled_search_keeps_bundled_corpus(monkeypatch):
    mod = store_class()
    from mcp_server import server
    assert hasattr(server, 'PUBLIC_STORE'), 'MCP public source integration missing'
    monkeypatch.setattr(server, 'PUBLIC_STORE', mod.PublicSourceStore(enabled=False))
    assert all(hit.get('source_kind') != 'official_public_document' for hit in server.search_documents('revenue'))


def test_client_scope_and_narrow_child_environment_follow_explicit_optin(monkeypatch):
    from backend import mcp_client
    assert hasattr(mcp_client, 'document_environment'), 'MCP environment integration missing'
    monkeypatch.setenv('OPENAI_API_KEY', 'never-forward')
    monkeypatch.setenv('HTTP_PROXY', 'http://untrusted')
    monkeypatch.setenv('RESEARCH_PUBLIC_SOURCES', 'true')
    assert 'RESEARCH_PUBLIC_SOURCES' not in mcp_client.document_environment()
    monkeypatch.setenv('RESEARCH_PUBLIC_SOURCES', '1')
    env = mcp_client.document_environment()
    assert env['RESEARCH_PUBLIC_SOURCES'] == '1'
    assert not {'OPENAI_API_KEY', 'HTTP_PROXY'} & env.keys()
    scope = mcp_client.get_dataset_scope()
    assert scope['public_sources_enabled'] is True
    assert any(s['document_id'] == PDF_ID for s in scope['available_documents'])
    assert (PDF_ID, 'operations') in mcp_client.SECTION_IDS
    monkeypatch.delenv('RESEARCH_PUBLIC_SOURCES')
    assert not mcp_client.get_dataset_scope()['public_sources_enabled']
    assert all(s['document_id'] != PDF_ID for s in mcp_client.get_dataset_scope()['available_documents'])


@pytest.mark.asyncio
async def test_client_allows_exact_public_id_without_treating_remote_error_as_correction():
    from backend.mcp_client import DocumentClient, ToolFailure, RecoverableToolError
    from types import SimpleNamespace
    calls = []
    class Session:
        async def call_tool(self, name, args):
            calls.append((name, args))
            return SimpleNamespace(isError=True)
    client = DocumentClient(Session())
    with pytest.raises(ToolFailure) as error:
        await client.call('get_section', {'document_id': PDF_ID, 'section_id': 'operations'})
    assert not isinstance(error.value, RecoverableToolError)
    assert len(calls) == 1
    assert client.corrections == 0



@pytest.mark.asyncio
async def test_real_fastmcp_dispatch_does_not_nest_asyncio_run(monkeypatch):
    mod = store_class()
    from mcp_server import server
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')), pdf_decoder=fixture_decoder)
    monkeypatch.setattr(server, 'PUBLIC_STORE', store)
    result = await server.mcp.call_tool('get_section', {'document_id': PDF_ID, 'section_id': 'operations'})
    assert '14,736' in str(result)



def test_unexpected_parser_failure_is_sanitized_and_never_refetched():
    mod = store_class()
    calls = []
    async def broken_decoder(body):
        raise ValueError('internal parser details')
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=broken_decoder)
    for _ in range(3):
        with pytest.raises(mod.PublicSourceError, match='parser failure') as error:
            store.get_section(PDF_ID, 'operations')
        assert 'internal' not in str(error.value)
    assert len(calls) == 1



def test_live_smoke_requires_explicit_network_optin(monkeypatch):
    assert importlib.util.find_spec('mcp_server.smoke_public_sources') is not None, 'opt-in source smoke missing'
    from mcp_server.smoke_public_sources import run_smoke
    monkeypatch.delenv('RESEARCH_PUBLIC_SOURCES', raising=False)
    with pytest.raises(RuntimeError, match='RESEARCH_PUBLIC_SOURCES=1'):
        asyncio.run(run_smoke())



@pytest.mark.asyncio
async def test_smoke_checks_real_client_contract_without_retaining_excerpts(monkeypatch):
    assert importlib.util.find_spec('mcp_server.smoke_public_sources') is not None, 'opt-in source smoke missing'
    from mcp_server import smoke_public_sources as smoke
    from contextlib import asynccontextmanager
    mod = source_module()
    monkeypatch.setenv('RESEARCH_PUBLIC_SOURCES', '1')
    values = {key: {**entry, 'excerpt': mod.extract_financials(OPERATIONS)[entry['section_id']],
                   'retrieved_at': '2026-01-01T00:00:00+00:00', 'source_sha256': 'a' * 64,
                   'source_bytes': 9, 'retrieval_status': 'fetched'}
              for key, entry in enumerate(mod.CATALOG[:2])}
    news = {**mod.CATALOG[2], 'excerpt': '$94.9 billion', 'retrieved_at': '2026-01-01T00:00:00+00:00',
            'source_sha256': 'b' * 64, 'source_bytes': 10, 'retrieval_status': 'fetched'}
    class Client:
        async def list_tools(self):
            return ['search_documents', 'get_section']
        async def call(self, name, args):
            if name == 'search_documents':
                return list(mod.CATALOG)
            return next(s for s in [*values.values(), news] if s['document_id'] == args['document_id'] and s['section_id'] == args['section_id'])
    @asynccontextmanager
    async def session():
        yield Client()
    monkeypatch.setattr(smoke, 'document_session', session)
    result = await smoke.run_smoke()
    assert len(result['sections']) == 3
    assert result['cache_reused'] is True
    assert all('excerpt' not in entry for entry in result['sections'])



def test_concurrent_cache_misses_are_single_flight():
    from concurrent.futures import ThreadPoolExecutor
    mod = store_class()
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'%PDF-test')
    store = mod.PublicSourceStore(enabled=True, transport=httpx.MockTransport(handler), pdf_decoder=fixture_decoder)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: store.get_section(PDF_ID, 'operations'), range(3)))
    assert len(calls) == 1
    assert results[0] == results[1] == results[2]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'oversize', 'timeout', 'failure'])
async def test_pdf_subprocess_is_page_bounded_and_cleans_up(monkeypatch, mode):
    from pathlib import Path
    mod = source_module()
    paths = []
    class Process:
        returncode = None
        killed = False
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            if mode != 'timeout':
                self.stdout.feed_data(b'x' * (mod.MAX_TEXT_BYTES + 1) if mode == 'oversize' else b'page one')
                self.stdout.feed_eof()
        async def wait(self):
            self.returncode = -9 if self.killed else (1 if mode == 'failure' else 0)
            return self.returncode
        def kill(self):
            self.killed = True
    process = Process()
    async def spawn(*args, **kwargs):
        assert args[:7] == ('/trusted/pdftotext', '-f', '1', '-l', '1', '-layout', '-enc')
        assert args[7] == 'UTF-8'
        path = Path(args[8])
        assert path.read_bytes() == b'%PDF-test'
        paths.append(path)
        assert args[9] == '-'
        assert kwargs['stderr'] == asyncio.subprocess.DEVNULL
        return process
    monkeypatch.setattr(mod.asyncio, 'create_subprocess_exec', spawn)
    if mode == 'success':
        assert await mod._pdf_text(b'%PDF-test', '/trusted/pdftotext') == 'page one'
    elif mode == 'timeout':
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(mod._pdf_text(b'%PDF-test', '/trusted/pdftotext'), 0.01)
    else:
        with pytest.raises(mod.PublicSourceError):
            await mod._pdf_text(b'%PDF-test', '/trusted/pdftotext')
    assert not paths[0].exists()
    assert process.returncode is not None
    assert process.killed == (mode in ('oversize', 'timeout'))
