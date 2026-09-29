"""Read-only allowlisted data tools. No arbitrary paths, URLs, shell or SQL."""
import json
from pathlib import Path
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

DATA = json.loads((Path(__file__).resolve().parents[1] / "data/apple_fy2024.json").read_text(encoding="utf-8"))
SECTIONS = {(s["document_id"], s["section_id"]): s for s in DATA["sections"]}
mcp = FastMCP("research-documents", log_level="CRITICAL")

def public(section):
    return {k: v for k, v in section.items() if k != "keywords"}

@mcp.tool()
def search_documents(query: Annotated[str, Field(min_length=1, max_length=300)], limit: Annotated[int, Field(ge=1, le=5)] = 5) -> list[dict]:
    """Search bundled historical summaries; return at most five metadata hits, not excerpts. Call get_section to retrieve evidence."""
    tokens = query.casefold().split()
    scored = [(sum(t in (s["title"] + s["excerpt"] + s["keywords"]).casefold() for t in tokens), s) for s in SECTIONS.values()]
    return [{k:v for k,v in public(s).items() if k != "excerpt"} for score, s in sorted(scored, key=lambda pair: -pair[0]) if score][:limit]

@mcp.tool()
def get_section(document_id: Annotated[str, Field(min_length=1, max_length=80)], section_id: Annotated[str, Field(min_length=1, max_length=80)]) -> dict:
    """Read an allowlisted document section by exact identifiers."""
    section = SECTIONS.get((document_id, section_id))
    if section is None:
        raise ValueError("Unknown document or section ID")
    return public(section)

if __name__ == "__main__":
    mcp.run(transport="stdio")
