"""Read-only allowlisted data tools. No arbitrary paths, URLs, shell or SQL."""
import asyncio
from mcp_server.dataset import DATA, SECTIONS
from mcp_server.tool_schemas import SearchQuery, SearchLimit, SectionIdentifier, DEFAULT_SEARCH_LIMIT
from mcp.server.fastmcp import FastMCP
from mcp_server.public_sources import CATALOG, PUBLIC_SECTION_IDS, PublicSourceStore, PublicSourceError, PublicSourceSecurityError, UnavailableSource, public_sources_enabled

PUBLIC_STORE = PublicSourceStore(enabled=public_sources_enabled())
mcp = FastMCP("research-documents", log_level="CRITICAL")

def public(section):
    return {k: v for k, v in section.items() if k != "keywords"}

@mcp.tool()
def search_documents(query: SearchQuery, limit: SearchLimit = DEFAULT_SEARCH_LIMIT) -> list[dict]:
    """Search historical summaries and opted-in exact Apple public-source catalog. Metadata is not evidence; call get_section to fetch. No web crawling."""
    tokens = query.casefold().split()
    sections = (list(CATALOG) if PUBLIC_STORE.enabled else []) + list(SECTIONS.values())
    scored = [(sum(t in (s["title"] + s.get("excerpt", "") + s["keywords"]).casefold() for t in tokens), s) for s in sections]
    return [{k:v for k,v in public(s).items() if k != "excerpt"} for score, s in sorted(scored, key=lambda pair: -pair[0]) if score][:limit]

def get_section(document_id: SectionIdentifier, section_id: SectionIdentifier) -> dict:
    """Read an allowlisted document section by exact identifiers."""
    if (document_id, section_id) in PUBLIC_SECTION_IDS:
        try:
            return PUBLIC_STORE.get_section(document_id, section_id)
        except PublicSourceSecurityError:
            raise
        except PublicSourceError:
            if not PUBLIC_STORE.enabled:
                raise
            return UnavailableSource(document_id=document_id, section_id=section_id).model_dump()
    section = SECTIONS.get((document_id, section_id))
    if section is None:
        raise ValueError("Unknown document or section ID")
    return public(section)

@mcp.tool(name="get_section")
async def get_section_tool(document_id: SectionIdentifier, section_id: SectionIdentifier) -> dict:
    """Fetch one exact allowlisted section; optional unavailable results are not evidence."""
    return await asyncio.to_thread(get_section, document_id, section_id)

if __name__ == "__main__":
    mcp.run(transport="stdio")
