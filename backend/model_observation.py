"""Allowlisted per-invocation metrics, never prompts, URLs, keys or errors."""
import json
import logging
import re
from time import monotonic

LOGGER = logging.getLogger("research.model")
LOGGER.setLevel(logging.INFO)
# Uvicorn need not configure a root handler; keep these safe records visible.
if not LOGGER.handlers:
    LOGGER.addHandler(logging.StreamHandler())


def identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{32,36}", value) else None


def record_model_call(*, run_id, role, call_id, model, started, status, response=None):
    metadata = {}
    if response is not None and response.result:
        metadata = response.result[-1].response_metadata
    usage = metadata.get("token_usage") or {}
    # Some proxies synthesize zero usage when upstream omits it. Do not call that measured zero.
    def count(key):
        value = usage.get(key)
        return value if type(value) is int and value >= 0 else None
    total = count("total_tokens")
    known = total is not None and total > 0
    headers = metadata.get("headers") or {}
    deployment = headers.get("x-litellm-model-id", "")
    deployment = deployment if isinstance(deployment, str) and re.fullmatch(r"[a-f0-9]{64}", deployment) else None
    record = {
        "run_id": identifier(run_id), "role": role, "model_call_id": call_id,
        "model": model if model in {"research-primary", "research-secondary"} else "configured-model",
        "gateway_call_id": identifier(headers.get("x-litellm-call-id")),
        "gateway_model_id": deployment,
        "status": status, "latency_ms": round((monotonic() - started) * 1000, 2),
        "input_tokens": count("prompt_tokens") if known else None,
        "output_tokens": count("completion_tokens") if known else None,
        "total_tokens": total if known else None,
        "usage_source": "response_reported" if known else "unknown",
        "estimated_cost_usd": None, "billing_cost_usd": None,
    }
    LOGGER.info(json.dumps(record, ensure_ascii=True))
