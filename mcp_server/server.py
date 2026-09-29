"""Read-only allowlisted data tools. No arbitrary paths, URLs, shell or SQL."""
import asyncio
import os
import json
from mcp.types import CallToolResult, TextContent
from mcp_server.general_web import GeneralWebError
from mcp_server.dataset import DATA, SECTIONS
from mcp_server.tool_schemas import SearchQuery, SearchLimit, SectionIdentifier, SourceIdentifier, DEFAULT_SEARCH_LIMIT
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

def register_general_tools(server, store):
    """Register only on an explicitly configured, run-local server instance."""
    @server.resource("research://run/web-budget")
    def web_budget() -> str:
        return json.dumps(store.remaining_budget())

    def failure(exc):
        # Explicit typed envelope, never FastMCP exception prose.
        return CallToolResult(isError=True, content=[TextContent(type="text", text="General web retrieval failed")],
                              structuredContent={"web_failure": {"category": exc.category}})

    @server.tool(name="web_search", structured_output=False)
    async def web_search(query: SearchQuery, limit: SearchLimit = DEFAULT_SEARCH_LIMIT) -> list[dict]:
        """Search general public topics via Exa. Returns metadata and run-local source IDs, never evidence. Use read_page for contents. No fallback."""
        try:
            value = await store.web_search(query, limit)
            return CallToolResult(isError=False, content=[TextContent(type="text", text=json.dumps(value))], structuredContent={"result":value})
        except GeneralWebError as exc:
            return failure(exc)

    @server.tool(name="read_page", structured_output=False)
    async def read_page(source_id: SourceIdentifier) -> dict:
        """Retrieve extracted page evidence for an exact source_id from this run's web_search. URLs and unknown IDs are forbidden. Dates may be unknown."""
        try:
            value = await store.read_page(source_id)
        except GeneralWebError as exc:
            return failure(exc)
        if not store.validate_evidence(value):
            raise ValueError("Invalid retrieved evidence")
        return CallToolResult(isError=False, content=[TextContent(type="text", text=json.dumps(value))], structuredContent=value)


async def _main():
    from mcp_server.general_web import GeneralWebStore
    store = None
    try:
        if os.environ.get("SEARCH_PROVIDER", "").strip() == "exa" and os.environ.get("EXA_API_KEY", "").strip():
            store = GeneralWebStore(api_key=os.environ["EXA_API_KEY"])
            register_general_tools(mcp, store)
        await mcp.run_stdio_async()
    finally:
        if store is not None:
            await store.close()



def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
