"""Bounded local MCP sessions; general research keeps one registry per run."""
from copy import deepcopy
import asyncio
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import ValidationError
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp_server.tool_schemas import SearchArguments, SectionArguments, PageArguments, ARGUMENT_SCHEMAS
from mcp_server.general_web import _public_url, _date, MAX_TEXT_CHARS, MAX_RESPONSE_BYTES
from mcp_server.dataset import DATA, SECTION_IDS, get_dataset_scope
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_server.public_sources import UnavailableSource, public_sources_enabled

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"search_documents", "get_section"}
GENERAL_ALLOWED = ALLOWED | {"web_search", "read_page"}
def planner_tool_metadata(tools):
    """Bounded projection of discovered contracts, not a fabricated inventory.

    Descriptions are untrusted prose for the Planner only. Schema values that
    could contain arbitrary source data (examples/defaults/$refs) are omitted.
    The executable Researcher contracts remain the unmodified MCP schemas.
    """
    result = []
    for tool in sorted(tools, key=lambda t: t.name):
        if tool.name not in ARGUMENT_SCHEMAS:
            raise ToolFailure("Invalid document tool inventory")
        fields = set(ARGUMENT_SCHEMAS[tool.name].model_fields)
        raw = tool.args_schema
        if not isinstance(raw, dict):
            raise ToolFailure("Invalid document tool schema")
        def project(schema):
            output = {}
            if not isinstance(schema, dict):
                return output
            if schema.get("type") in ("object", "string", "integer", "number", "boolean", "array", "null"):
                output["type"] = schema["type"]
            for key in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                value = schema.get(key)
                if type(value) in (int, float) and 0 <= value <= 1_000_000:
                    output[key] = value
            if type(schema.get("additionalProperties")) is bool:
                output["additionalProperties"] = schema["additionalProperties"]
            return output
        schema = project(raw)
        if isinstance(raw.get("properties"), dict):
            schema["properties"] = {k: project(v) for k, v in raw["properties"].items() if k in fields}
        if isinstance(raw.get("required"), list):
            schema["required"] = [k for k in raw["required"] if isinstance(k, str) and k in fields][:len(fields)]
        description = " ".join("".join(c for c in (tool.description or "")[:2400] if c.isprintable() or c in "\n\t").split())[:600]
        result.append({"name": tool.name, "description": description, "input_schema": schema})
    return result


def document_environment(*, enabled=None, search_provider="", exa_api_key=""):
    """Forward an explicit boolean and resolved parser path, never model secrets."""
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    if public_sources_enabled() if enabled is None else enabled:
        env["RESEARCH_PUBLIC_SOURCES"] = "1"
        executable = shutil.which(os.environ.get("RESEARCH_PDFTOTEXT", "").strip() or "pdftotext")
        if executable:
            env["RESEARCH_PDFTOTEXT"] = str(Path(executable).resolve())
    if search_provider == "exa" and exa_api_key.strip():
        env.update(SEARCH_PROVIDER="exa", EXA_API_KEY=exa_api_key.strip())
    return env

class ToolFailure(Exception):
    pass

class RecoverableToolError(ToolFailure):
    """Only locally verified argument/identifier mistakes, never remote errors."""

class DocumentClient:
    def __init__(self, session, timeout=10, max_tool_calls=12, max_tool_corrections=2, *, general_web=False):
        self.allowed = GENERAL_ALLOWED if general_web else ALLOWED
        self._sources = {}
        self._evidence = {}
        self.session = session
        self.timeout = timeout
        self.max_tool_calls = max_tool_calls
        self.max_tool_corrections = max_tool_corrections
        self.calls = 0
        self.corrections = 0
        self.unresolved_error = False
        # LangChain may dispatch a batch concurrently; keep budget and recovery
        # ordering deterministic, and never let an older retrieval clear an error.
        self._lock = asyncio.Lock()

    def reset_budget(self):
        # Per-researcher attempt budgets; retain source identities across revisions.
        self.calls = self.corrections = 0
        self.unresolved_error = False

    def validate_evidence(self, value):
        return isinstance(value, dict) and self._evidence.get(value.get("id")) == value

    def _admit_general(self, name, args, value):
        """Bind contents to metadata actually returned by this exact MCP session."""
        def metadata(item):
            if not isinstance(item, dict) or not _public_url(item.get("url")):
                raise ToolFailure("Invalid source result")
            if type(item.get("title")) is not str or not 1 <= len(item["title"]) <= 500:
                raise ToolFailure("Invalid source result")
            _date(item.get("published_at"))
        if name == "web_search":
            if not isinstance(value, list) or len(value) > args["limit"]:
                raise ToolFailure("Invalid source result")
            admitted = {}
            for item in value:
                metadata(item)
                if set(item) != {"source_id", "url", "title", "published_at", "retrieval_status"} or item["retrieval_status"] != "metadata_only":
                    raise ToolFailure("Invalid source result")
                sid = PageArguments.model_validate({"source_id":item["source_id"]}).source_id
                if sid in self._sources and self._sources[sid] != item:
                    raise ToolFailure("Source identity changed")
                admitted[sid] = deepcopy(item)
            if len(self._sources.keys() | admitted.keys()) > 30:
                raise ToolFailure("Source registry bound exceeded")
            self._sources.update(admitted)
        else:
            metadata(value)
            sid = args["source_id"]
            if (set(value) != {"url", "title", "published_at", "id", "document_id", "section_id", "as_of", "excerpt", "provenance"}
                    or value["document_id"] != sid or value["id"] != sid + ":page"
                    or value["section_id"] != "page" or value["provenance"] != "exa_contents"
                    or value["url"] != self._sources[sid]["url"] or value["as_of"] is not None
                    or type(value["excerpt"]) is not str or not value["excerpt"].strip()
                    or len(value["excerpt"]) > MAX_TEXT_CHARS):
                raise ToolFailure("Invalid source evidence")
            if value["id"] not in self._evidence and sum(e.get("provenance") == "exa_contents" for e in self._evidence.values()) >= 8:
                raise ToolFailure("Evidence registry bound exceeded")
            if value["id"] in self._evidence and self._evidence[value["id"]] != value:
                raise ToolFailure("Source evidence changed")

    async def load_tools(self):
        """Discover server contracts under one deadline; fail closed before binding."""
        tools = await asyncio.wait_for(load_mcp_tools(self.session), self.timeout)
        names = [tool.name for tool in tools]
        if len(names) != len(self.allowed) or set(names) != self.allowed:
            raise ToolFailure("Invalid document tool inventory")
        return tools

    async def list_tools(self):
        return [tool.name for tool in await self.load_tools()]

    async def call(self, name, arguments):
        async with self._lock:
            return await self._call(name, arguments)

    async def _call(self, name, arguments):
        if name not in self.allowed or self.calls >= self.max_tool_calls:
            raise ToolFailure("Tool permission or call budget exceeded")
        self.calls += 1
        args = {}
        try:
            schema = ARGUMENT_SCHEMAS[name]
            args = schema.model_validate(arguments).model_dump()
            unknown = (name == "get_section" and (args["document_id"], args["section_id"]) not in SECTION_IDS) or (name == "read_page" and args["source_id"] not in self._sources)
        except ValidationError:
            unknown = True
        if unknown:
            self.unresolved_error = True
            self.corrections += 1
            if self.corrections > self.max_tool_corrections:
                raise ToolFailure("Tool correction budget exceeded")
            raise RecoverableToolError("Invalid document tool input")
        try:
            result = await asyncio.wait_for(self.session.call_tool(name, args), self.timeout)
            if result.isError:
                raise ToolFailure("Document tool failed")
            if result.structuredContent is not None:
                value = result.structuredContent
                value = value.get("result", value)
            else:
                texts = [c.text for c in result.content if c.type == "text"]
                value = json.loads(texts[0]) if len(texts) == 1 else [json.loads(t) for t in texts]
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ToolFailure("Tool result bound exceeded")
            if name in ("web_search", "read_page"):
                self._admit_general(name, args, value)
            if isinstance(value, dict) and value.get("retrieval_status") == "unavailable":
                unavailable = UnavailableSource.model_validate(value)
                if name != "get_section" or (unavailable.document_id, unavailable.section_id) != (args["document_id"], args["section_id"]):
                    raise ToolFailure("Invalid unavailable source result")
                return unavailable.model_dump()
            if name in ("get_section", "read_page"):
                self.unresolved_error = False
                self._evidence[value["id"]] = deepcopy(value)
            return value
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise ToolFailure("Document tool failed") from exc

@asynccontextmanager
async def document_session(timeout=10, max_tool_calls=12, max_tool_corrections=2, *, enabled=None, search_provider="", exa_api_key=""):
    # No model credentials, global config, or traces are forwarded to the child.
    env = document_environment(enabled=enabled, search_provider=search_provider, exa_api_key=exa_api_key)
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=env)
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout)
                yield DocumentClient(session, timeout=timeout, max_tool_calls=max_tool_calls, max_tool_corrections=max_tool_corrections, general_web=env.get("SEARCH_PROVIDER") == "exa")
