"""Exact Apple historical sources only; no model-supplied URLs or paths."""
import asyncio
import hashlib
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class PublicSourceError(RuntimeError):
    """A public source could not be fetched or validated; never an empty search."""


class PublicSourceSecurityError(PublicSourceError):
    """A source safety bound failed; never downgraded to optional absence."""


class UnavailableSource(BaseModel):
    """Closed protocol result: no evidence, exception text, or arbitrary URLs."""
    model_config = ConfigDict(strict=True, extra='forbid')
    document_id: str
    section_id: str
    retrieval_status: Literal['unavailable'] = 'unavailable'
    reason: Literal['public_source_unavailable'] = 'public_source_unavailable'

    @model_validator(mode='after')
    def allowlisted(self):
        if (self.document_id, self.section_id) not in PUBLIC_SECTION_IDS:
            raise ValueError('Unknown public source')
        return self


COLUMN_NOTE = ('USD millions; columns in source order: FY2024 Q4 (three months ended '
               '2024-09-28), FY2023 Q4 (2023-09-30), FY2024 annual (twelve months '
               'ended 2024-09-28), FY2023 annual (2023-09-30). GAAP, unaudited. '
               'Gross margin is a dollar amount, not a percentage.\n')


def extract_financials(text: str) -> dict[str, str]:
    page = text.split('\f', 1)[0]
    normalized = ' '.join(page.split())
    if not all(marker in normalized for marker in (
        'STATEMENTS OF OPERATIONS', 'Three Months Ended', 'Twelve Months Ended',
        'September 28,', 'September 30,', '2024 2023 2024 2023',
        'Net sales by category:', 'Cost of sales:',
    )):
        raise PublicSourceError('Public source financial layout changed or missing')
    operations, categories = page.split('Net sales by category:', 1)
    # Select factual rows only. Never return the whole PDF or prose notes.
    def rows(block, labels):
        result = []
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        for label in labels:
            found = False
            for index, line in enumerate(lines):
                if not line.startswith(label):
                    continue
                remainder = line[len(label):]
                if remainder and not remainder[0].isspace():
                    continue
                found = True
                remainder = remainder.strip()
                if remainder.startswith('(1)'):
                    remainder = remainder[3:].strip()
                # pdftotext can put the four columns below the footnoted label.
                if not remainder and index + 1 < len(lines):
                    remainder = lines[index + 1]
                # At most four amounts plus four standalone currency markers.
                # Never partition a digit run using repeated optional regexes:
                # synchronous backtracking cannot be bounded by asyncio timeouts.
                tokens = remainder.split(maxsplit=8)
                values = []
                cursor = 0
                while cursor < len(tokens) and len(values) < 4:
                    token = tokens[cursor]
                    cursor += 1
                    if token == '$' and cursor < len(tokens):
                        token = tokens[cursor]
                        cursor += 1
                    elif token.startswith('$'):
                        token = token[1:]
                    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)', token):
                        raise PublicSourceError('Public source financial layout changed or missing')
                    values.append(token)
                if len(values) != 4 or cursor != len(tokens):
                    raise PublicSourceError('Public source financial layout changed or missing')
                result.append(label + ': ' + ' | '.join(values))
            if not found:
                raise PublicSourceError('Public source financial layout changed or missing')
        return '\n'.join(result)
    sales, costs = operations.split('Cost of sales:', 1)
    return {
        'operations': COLUMN_NOTE + 'Net sales:\n' + rows(sales, ['Products', 'Services', 'Total net sales'])
        + '\nCost of sales and earnings:\n' + rows(costs, ['Products', 'Services', 'Total cost of sales', 'Gross margin', 'Net income']),
        'product-revenue': COLUMN_NOTE + 'Net sales by category:\n' + rows(categories, ['iPhone', 'Mac', 'iPad', 'Wearables, Home and Accessories', 'Services', 'Total net sales']),
    }


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.block = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('p', 'div') and not self.skip:
            self.flush()

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in ('p', 'div') and not self.skip:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.block.append(data)

    def flush(self):
        value = ' '.join(''.join(self.block).split())
        if value:
            self.parts.append(value)
        self.block = []


def extract_newsroom(text: str) -> str:
    parser = _Paragraphs()
    parser.feed(text)
    parser.flush()
    for paragraph in parser.parts:
        if ('fiscal 2024 fourth quarter' in paragraph and 'quarterly revenue' in paragraph
                and len(paragraph) <= 2000):
            return paragraph
    raise PublicSourceError('Public source newsroom layout changed or missing')


# Fixed two-document catalog. Metadata is discovery, not fetched evidence.
NEWSROOM_URL = 'https://www.apple.com/newsroom/2024/10/apple-reports-fourth-quarter-results/'
FINANCIAL_URL = 'https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf'
MAX_SOURCE_BYTES = 6 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024
FETCH_SECONDS = 6.0
PARSE_SECONDS = 2.0
CATALOG = (
    {'document_id': 'apple-official-fy2024-q4', 'section_id': 'operations',
     'title': 'Apple FY2024 Q4 official financial statements: net income, revenue, gross margin',
     'url': FINANCIAL_URL, 'source_locator': 'PDF page 1: statements of operations',
     'keywords': 'apple revenue income earnings sales gross margin products services net profit 매출 순이익 매출총이익 이익률 실적'},
    {'document_id': 'apple-official-fy2024-q4', 'section_id': 'product-revenue',
     'title': 'Apple FY2024 Q4 official financial statements: product category revenue',
     'url': FINANCIAL_URL, 'source_locator': 'PDF page 1: net sales by category',
     'keywords': 'apple iphone ipad mac wearables home accessories services product revenue category 아이폰 아이패드 맥 제품별 매출 서비스'},
    {'document_id': 'apple-official-q4-2024-newsroom', 'section_id': 'results',
     'title': 'Apple FY2024 Q4 official newsroom results',
     'url': NEWSROOM_URL, 'source_locator': 'Opening fiscal 2024 fourth-quarter results paragraph',
     'keywords': 'apple revenue earnings diluted eps fourth quarter 실적 매출 주당순이익'},
)
for _entry in CATALOG:
    _entry.update(id=_entry['document_id'] + ':' + _entry['section_id'],
                  published_at='2024-10-31', as_of='2024-09-28',
                  source_kind='official_public_document', retrieval_status='not_fetched')
PUBLIC_SECTION_IDS = frozenset((s['document_id'], s['section_id']) for s in CATALOG)


def public_sources_enabled():
    return os.environ.get('RESEARCH_PUBLIC_SOURCES') == '1'


async def _pdf_text(body: bytes, executable: str) -> str:
    # Temporary bytes are deleted even on failure; only page 1 factual rows survive.
    with tempfile.TemporaryDirectory(prefix='research-apple-') as directory:
        path = Path(directory) / 'financials.pdf'
        path.write_bytes(body)
        process = await asyncio.create_subprocess_exec(
            executable, '-f', '1', '-l', '1', '-layout', '-enc', 'UTF-8', str(path), '-',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            assert process.stdout is not None
            output = await process.stdout.read(MAX_TEXT_BYTES + 1)
            # read(n) may return fewer than n before EOF.
            while len(output) <= MAX_TEXT_BYTES:
                chunk = await process.stdout.read(MAX_TEXT_BYTES + 1 - len(output))
                if not chunk:
                    break
                output += chunk
            if len(output) > MAX_TEXT_BYTES:
                raise PublicSourceSecurityError('Public source PDF text byte limit exceeded')
            if await process.wait() != 0:
                raise PublicSourceError('Public source PDF parser failed')
            return output.decode('utf-8', errors='strict')
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


class PublicSourceStore:
    """Per-MCP-process snapshot: two HTTP attempts max, no retries or refresh.

    Positive and negative cache share the same fixed document IDs. Cache lifetime
    is the MCP session lifetime; no persistent source redistribution or stale reuse.
    """
    def __init__(self, *, enabled=False, transport=None, pdf_decoder=None):
        self.enabled = enabled
        self.transport = transport
        self.pdf_decoder = pdf_decoder
        self._cache = {}
        self._failures = {}
        self._lock = threading.Lock()

    def get_section(self, document_id, section_id):
        if (document_id, section_id) not in PUBLIC_SECTION_IDS:
            raise ValueError('Unknown document or section ID')
        if not self.enabled:
            raise PublicSourceError('Public source retrieval disabled; set RESEARCH_PUBLIC_SOURCES=1')
        with self._lock:
            if document_id in self._failures:
                error_type, message = self._failures[document_id]
                raise error_type(message)
            if document_id not in self._cache:
                try:
                    self._cache[document_id] = asyncio.run(self._load(document_id))
                except PublicSourceError as exc:
                    self._failures[document_id] = (type(exc), str(exc))
                    raise
                except Exception as exc:
                    # Fail closed even for an unexpected parser/transport defect.
                    self._failures[document_id] = (PublicSourceError, 'Public source decoding or parser failure')
                    raise PublicSourceError(self._failures[document_id][1]) from exc
            return dict(self._cache[document_id][section_id])

    async def _download(self, url, is_pdf):
        async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                                    follow_redirects=False, timeout=2.0) as client:
            async with client.stream('GET', url, headers={
                'Accept': 'application/pdf' if is_pdf else 'text/html',
                'Accept-Encoding': 'identity',
                'User-Agent': 'ResearchAgentStudio/0.1 (bounded public financial research)',
            }) as response:
                if 300 <= response.status_code < 400:
                    raise PublicSourceSecurityError(f'Public source HTTP {response.status_code}; no redirects or retries')
                if response.status_code != 200:
                    raise PublicSourceError(f'Public source HTTP {response.status_code}; no redirects or retries')
                expected = 'application/pdf' if is_pdf else 'text/html'
                if response.headers.get('content-type', '').split(';')[0].strip().lower() != expected:
                    raise PublicSourceSecurityError('Public source unexpected content type')
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise PublicSourceSecurityError('Public source unsupported content encoding')
                length = response.headers.get('content-length')
                if length and (not length.isdecimal() or int(length) > MAX_SOURCE_BYTES):
                    raise PublicSourceSecurityError('Public source byte limit exceeded')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_SOURCE_BYTES:
                        raise PublicSourceSecurityError('Public source byte limit exceeded')
                    body.extend(chunk)
                return bytes(body)

    async def _load(self, document_id):
        entries = [s for s in CATALOG if s['document_id'] == document_id]
        url = entries[0]['url']  # selected from exact ID catalog, never user input
        is_pdf = url == FINANCIAL_URL
        executable = None
        if is_pdf and self.pdf_decoder is None:
            executable = shutil.which(os.environ.get('RESEARCH_PDFTOTEXT', '').strip() or 'pdftotext')
            if not executable:
                raise PublicSourceError('Public source pdftotext unavailable; install Poppler or set RESEARCH_PDFTOTEXT')
        try:
            body = await asyncio.wait_for(self._download(url, is_pdf), FETCH_SECONDS)
            if is_pdf:
                if not body.startswith(b'%PDF-'):
                    raise PublicSourceSecurityError('Public source invalid PDF signature')
                if self.pdf_decoder:
                    decode = self.pdf_decoder(body)
                else:
                    assert executable is not None
                    decode = _pdf_text(body, executable)
                text = await asyncio.wait_for(decode, PARSE_SECONDS)
                if len(text.encode('utf-8')) > MAX_TEXT_BYTES:
                    raise PublicSourceSecurityError('Public source PDF text byte limit exceeded')
                excerpts = extract_financials(text)
            else:
                excerpts = {'results': extract_newsroom(body.decode('utf-8', errors='strict'))}
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise PublicSourceError('Public source timeout; no retries') from exc
        except httpx.HTTPError as exc:
            raise PublicSourceError('Public source network failure; no retries') from exc
        except (OSError, UnicodeError) as exc:
            raise PublicSourceError('Public source decoding or parser failure') from exc
        lineage = {'retrieved_at': datetime.now(timezone.utc).isoformat(),
                   'source_sha256': hashlib.sha256(body).hexdigest(), 'source_bytes': len(body),
                   'retrieval_status': 'fetched'}
        return {entry['section_id']: {**{k: v for k, v in entry.items() if k != 'keywords'},
                                     **lineage, 'excerpt': excerpts[entry['section_id']]}
                for entry in entries}
