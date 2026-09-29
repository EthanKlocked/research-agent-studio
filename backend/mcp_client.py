"""One bounded, local stdio MCP session per research node."""
import asyncio
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import ValidationError
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp_server.tool_schemas import SearchArguments, SectionArguments
from mcp_server.dataset import DATA, SECTION_IDS, get_dataset_scope
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_server.public_sources import UnavailableSource, public_sources_enabled

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"search_documents", "get_section"}
def document_environment(*, enabled=None):
    """Forward an explicit boolean and resolved parser path, never model secrets."""
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    if public_sources_enabled() if enabled is None else enabled:
        env["RESEARCH_PUBLIC_SOURCES"] = "1"
        executable = shutil.which(os.environ.get("RESEARCH_PDFTOTEXT", "").strip() or "pdftotext")
        if executable:
            env["RESEARCH_PDFTOTEXT"] = str(Path(executable).resolve())
    return env

class ToolFailure(Exception):
    pass

class RecoverableToolError(ToolFailure):
    """Only locally verified argument/identifier mistakes, never remote errors."""

class DocumentClient:
    def __init__(self, session, timeout=10, max_tool_calls=12, max_tool_corrections=2):
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

    async def load_tools(self):
        """Discover server contracts under one deadline; fail closed before binding."""
        tools = await asyncio.wait_for(load_mcp_tools(self.session), self.timeout)
        names = [tool.name for tool in tools]
        if len(names) != len(ALLOWED) or set(names) != ALLOWED:
            raise ToolFailure("Invalid document tool inventory")
        return tools

    async def list_tools(self):
        return [tool.name for tool in await self.load_tools()]

    async def call(self, name, arguments):
        async with self._lock:
            return await self._call(name, arguments)

    async def _call(self, name, arguments):
        if name not in ALLOWED or self.calls >= self.max_tool_calls:
            raise ToolFailure("Tool permission or call budget exceeded")
        self.calls += 1
        args = {}
        try:
            schema = SearchArguments if name == "search_documents" else SectionArguments
            args = schema.model_validate(arguments).model_dump()
            unknown = name == "get_section" and (args["document_id"], args["section_id"]) not in SECTION_IDS
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
            if isinstance(value, dict) and value.get("retrieval_status") == "unavailable":
                unavailable = UnavailableSource.model_validate(value)
                if name != "get_section" or (unavailable.document_id, unavailable.section_id) != (args["document_id"], args["section_id"]):
                    raise ToolFailure("Invalid unavailable source result")
                return unavailable.model_dump()
            if name == "get_section":
                self.unresolved_error = False
            return value
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise ToolFailure("Document tool failed") from exc

@asynccontextmanager
async def document_session(timeout=10, max_tool_calls=12, max_tool_corrections=2, *, enabled=None):
    # No model credentials, global config, or traces are forwarded to the child.
    env = document_environment(enabled=enabled)
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=env)
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout)
                yield DocumentClient(session, timeout=timeout, max_tool_calls=max_tool_calls, max_tool_corrections=max_tool_corrections)
