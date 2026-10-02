"""Fixed diagnostics only; never expose exception text or provider payloads."""
from pydantic import ValidationError
from httpx import TimeoutException
from openai import APITimeoutError
from backend.mcp_client import ToolFailure, WebToolFailure
from mcp_server.general_web import WEB_FAILURE_CATEGORIES

class OutputLimit(ValueError):
    pass

class OutputValidation(ValueError):
    pass

class RetrievalIncomplete(ToolFailure):
    pass


def web_failure_reason(category):
    return {
        "budget": "실행별 웹 조회 예산을 소진했습니다. 기존 근거만 사용할 수 있으며 조사가 불완전할 수 있습니다.",
        "quota": "검색 제공자의 할당량 또는 요청 제한에 도달했습니다. 운영자가 잔액과 제한을 확인해야 합니다.",
        "auth": "검색 제공자 인증에 실패했습니다. 운영자가 로컬 설정을 확인해야 합니다.",
        "timeout": "웹 자료 조회 시간이 초과되었습니다.",
        "security": "웹 자료가 허용된 보안 경계를 충족하지 않습니다.",
        "oversize": "웹 자료 크기가 허용된 한도를 초과했습니다.",
        "invalid_input": "웹 조회 입력이 허용된 형식을 충족하지 않습니다.",
    }.get(category, "웹 자료를 조회하지 못했습니다. 검색 결과 없음과는 다릅니다.")


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


def safe_web_category(exc):
    for current in exception_chain(exc):
        if isinstance(current, WebToolFailure):
            category = current.web_category
            if type(category) is str and category in WEB_FAILURE_CATEGORIES:
                return category
    return "none"


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
