"""Operator-only configuration; never serialized to the browser."""
import os
import math
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Explicitly disable inherited tracing; no credential discovery or global dotenv.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

TIMEOUT_ENV = {"model_timeout": "LLM_REQUEST_TIMEOUT", "listener_timeout": "LISTENER_TIMEOUT", "planner_timeout": "PLANNER_TIMEOUT", "researcher_timeout": "RESEARCHER_TIMEOUT", "reporter_timeout": "REPORTER_TIMEOUT", "evaluator_timeout": "EVALUATOR_TIMEOUT", "run_timeout": "RUN_TIMEOUT"}

@dataclass(frozen=True)
class Settings:
    provider: str = field(default="", repr=False)
    model: str = field(default="", repr=False)
    base_url: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    search_provider: str = field(default="", repr=False)
    exa_api_key: str = field(default="", repr=False)
    gateway_observation: bool = False
    token_prices: dict = field(default_factory=dict, repr=False)
    test_mode: bool = False
    max_iterations: int = 2
    max_concurrent: int = 2
    max_runs: int = 20
    max_events: int = 160
    max_tool_calls: int = 12
    max_tool_corrections: int = 2
    mcp_timeout: float = 10
    model_timeout: float = 60
    listener_timeout: float = 60
    planner_timeout: float = 60
    researcher_timeout: float = 180
    reporter_timeout: float = 120
    evaluator_timeout: float = 60
    run_timeout: float = 600
    max_output_tokens: int = 8192

    def role_timeout(self, role):
        return getattr(self, role.lower() + "_timeout")

    def __post_init__(self):
        price_error = "LLM_TOKEN_PRICES_JSON must map safe model labels to finite nonnegative input/output USD per million rates"
        if not isinstance(self.token_prices, dict):
            raise ValueError(price_error)
        for label, rates in self.token_prices.items():
            if label not in {"research-primary", "research-secondary", "configured-model"} or not isinstance(rates, dict) or set(rates) != {"input", "output"}:
                raise ValueError(price_error)
            if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rates.values()):
                raise ValueError(price_error)
        for field_name, env_name in TIMEOUT_ENV.items():
            value = getattr(self, field_name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 7200:
                raise ValueError(f"{env_name} must be finite seconds greater than 0 and at most 7200")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 65536:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be an integer from 1 to 65536")

    @property
    def general_web_enabled(self):
        return self.search_provider == "exa" and bool(self.exa_api_key.strip())

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
        try:
            tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "").strip() or "8192")
        except ValueError:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be an integer from 1 to 65536") from None
        try:
            prices = json.loads(os.getenv("LLM_TOKEN_PRICES_JSON", "").strip() or "{}")
        except ValueError:
            raise ValueError("LLM_TOKEN_PRICES_JSON must be valid JSON") from None
        timeouts = {}
        for field_name, env_name in TIMEOUT_ENV.items():
            raw = os.getenv(env_name, "").strip()
            if raw:
                try:
                    timeouts[field_name] = float(raw)
                except ValueError:
                    raise ValueError(f"{env_name} must be finite seconds greater than 0 and at most 7200") from None
        return cls(**timeouts, gateway_observation=os.getenv("LLM_GATEWAY_OBSERVATION", "0") == "1", token_prices=prices, search_provider=os.getenv("SEARCH_PROVIDER", "").strip(), exa_api_key=os.getenv("EXA_API_KEY", "").strip(), max_output_tokens=tokens, provider=os.getenv("LLM_PROVIDER", "").strip(), model=os.getenv("LLM_MODEL", "").strip(), base_url=os.getenv("LLM_BASE_URL", "").strip(), api_key=os.getenv("LLM_API_KEY", "").strip(), test_mode=os.getenv("RESEARCH_TEST_MODE", "0") == "1")
