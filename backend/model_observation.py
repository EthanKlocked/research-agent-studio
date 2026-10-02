"""Allowlisted per-invocation metrics, never prompts, URLs, keys or errors."""
import json
import logging
import math
import re
from time import monotonic

LOGGER = logging.getLogger("research.model")
LOGGER.setLevel(logging.INFO)
# Uvicorn need not configure a root handler; keep these safe records visible.
if not LOGGER.handlers:
    LOGGER.addHandler(logging.StreamHandler())


def identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{32,36}", value) else None


# Explicit public IDs in the bundled proxy config; never derive IDs from secrets.
GATEWAY_DEPLOYMENTS = {"01" * 32: "research-primary", "02" * 32: "research-secondary"}


def record_model_call(*, run_id, role, call_id, model, started, status, response=None, settings=None):
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
    gateway = settings is not None and settings.gateway_observation
    served_by = GATEWAY_DEPLOYMENTS.get(deployment) if gateway else None
    fallback = served_by != model if served_by and model in GATEWAY_DEPLOYMENTS.values() else None
    model_name = headers.get("x-litellm-model-name")
    model_name = model_name if settings is not None and served_by and model_name == settings.gateway_model_names.get(served_by) else None
    def header_count(name):
        value = headers.get(name)
        return int(value) if gateway and isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value) else None
    attempted_fallbacks = header_count("x-litellm-attempted-fallbacks")
    remaining_requests = header_count("x-ratelimit-remaining-requests")
    # The explicit router count is independent of alias comparison and availability.
    if attempted_fallbacks is not None:
        fallback = attempted_fallbacks > 0
    input_tokens = count("prompt_tokens") if known else None
    output_tokens = count("completion_tokens") if known else None
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    if type(reasoning) is not int or reasoning < 0:
        reasoning = None
    residual = total - input_tokens - output_tokens if known and input_tokens is not None and output_tokens is not None else None
    # Reasoning may already be included in completion_tokens. Never add it again.
    # Positive residuals stay unknown unless explicitly priced by assumption.
    price_label = served_by if gateway else "configured-model"
    rates = settings.token_prices.get(price_label) if settings is not None else None
    estimate = subtotal = None
    assumption = None
    if rates is not None and residual is not None and residual >= 0:
        try:
            value = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
            subtotal = value if math.isfinite(value) else None
            if residual == 0:
                estimate = subtotal
            elif settings is not None and settings.residual_pricing == "output":
                value += residual * rates["output"] / 1_000_000
                estimate = value if math.isfinite(value) else None
                assumption = "residual_at_output_rate" if estimate is not None else None
        except OverflowError:
            estimate = None
    record = {
        "run_id": identifier(run_id), "role": role, "model_call_id": call_id,
        "model": model if model in {"research-primary", "research-secondary"} else "configured-model",
        "gateway_call_id": identifier(headers.get("x-litellm-call-id")),
        "gateway_model_id": deployment, "served_by": served_by, "fallback": fallback,
        "gateway_model_name": model_name, "attempted_fallbacks": attempted_fallbacks,
        "rate_limit_remaining_requests": remaining_requests,
        "status": status, "latency_ms": round((monotonic() - started) * 1000, 2),
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "reasoning_tokens": reasoning, "unexplained_token_residual": residual,
        "total_tokens": total if known else None,
        "usage_source": "response_reported" if known else "unknown",
        "estimated_cost_usd": estimate, "billing_cost_usd": None,
        "input_output_estimated_cost_usd": subtotal, "cost_assumption": assumption,
    }
    LOGGER.info(json.dumps(record, ensure_ascii=True))
    return record
