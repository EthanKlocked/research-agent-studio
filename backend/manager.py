"""Bounded process-local run snapshots and replay logs; not durable persistence."""
import asyncio
import logging
import math
from backend.errors import error_category, safe_exception_classes, safe_web_category, web_failure_reason
from backend.schemas import ROLE_SCHEMAS
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from langsmith import tracing_context
from backend.workflow import build_graph
from backend.mcp_client import ToolFailure, document_session

TERMINAL = {"success", "limit_reached", "empty", "out_of_scope", "unsupported", "budget_exhausted", "error", "cancelled"}

def now():
    return datetime.now(timezone.utc).isoformat()

class RunRejected(Exception):
    def __init__(self, message, status_code=429):
        super().__init__(message)
        self.status_code = status_code

@dataclass
class RunRecord:
    state: dict
    events: deque
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: bool = False
    finalized: bool = False
    validated_state: dict | None = None
    # Per model-call ID, separate from bounded/replayed events: (completed, estimate).
    model_costs: dict = field(default_factory=dict)

    def observe_cost(self, kind, data):
        call = (data or {}).get("model_call_id")
        if not isinstance(call, str) or len(call) != 32 or any(c not in "0123456789abcdef" for c in call):
            return
        if kind == "model_start":
            self.model_costs.setdefault(call, (False, None))
        elif kind == "model_complete" and not self.model_costs.get(call, (False, None))[0]:
            value = ((data or {}).get("observation") or {}).get("estimated_cost_usd")
            try:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
            except OverflowError:
                valid = False
            self.model_costs[call] = (True, value if valid else None)

    def cost_summary(self):
        known = [value for _, value in self.model_costs.values() if value is not None]
        try:
            subtotal = math.fsum(known) if known else None
            if subtotal is not None and not math.isfinite(subtotal):
                subtotal = None
        except OverflowError:
            subtotal = None
        unknown = len(self.model_costs) - len(known)
        return {"model_requests": len(self.model_costs), "priced_requests": len(known),
                "unknown_requests": unknown, "known_estimated_cost_usd": subtotal,
                "estimated_cost_usd": subtotal if unknown == 0 else None,
                "estimate_status": "unknown" if subtotal is None else "partial" if unknown else "complete"}

def safe_error(exc):
    category = error_category(exc)
    if category == "timeout":
        return "실행 시간 제한에 도달했습니다. 요청 또는 모델 응답 시간이 초과되었습니다."
    if category in ("tool", "retrieval_incomplete"):
        return "자료 조회 도구가 실패했습니다. 근거 없음과는 다른 오류입니다."
    return "실행 오류: 모델 응답 또는 출력 검증에 실패했습니다."

class RunManager:
    def __init__(self, settings, *, clock=None):
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.runs = OrderedDict()
        self.tasks = {}

    def snapshot(self, run_id):
        return deepcopy(self.runs[run_id].state)

    async def emit(self, run_id, kind, state, data=None):
        record = self.runs[run_id]
        if record.finalized or (record.cancel_requested and kind != "terminal"):
            return
        if kind == "terminal":
            if record.cancel_requested:
                state = {**state, "status": "cancelled", "errors": []}
            record.finalized = True
        if kind == "node_complete" and state.get("stage") == "Evaluator":
            record.validated_state = deepcopy(state)
        if record.state.get("mode") == "live":
            record.observe_cost(kind, data)
        seq = record.state["last_seq"] + 1
        record.state = deepcopy(state)
        record.state["last_seq"] = seq
        record.state["cost_summary"] = record.cost_summary() if record.state.get("mode") == "live" else None
        event = {"seq":seq, "run_id":run_id, "type":kind, "timestamp":now(), "data":{**(data or {}), "snapshot":deepcopy(record.state)}}
        record.events.append(event)
        record.changed.set()

    async def start(self, request):
        if request.mode == "test" and not self.settings.test_mode:
            raise RunRejected("테스트 모드는 운영자가 활성화해야 합니다.", 403)
        if request.mode == "live" and not self.settings.configured:
            raise RunRejected("모델 연결 설정이 없습니다. 로컬 환경변수를 확인하세요.", 409)
        if request.mode == "live" and request.scenario != "pass":
            raise RunRejected("시나리오 주입은 테스트 모드에서만 허용됩니다.", 422)
        if sum(not task.done() for task in self.tasks.values()) >= self.settings.max_concurrent:
            raise RunRejected("동시 실행 한도에 도달했습니다.")
        while len(self.runs) >= self.settings.max_runs:
            old = next((rid for rid in self.runs if self.tasks[rid].done()), None)
            if old is None:
                raise RunRejected("실행 저장 한도에 도달했습니다.")
            self.runs.pop(old)
            self.tasks.pop(old)
        run_id = uuid4().hex
        instant = self.clock()
        if instant.utcoffset() is None:
            raise ValueError("Run clock must be timezone-aware")
        context = {"started_at": instant.isoformat(), "current_date": instant.date().isoformat(),
                   "timezone": instant.tzname()}
        state = dict(run_id=run_id, question=request.question, mode=request.mode, status="queued", stage=None, iteration=0, started_at=context["started_at"], run_context=context, unsupported_reason=None, web_budget_exhausted=[], finished_at=None, last_seq=0, interpreted_request="", plan=[], evidence=[], unavailable_sources=[], report=None, revisions=[], evaluation=None, feedback=[], errors=[], partial_result=None, cost_summary=None)
        self.runs[run_id] = RunRecord(state, deque(maxlen=self.settings.max_events))
        self.tasks[run_id] = asyncio.create_task(self.execute(run_id, request))
        return self.snapshot(run_id)

    async def execute(self, run_id, request):
        async def publish(kind, state, data):
            await self.emit(run_id, kind, state, data)
        try:
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.settings.run_timeout):
                    if request.mode == "live" and self.settings.general_web_enabled:
                        # Classify before even starting MCP: unsupported requests
                        # must not depend on tool infrastructure availability.
                        listener = build_graph(self.settings, request.mode, request.scenario, publish, listener_only=True)
                        result = await listener.ainvoke(self.snapshot(run_id), config={"recursion_limit":32, "callbacks":[]})
                        # Own the AnyIO/MCP lifetime in this task, around the entire
                        # research graph, not across node tasks. Discovery never closes it.
                        if result["status"] not in TERMINAL:
                            async with document_session(timeout=self.settings.mcp_timeout,
                                    max_tool_calls=self.settings.max_tool_calls,
                                    max_tool_corrections=self.settings.max_tool_corrections,
                                    search_provider="exa", exa_api_key=self.settings.exa_api_key) as client:
                                graph = build_graph(self.settings, request.mode, request.scenario, publish, persistent_client=client, entry="Planner")
                                result = await graph.ainvoke(result, config={"recursion_limit":32, "callbacks":[]})
                    else:
                        graph = build_graph(self.settings, request.mode, request.scenario, publish)
                        result = await graph.ainvoke(self.snapshot(run_id), config={"recursion_limit":32, "callbacks":[]})
            state = result
        except asyncio.CancelledError:
            state = self.snapshot(run_id)
            state["status"] = "cancelled"
        except (Exception, BaseExceptionGroup) as exc:
            state = self.snapshot(run_id)
            category = error_category(exc)
            role = state.get("stage") if state.get("stage") in ROLE_SCHEMAS else "Workflow"
            messages = {
                "output_limit":"모델 출력 토큰 한도에 도달했습니다. 운영자의 출력 한도 설정을 확인하세요.",
                "validation":"모델 JSON, 출력 스키마 또는 인용 검증에 실패했습니다.",
                "retrieval_incomplete":"검색 결과는 있지만 본문 구간을 조회하지 않았습니다. 근거 없음과는 다른 오류입니다.",
            }
            message = messages.get(category, safe_error(exc))
            web_category = safe_web_category(exc)
            if web_category != "none":
                message += f" [web_category={web_category}] " + web_failure_reason(web_category)
            logging.getLogger(__name__).warning("run_failed role=%s category=%s classes=%s web_category=%s", role, category, safe_exception_classes(exc), safe_web_category(exc))
            state.update(status="error", errors=[f"[{role}/{category}] {message}"])
            checkpoint = self.runs[run_id].validated_state
            if checkpoint and not self.runs[run_id].cancel_requested:
                previous = checkpoint["revisions"][-1]
                state["report"] = deepcopy(previous["report"])
                state["report"]["limitations"] = state["report"]["limitations"][:7] + ["후속 수정 실행이 실패하여 이전 검증 보고서를 보존했습니다. 평가 통과가 아니며 미해결 이슈가 남아 있습니다."]
                state["evidence"] = deepcopy(checkpoint["evidence"])
                state["evaluation"] = deepcopy(previous["evaluation"])
                state["feedback"] = previous["evaluation"]["issues"] + previous["evaluation"]["follow_up"]
                state["partial_result"] = {"iteration": previous["iteration"], "reason": "revision_failed"}
        state["finished_at"] = now()
        await self.emit(run_id, "terminal", state)

    async def cancel(self, run_id):
        record = self.runs[run_id]
        if not record.finalized:
            task = self.tasks[run_id]
            # Record intent before signalling: MCP/AnyIO cleanup may replace the
            # CancelledError with an ExceptionGroup, or a callee may swallow it.
            # Repeated requests must not interrupt the first request's cleanup.
            if not record.cancel_requested:
                record.cancel_requested = True
                task.cancel()
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            # A task cancelled before its first instruction cannot finalize itself.
            if not record.finalized:
                state = self.snapshot(run_id)
                state.update(status="cancelled", finished_at=now())
                await self.emit(run_id, "terminal", state)
        return self.snapshot(run_id)

    async def close(self):
        for rid in list(self.runs):
            if not self.tasks[rid].done():
                await self.cancel(rid)
