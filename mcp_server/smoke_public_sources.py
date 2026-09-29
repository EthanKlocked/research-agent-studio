"""Optional live HTTP + real MCP smoke; no model call, key, or full-text output.

Run: RESEARCH_PUBLIC_SOURCES=1 .venv/bin/python -m mcp_server.smoke_public_sources
"""
import asyncio
import json

from backend.mcp_client import document_session
from mcp_server.public_sources import CATALOG, public_sources_enabled


async def run_smoke():
    if not public_sources_enabled():
        raise RuntimeError('Live source smoke requires RESEARCH_PUBLIC_SOURCES=1')
    async with document_session() as client:
        tools = await client.list_tools()
        assert set(tools) == {'search_documents', 'get_section'}
        hits = await client.call('search_documents', {'query': 'product revenue net income gross margin'})
        assert any(hit['document_id'] == CATALOG[0]['document_id'] for hit in hits)
        sections = []
        for entry in CATALOG:
            sections.append(await client.call('get_section', {
                'document_id': entry['document_id'], 'section_id': entry['section_id'],
            }))
        assert 'Net income: 14,736 | 22,956' in sections[0]['excerpt']
        assert 'Gross margin: 43,879 | 40,427' in sections[0]['excerpt']
        assert 'iPhone: 46,222 | 43,805' in sections[1]['excerpt']
        assert '$94.9 billion' in sections[2]['excerpt']
        again = await client.call('get_section', {
            'document_id': CATALOG[0]['document_id'], 'section_id': CATALOG[0]['section_id'],
        })
        assert again == sections[0]
        assert sections[0]['retrieved_at'] == sections[1]['retrieved_at']
        keys = ('id', 'url', 'published_at', 'as_of', 'retrieved_at', 'source_bytes',
                'source_sha256', 'source_locator', 'retrieval_status')
        return {'verification': 'live Apple HTTP through real MCP stdio; no LLM/provider call',
                'tools': tools, 'cache_reused': True,
                'observed_q4_usd_millions': {'net_income': 14736, 'gross_margin': 43879, 'iphone_revenue': 46222},
                'sections': [{key: section[key] for key in keys} for section in sections]}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(run_smoke()), indent=2))
