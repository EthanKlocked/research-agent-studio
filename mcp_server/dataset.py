"""Bundled dataset and discoverable scope, loaded once per process as UTF-8."""
import json
from pathlib import Path
from mcp_server.public_sources import CATALOG, PUBLIC_SECTION_IDS, public_sources_enabled

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "data/apple_fy2024.json").read_text(encoding="utf-8"))
SECTIONS = {(s["document_id"], s["section_id"]): s for s in DATA["sections"]}
SECTION_IDS = frozenset(SECTIONS) | PUBLIC_SECTION_IDS
DATASET_SCOPE = {
    "name": DATA["name"], "as_of": DATA["as_of"], "scope": DATA["scope"],
    "period_note": "FY2024 Q4 is a completed historical quarter ending 2024-09-28. as_of is the reporting period end, not publication or knowledge cutoff. Use each document's published_at; these are reported results, not future estimates.",
    "available_documents": [{k:s[k] for k in ("document_id", "section_id", "title", "published_at")} for s in DATA["sections"]],
}

def general_dataset_scope(*, enabled=None):
    historical = get_dataset_scope(enabled=enabled)
    return {"name": "General public web research + historical document catalog",
            "as_of": None,
            "scope": "General topics through Exa search and extracted pages. Search metadata is not evidence. Coverage is not exhaustive; no guaranteed freshness or date range.",
            "period_note": "No global as-of date. published_at is nullable source publication metadata, not a verified fact date or knowledge cutoff; never infer a date when absent.",
            "general_web_enabled": True,
            "public_sources_enabled": historical["public_sources_enabled"],
            "available_documents": historical["available_documents"]}


def get_dataset_scope(*, enabled=None):
    """Resolve after dotenv loading; only enabled public metadata is discoverable."""
    enabled = public_sources_enabled() if enabled is None else enabled
    return {**DATASET_SCOPE, "public_sources_enabled": enabled,
            "scope": DATA["scope"] + (" Exact official Apple FY2024 Q4 documents may be fetched on demand; catalog metadata is not evidence." if enabled else ""),
            "available_documents": DATASET_SCOPE["available_documents"] +
            ([{k: s[k] for k in ("document_id", "section_id", "title", "published_at", "url", "retrieval_status")} for s in CATALOG] if enabled else [])}
