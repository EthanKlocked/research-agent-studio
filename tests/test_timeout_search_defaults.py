"""Offline regressions: no operator dotenv, provider calls, or live server."""
import pytest
from pydantic import ValidationError

from backend.config import Settings, TIMEOUT_ENV
from backend.workflow import tool_input_summary
from mcp_server.tool_schemas import ARGUMENT_SCHEMAS, DEFAULT_SEARCH_LIMIT


DEFAULTS = dict(model_timeout=60, listener_timeout=60, planner_timeout=60,
                researcher_timeout=180, reporter_timeout=120, evaluator_timeout=60,
                run_timeout=600)


def test_direct_timeout_defaults_allow_reporter_one_repair():
    settings = Settings()
    assert {key: getattr(settings, key) for key in DEFAULTS} == DEFAULTS
    assert settings.role_timeout('Reporter') == 2 * settings.model_timeout


@pytest.mark.parametrize('raw', [None, '', ' \t\n'])
def test_missing_or_blank_timeout_env_uses_defaults(monkeypatch, raw):
    monkeypatch.setattr('backend.config.load_dotenv', lambda *a, **kw: None)
    for name in TIMEOUT_ENV.values():
        if raw is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, raw)
    settings = Settings.from_env()
    assert {key: getattr(settings, key) for key in DEFAULTS} == DEFAULTS


@pytest.mark.parametrize('field', list(TIMEOUT_ENV))
@pytest.mark.parametrize('raw', ['0.5', '7200'])
def test_timeout_env_overrides_remain_independent(monkeypatch, field, raw):
    monkeypatch.setattr('backend.config.load_dotenv', lambda *a, **kw: None)
    for name in TIMEOUT_ENV.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(TIMEOUT_ENV[field], raw)
    settings = Settings.from_env()
    expected = {**DEFAULTS, field: float(raw)}
    assert {key: getattr(settings, key) for key in DEFAULTS} == expected


@pytest.mark.parametrize('field', list(TIMEOUT_ENV))
@pytest.mark.parametrize('raw', ['0', '-1', 'nan', 'inf', '7200.1', 'not-seconds'])
def test_request_and_role_env_bounds(monkeypatch, field, raw):
    monkeypatch.setattr('backend.config.load_dotenv', lambda *a, **kw: None)
    for name in TIMEOUT_ENV.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(TIMEOUT_ENV[field], raw)
    with pytest.raises(ValueError, match=TIMEOUT_ENV[field]):
        Settings.from_env()


@pytest.mark.parametrize('tool', ['web_search', 'search_documents'])
def test_omitted_search_limit_matches_shared_schema(tool):
    args = {'query': 'private query'}
    validated = ARGUMENT_SCHEMAS[tool].model_validate(args)
    assert validated.limit == DEFAULT_SEARCH_LIMIT
    assert tool_input_summary(tool, args) == f'검색어 13자 · 결과 상한 {validated.limit}건'
    assert args == {'query': 'private query'}


@pytest.mark.parametrize('tool', ['web_search', 'search_documents'])
@pytest.mark.parametrize('limit', [None, True, False, '5', '', 'secret', 1.0, 0, 6, [], {}])
def test_explicit_invalid_search_limits_are_not_defaulted_or_coerced(tool, limit):
    args = {'query': 'private query', 'limit': limit}
    with pytest.raises(ValidationError):
        ARGUMENT_SCHEMAS[tool].model_validate(args)
    assert tool_input_summary(tool, args) == '검색어 13자 · 결과 상한 유효하지 않음건'


@pytest.mark.parametrize('tool', ['web_search', 'search_documents'])
@pytest.mark.parametrize('limit', [1, 3, 5])
def test_explicit_valid_search_limit_is_preserved(tool, limit):
    assert tool_input_summary(tool, {'query': 'private query', 'limit': limit}) == f'검색어 13자 · 결과 상한 {limit}건'
