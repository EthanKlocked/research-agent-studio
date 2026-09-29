import json
from pathlib import Path

import pytest

from backend.config import Settings
from backend.manager import RunManager
from backend.schemas import RunRequest


@pytest.mark.parametrize("scenario", ["pass", "tool_error"])
async def test_tool_events_have_bounded_safe_input_summaries(scenario):
    manager = RunManager(Settings(test_mode=True))
    state = await manager.start(RunRequest(question="private-user-prompt", mode="test", scenario=scenario))
    await manager.tasks[state["run_id"]]
    events = [e for e in manager.runs[state["run_id"]].events if e["type"] == "tool_start"]
    assert events
    for event in events:
        summary = event["data"].get("input_summary")
        assert isinstance(summary, str) and 0 < len(summary) <= 160
        assert "private-user-prompt" not in summary
        if event["data"]["tool"] == "search_documents":
            assert summary == "검색어 21자 · 결과 상한 5건"
        elif scenario == "tool_error":
            assert summary == "자료 구간 조회 · 허용되지 않은 식별자"


def test_input_summaries_never_echo_untrusted_arguments():
    from backend.workflow import tool_input_summary
    secret = "credential-or-prompt-secret"
    summary = tool_input_summary("search_documents", {"query": secret, "limit": secret})
    assert secret not in summary and len(summary) <= 160
    assert secret not in tool_input_summary("get_section", {"document_id": secret, "section_id": secret})
    data = json.loads((Path(__file__).resolve().parents[1] / "data/apple_fy2024.json").read_text())
    section = data["sections"][0]
    summary = tool_input_summary("get_section", section)
    assert section["document_id"] in summary and section["section_id"] in summary
    assert len(summary) <= 160
