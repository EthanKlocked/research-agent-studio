"""One bounded, local stdio MCP session per research node."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"search_documents", "get_section"}
SECTION_IDS = frozenset(
    (s["document_id"], s["section_id"])
    for s in json.loads((ROOT / "data/apple_fy2024.json").read_text())["sections"]
)

class ToolFailure(Exception):
    pass

class RecoverableToolError(ToolFailure):
    """Only locally verified argument/identifier mistakes, never remote errors."""

class ToolArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

class SearchArguments(ToolArguments):
    query: Annotated[str, Field(min_length=1, max_length=300)]
    limit: Annotated[int, Field(ge=1, le=5)] = 5

class SectionArguments(ToolArguments):
    document_id: Annotated[str, Field(min_length=1, max_length=80)]
    section_id: Annotated[str, Field(min_length=1, max_length=80)]

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

    async def list_tools(self):
        result = await asyncio.wait_for(self.session.list_tools(), self.timeout)
        return [tool.name for tool in result.tools]

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
            if name == "get_section":
                self.unresolved_error = False
            return value
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise ToolFailure("Document tool failed") from exc

@asynccontextmanager
async def document_session(timeout=10, max_tool_calls=12, max_tool_corrections=2):
    # No model credentials, global config, or traces are forwarded to the child.
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=env)
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), timeout)
                yield DocumentClient(session, timeout=timeout, max_tool_calls=max_tool_calls, max_tool_corrections=max_tool_corrections)
