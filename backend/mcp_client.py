"""One bounded, local stdio MCP session per research node."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"search_documents", "get_section"}

class ToolFailure(Exception):
    pass

class DocumentClient:
    def __init__(self, session, timeout=10):
        self.session = session
        self.timeout = timeout
        self.calls = 0

    async def list_tools(self):
        result = await asyncio.wait_for(self.session.list_tools(), self.timeout)
        return [tool.name for tool in result.tools]

    async def call(self, name, arguments):
        if name not in ALLOWED or self.calls >= 12:
            raise ToolFailure("Tool permission or call budget exceeded")
        self.calls += 1
        try:
            result = await asyncio.wait_for(self.session.call_tool(name, arguments), self.timeout)
            if result.isError:
                raise ToolFailure("Document tool failed")
            if result.structuredContent is not None:
                value = result.structuredContent
                return value.get("result", value)
            texts = [c.text for c in result.content if c.type == "text"]
            if len(texts) == 1:
                return json.loads(texts[0])
            return [json.loads(t) for t in texts]
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise ToolFailure("Document tool failed") from exc

@asynccontextmanager
async def document_session():
    # No model credentials, global config, or traces are forwarded to the child.
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=env)
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await asyncio.wait_for(session.initialize(), 10)
                yield DocumentClient(session)
