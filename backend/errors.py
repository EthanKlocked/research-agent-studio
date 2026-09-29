"""Fixed diagnostics only; never expose exception text or provider payloads."""
from pydantic import ValidationError
from backend.mcp_client import ToolFailure

class OutputLimit(ValueError):
    pass

class OutputValidation(ValueError):
    pass

class RetrievalIncomplete(ToolFailure):
    pass


def error_category(exc):
    if isinstance(exc, BaseExceptionGroup):
        categories = [error_category(e) for e in exc.exceptions]
        return next((c for c in categories if c != "provider_or_execution"), categories[0])
    if isinstance(exc, OutputLimit):
        return "output_limit"
    if isinstance(exc, (OutputValidation, ValidationError)):
        return "validation"
    if isinstance(exc, RetrievalIncomplete):
        return "retrieval_incomplete"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ToolFailure):
        return "tool"
    return "provider_or_execution"
