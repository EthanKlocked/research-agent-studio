"""Real LangGraph outer workflow. Each node returns validated partial state."""
from copy import deepcopy
from contextlib import asynccontextmanager
import asyncio
from uuid import uuid4
import json
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from backend.agents import RoleRunner
from backend.errors import RetrievalIncomplete, safe_web_category, web_failure_reason
from backend.mcp_client import (
    document_session, ToolFailure, RecoverableToolError, WebToolFailure,
    SECTION_IDS, planner_tool_metadata,
)
from backend.schemas import ROLE_SCHEMAS, validate_citations
from mcp_server.tool_schemas import ARGUMENT_SCHEMAS


def tool_input_summary(name, arguments):
    """Public metadata only: never echo arbitrary model-authored arguments."""
    if name in ("search_documents", "web_search"):
        query = arguments.get("query")
        limit = arguments.get("limit", ARGUMENT_SCHEMAS[name].model_fields["limit"].default)
        length = len(query) if isinstance(query, str) else 0
        cap = str(limit) if type(limit) is int and 1 <= limit <= 5 else "유효하지 않음"
        return f"검색어 {length}자 · 결과 상한 {cap}건"[:160]
    if name == "get_section":
        doc, section = arguments.get("document_id"), arguments.get("section_id")
        if isinstance(doc, str) and isinstance(section, str) and (doc, section) in SECTION_IDS:
            return f"자료 구간 조회 · {doc} / {section}"[:160]
        return "자료 구간 조회 · 허용되지 않은 식별자"
    if name == "read_page":
        return "검색으로 등록된 자료 본문 조회"
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
    unavailable_sources: list[dict]
    report: dict | None
    revisions: list[dict]
    evaluation: dict | None
    feedback: list[str]
    errors: list[str]
    partial_result: dict | None
    run_context: dict
    unsupported_reason: str | None
    web_budget_exhausted: list[str]

def build_graph(settings, mode, scenario, publish, *, persistent_client=None, entry="Listener", listener_only=False):
    runner = RoleRunner(settings, mode, scenario)
    runner.publish = publish

    async def discover(state, client, purpose):
        await publish("discovery_start", state, {"purpose": purpose})
        tools = await client.load_tools()
        metadata = planner_tool_metadata(tools)
        await publish("discovery_complete", state, {"purpose": purpose, "tool_count": len(tools)})
        return tools, metadata

    @asynccontextmanager
    async def research_session():
        if persistent_client is not None:
            persistent_client.reset_budget()
            yield persistent_client
        else:
            async with document_session(timeout=settings.mcp_timeout, max_tool_calls=settings.max_tool_calls, max_tool_corrections=settings.max_tool_corrections, enabled=False if mode == "test" else None) as client:
                yield client

    async def planner_inventory(state):
        if persistent_client is not None:
            _, runner.tool_inventory = await discover(state, persistent_client, "planner_context")
            return
        # A short independent session; only detached metadata survives its closure.
        # One deadline includes subprocess startup, initialize and all list pages.
        async with asyncio.timeout(settings.mcp_timeout):
            async with document_session(timeout=settings.mcp_timeout, max_tool_calls=settings.max_tool_calls, max_tool_corrections=settings.max_tool_corrections, enabled=False if mode == "test" else None) as client:
                _, metadata = await discover(state, client, "planner_context")
        runner.tool_inventory = metadata

    async def research(state):
        evidence = {e["id"]: e for e in state["evidence"]}
        unavailable = {(s["document_id"], s["section_id"]): s for s in state.get("unavailable_sources", [])}
        failures = []
        search_hits = []
        exhausted = set(state.get("web_budget_exhausted", []))
        async with research_session() as client:
            if persistent_client is not None:
                runner.web_budget = await client.remaining_web_budget()
            async def invoke_tool(name, args):
                public_name = name if name in ("search_documents", "get_section", "web_search", "read_page") else "unknown"
                call_id = uuid4().hex
                public = {"tool": public_name, "tool_call_id": call_id}
                await publish("tool_start", state, {**public, "input_summary":tool_input_summary(name, args)})
                try:
                    result = await client.call(name, args)
                except RecoverableToolError:
                    await publish("tool_error", state, {**public, "reason":"입력 오류로 재조회가 필요합니다."})
                    return {"error":{"code":"invalid_tool_input", "message":"Check tool arguments and search for valid document/section IDs before retrieving again."}}
                except Exception as exc:
                    category = safe_web_category(exc)
                    if isinstance(exc, WebToolFailure) and category == "budget":
                        exhausted.add("search" if name == "web_search" else "read")
                        state["web_budget_exhausted"] = sorted(exhausted)
                        remaining = await client.remaining_web_budget()
                        await publish("tool_error", state, {**public, "web_category":"budget", "recoverable":True, "reason":web_failure_reason("budget")})
                        return {"error":{"code":"web_budget_exhausted", "message":"Do not retry the exhausted operation. Finish with existing verified evidence and disclose incomplete coverage; never invent evidence."}, "remaining_run_web_budget":remaining}
                    failures.append(exc)
                    await publish("tool_error", state, {**public, "web_category":category, "recoverable":False, "reason": web_failure_reason(category) if category != "none" else "자료 조회 도구가 실패했습니다."})
                    raise
                if name in ("search_documents", "web_search"):
                    search_hits.extend(result)
                if name == "get_section":
                    key = (args["document_id"], args["section_id"])
                    if result.get("retrieval_status") == "unavailable":
                        unavailable[key] = result
                        state["unavailable_sources"] = list(unavailable.values())
                        await publish("tool_complete", state, {**public, "count":0, "retrieval_status":"unavailable"})
                        return result
                    unavailable.pop(key, None)
                    evidence[result["id"]] = result
                if name == "read_page":
                    if not client.validate_evidence(result):
                        raise ToolFailure("Unregistered evidence")
                    evidence[result["id"]] = result
                await publish("tool_complete", state, {**public, "count":len(result) if isinstance(result, list) else 1})
                return result
            tools, _ = await discover(state, client, "research_execution")
            @wrap_tool_call
            async def document_tools(request, handler):
                # Route before LangChain coercion/default error handling: every raw
                # attempt reaches the bounded local validator, including unknown tools.
                # Adapter tools supply metadata only: do NOT call handler, which
                # would bypass DocumentClient or dispatch the same request twice.
                call = request.tool_call
                result = await invoke_tool(call["name"], call["args"])
                return ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"], name=call["name"], status="error" if isinstance(result, dict) and "error" in result else "success")

            output = await runner.invoke("Researcher", state, tools, middleware=[document_tools])
            if failures or client.unresolved_error:
                raise ToolFailure("Document tool failed")
            if client.calls == 0 and not (state["iteration"] > 1 and state["evidence"]):
                raise ToolFailure("Researcher did not call a document tool")
            if unavailable and not evidence:
                raise ToolFailure("Optional sources unavailable and no evidence retrieved")
            if search_hits and not evidence and not exhausted:
                raise RetrievalIncomplete("Search matched but no section was retrieved")
            ROLE_SCHEMAS["Researcher"].model_validate(output)
        return {"evidence":list(evidence.values()), "unavailable_sources":list(unavailable.values()), "web_budget_exhausted":sorted(exhausted), **({"status":"budget_exhausted" if exhausted else "empty"} if not evidence else {})}

    def node(role):
        async def execute(state):
            current = deepcopy(state)
            current.update(stage=role, status="running")
            if role == "Planner":
                current["iteration"] += 1
            await publish("node_start", current, {})
            if role == "Planner" and runner.tool_inventory is None:
                await planner_inventory(current)
            if role == "Planner" and persistent_client is not None:
                runner.web_budget = await persistent_client.remaining_web_budget()
            if role == "Researcher":
                updates = await research(current)
            else:
                raw = await runner.invoke(role, current, [])
                value = ROLE_SCHEMAS[role].model_validate(raw).model_dump()
                if role == "Listener":
                    scope = value.pop("scope")
                    support = value.pop("request_support")
                    if support != "unsupported":
                        value["unsupported_reason"] = None
                    updates = value
                    # Only an explicit, schema-validated decision can end research
                    # for a closed corpus. Never infer scope from retrieval/errors.
                    if support == "unsupported":
                        updates["status"] = "unsupported"
                    elif scope == "out_of_scope" and not (mode == "live" and settings.general_web_enabled):
                        updates["status"] = "out_of_scope"
                elif role == "Reporter":
                    # Final source-registry check is independent of model citation repair.
                    validation = {"role": role, "scope": "evidence_integrity"}
                    await publish("validation_start", current, validation)
                    try:
                        validate_citations(value, current["evidence"], validator=persistent_client.validate_evidence if persistent_client is not None else None)
                    except ValueError:
                        await publish("validation_error", current, validation)
                        raise
                    await publish("validation_complete", current, validation)
                    # Reserve a bounded deterministic limitation even if the model
                    # omits optional failures. These identifiers are never citations.
                    sources = current.get("unavailable_sources", [])
                    if sources:
                        documents = sorted({s["document_id"] for s in sources})
                        note = "공식 공개 자료 조회 불가: " + ", ".join(documents) + ". 해당 자료는 근거에서 제외했으며 조회된 자료 범위로만 작성했습니다."
                        value["limitations"] = [note] + [s for s in value["limitations"] if s != note][:7]
                    updates = {"report":value}
                    if current.get("web_budget_exhausted"):
                        value["limitations"] = [web_failure_reason("budget")] + value["limitations"][:7]
                elif role == "Evaluator":
                    updates = {"evaluation":value, "feedback":value["issues"] + value["follow_up"]}
                    previous_ids = set(current["revisions"][-1]["evidence_ids"]) if current["revisions"] else set()
                    ids = [e["id"] for e in current["evidence"]]
                    if current.get("web_budget_exhausted"):
                        updates["status"] = "budget_exhausted"
                    elif value["decision"] == "pass":
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
    builder.add_edge(START, entry)
    builder.add_conditional_edges("Listener", lambda s: END if s["status"] in ("out_of_scope", "unsupported") else "Planner")
    builder.add_edge("Planner", "Researcher")
    builder.add_conditional_edges("Researcher", lambda s: END if s["status"] in ("empty", "budget_exhausted") else "Reporter")
    builder.add_edge("Reporter", "Evaluator")
    builder.add_conditional_edges("Evaluator", lambda s: "Planner" if s["status"] == "running" else END)
    return builder.compile(interrupt_after=["Listener"] if listener_only else None)
