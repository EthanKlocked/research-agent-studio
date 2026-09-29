"""Real LangGraph outer workflow. Each node returns validated partial state."""
from copy import deepcopy
import json
from pathlib import Path
from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from langsmith import tracing_context
from backend.agents import RoleRunner
from backend.mcp_client import document_session, ToolFailure
from backend.schemas import ROLE_SCHEMAS, validate_citations

SECTION_IDS = frozenset(
    (s["document_id"], s["section_id"])
    for s in json.loads((Path(__file__).resolve().parents[1] / "data/apple_fy2024.json").read_text())["sections"]
)


def tool_input_summary(name, arguments):
    """Public metadata only: never echo arbitrary model-authored arguments."""
    if name == "search_documents":
        query, limit = arguments.get("query"), arguments.get("limit")
        length = len(query) if isinstance(query, str) else 0
        cap = str(limit) if type(limit) is int and 1 <= limit <= 5 else "유효하지 않음"
        return f"검색어 {length}자 · 결과 상한 {cap}건"[:160]
    if name == "get_section":
        doc, section = arguments.get("document_id"), arguments.get("section_id")
        if isinstance(doc, str) and isinstance(section, str) and (doc, section) in SECTION_IDS:
            return f"자료 구간 조회 · {doc} / {section}"[:160]
        return "자료 구간 조회 · 허용되지 않은 식별자"
    return "허용되지 않은 도구"


class WorkflowState(TypedDict):
    run_id: str
    question: str
    mode: str
    status: str
    stage: str | None
    iteration: int
    started_at: str
    finished_at: str | None
    last_seq: int
    interpreted_request: str
    plan: list[str]
    evidence: list[dict]
    report: dict | None
    revisions: list[dict]
    evaluation: dict | None
    feedback: list[str]
    errors: list[str]

def build_graph(settings, mode, scenario, publish):
    runner = RoleRunner(settings, mode, scenario)

    async def research(state):
        evidence = {e["id"]: e for e in state["evidence"]}
        failures = []
        async with document_session() as client:
            async def invoke_tool(name, args):
                await publish("tool_start", state, {"tool":name, "input_summary":tool_input_summary(name, args)})
                try:
                    result = await client.call(name, args)
                except Exception as exc:
                    failures.append(exc)
                    raise
                if name == "get_section":
                    evidence[result["id"]] = result
                await publish("tool_complete", state, {"tool":name, "count":len(result) if isinstance(result, list) else 1})
                return result
            @tool
            async def search_documents(query: str, limit: int = 5) -> list[dict]:
                """Search the bundled historical summaries by keyword; query <=300 chars, limit 1..5."""
                return await invoke_tool("search_documents", {"query":query, "limit":limit})
            @tool
            async def get_section(document_id: str, section_id: str) -> dict:
                """Read one allowlisted document section, using IDs from search results."""
                return await invoke_tool("get_section", {"document_id":document_id, "section_id":section_id})
            output = await runner.invoke("Researcher", state, [search_documents, get_section])
            if failures:
                raise ToolFailure("Document tool failed")
            if client.calls == 0:
                raise ToolFailure("Researcher did not call a document tool")
            ROLE_SCHEMAS["Researcher"].model_validate(output)
        return {"evidence":list(evidence.values()), **({"status":"empty"} if not evidence else {})}

    def node(role):
        async def execute(state):
            current = deepcopy(state)
            current.update(stage=role, status="running")
            if role == "Planner":
                current["iteration"] += 1
            await publish("node_start", current, {})
            if role == "Researcher":
                updates = await research(current)
            else:
                raw = await runner.invoke(role, current, [])
                value = ROLE_SCHEMAS[role].model_validate(raw).model_dump()
                if role == "Reporter":
                    validate_citations(value, current["evidence"])
                    updates = {"report":value}
                elif role == "Evaluator":
                    updates = {"evaluation":value, "feedback":value["issues"] + value["follow_up"]}
                    previous_ids = set(current["revisions"][-1]["evidence_ids"]) if current["revisions"] else set()
                    ids = [e["id"] for e in current["evidence"]]
                    if value["decision"] == "pass":
                        updates["status"] = "success"
                    elif current["iteration"] >= settings.max_iterations:
                        updates["status"] = "limit_reached"
                        report = deepcopy(current["report"])
                        report["limitations"] = report["limitations"][:7] + ["반복 한도에 도달하여 평가 이슈가 해결되지 않았습니다."]
                        updates["report"] = report
                    updates["revisions"] = current["revisions"] + [{"iteration":current["iteration"], "report":deepcopy(updates.get("report", current["report"])), "evidence_ids":ids, "added_evidence_ids":[i for i in ids if i not in previous_ids], "evaluation":value}]
                else:
                    updates = value
            current.update(updates)
            await publish("node_complete", current, {"changed_fields":list(updates)})
            if role == "Evaluator":
                await publish("evaluation", current, {"decision":current["evaluation"]["decision"]})
                reason = "revise_to_planner" if current["status"] == "running" else current["status"]
                await publish("branch", current, {"reason":reason})
            return current
        return execute

    builder = StateGraph(WorkflowState)
    for role in ("Listener", "Planner", "Researcher", "Reporter", "Evaluator"):
        builder.add_node(role, node(role))
    builder.add_edge(START, "Listener")
    builder.add_edge("Listener", "Planner")
    builder.add_edge("Planner", "Researcher")
    builder.add_conditional_edges("Researcher", lambda s: END if s["status"] == "empty" else "Reporter")
    builder.add_edge("Reporter", "Evaluator")
    builder.add_conditional_edges("Evaluator", lambda s: "Planner" if s["status"] == "running" else END)
    return builder.compile()
