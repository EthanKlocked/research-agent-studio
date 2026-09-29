"""Fixed diagnostics only; never expose exception text or provider payloads."""
from pydantic import ValidationError
from httpx import TimeoutException
from openai import APITimeoutError
from backend.mcp_client import ToolFailure

class OutputLimit(ValueError):
    pass

class OutputValidation(ValueError):
    pass

class RetrievalIncomplete(ToolFailure):
    pass


def exception_chain(exc):
    """Cycle-safe traversal, including structured-concurrency siblings and causes."""
    pending, seen = [exc], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append(cause)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))


def error_category(exc):
    categories = set()
    for current in exception_chain(exc):
        if isinstance(current, (TimeoutError, TimeoutException, APITimeoutError)):
            return "timeout"
        if isinstance(current, OutputLimit):
            categories.add("output_limit")
        elif isinstance(current, (OutputValidation, ValidationError)):
            categories.add("validation")
        elif isinstance(current, RetrievalIncomplete):
            categories.add("retrieval_incomplete")
        elif isinstance(current, ToolFailure):
            categories.add("tool")
    return next((c for c in ("output_limit", "validation", "retrieval_incomplete", "tool") if c in categories), "provider_or_execution")


def safe_exception_classes(exc):
    """Bounded diagnostics; only exact trusted types expose their class names."""
    allowed = {ExceptionGroup, BaseExceptionGroup, TimeoutError, TimeoutException,
               APITimeoutError, ToolFailure, OutputLimit, OutputValidation,
               RetrievalIncomplete, ValidationError, ValueError, RuntimeError,
               ConnectionError, Exception}
    pending, seen, names = [(exc, 0)], set(), []
    while pending and len(names) < 16:
        current, depth = pending.pop()
        if id(current) in seen or depth > 8:
            continue
        seen.add(id(current))
        names.append(type(current).__name__ if type(current) in allowed else "Exception")
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append((cause, depth + 1))
        if isinstance(current, BaseExceptionGroup):
            pending.extend((e, depth + 1) for e in reversed(current.exceptions[:16]))
    return ">".join(names)
