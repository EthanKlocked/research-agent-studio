"""Operator-only configuration; never serialized to the browser."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Explicitly disable inherited tracing; no credential discovery or global dotenv.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

@dataclass(frozen=True)
class Settings:
    provider: str = field(default="", repr=False)
    model: str = field(default="", repr=False)
    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    test_mode: bool = False
    max_iterations: int = 2
    max_concurrent: int = 2
    max_runs: int = 20
    max_events: int = 160
    max_tool_calls: int = 12
    max_tool_corrections: int = 2
    mcp_timeout: float = 10
    model_timeout: float = 30
    run_timeout: float = 120

    @property
    def configured(self):
        try:
            url = urlsplit(self.base_url)
            _ = url.port
        except ValueError:
            return False
        valid_url = url.scheme == "https" or (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1"))
        return bool(self.provider in ("openai", "openai-compatible") and self.model and self.api_key and valid_url and url.hostname and not url.username and not url.password and not url.query and not url.fragment)

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return cls(provider=os.getenv("LLM_PROVIDER", "").strip(), model=os.getenv("LLM_MODEL", "").strip(), base_url=os.getenv("LLM_BASE_URL", "").strip(), api_key=os.getenv("LLM_API_KEY", "").strip(), test_mode=os.getenv("RESEARCH_TEST_MODE", "0") == "1")
