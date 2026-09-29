"""Bounded process-local run snapshots and replay logs; not durable persistence."""
import asyncio
import logging
from backend.errors import error_category, safe_exception_classes
from backend.schemas import ROLE_SCHEMAS
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4
from langsmith import tracing_context
from backend.workflow import build_graph
from backend.mcp_client import ToolFailure, document_session

TERMINAL = {"success", "limit_reached", "empty", "error", "cancelled"}

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

def safe_error(exc):
    category = error_category(exc)
    if category == "timeout":
        return "실행 시간 제한에 도달했습니다. 요청 또는 모델 응답 시간이 초과되었습니다."
    if category in ("tool", "retrieval_incomplete"):
        return "자료 조회 도구가 실패했습니다. 근거 없음과는 다른 오류입니다."
    return "실행 오류: 모델 응답 또는 출력 검증에 실패했습니다."

class RunManager:
    def __init__(self, settings):
        self.settings = settings
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
        seq = record.state["last_seq"] + 1
        record.state = deepcopy(state)
        record.state["last_seq"] = seq
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
        state = dict(run_id=run_id, question=request.question, mode=request.mode, status="queued", stage=None, iteration=0, started_at=now(), finished_at=None, last_seq=0, interpreted_request="", plan=[], evidence=[], unavailable_sources=[], report=None, revisions=[], evaluation=None, feedback=[], errors=[], partial_result=None)
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
                        # Own the AnyIO/MCP lifetime in this task, around the entire
                        # graph, not across node tasks. Discovery never closes it.
                        async with document_session(timeout=self.settings.mcp_timeout,
                                max_tool_calls=self.settings.max_tool_calls,
                                max_tool_corrections=self.settings.max_tool_corrections,
                                search_provider="exa", exa_api_key=self.settings.exa_api_key) as client:
                            graph = build_graph(self.settings, request.mode, request.scenario, publish, persistent_client=client)
                            result = await graph.ainvoke(self.snapshot(run_id), config={"recursion_limit":32, "callbacks":[]})
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
                "validation":"한 번의 보정 후에도 모델 JSON 또는 출력 스키마 검증에 실패했습니다.",
                "retrieval_incomplete":"검색 결과는 있지만 본문 구간을 조회하지 않았습니다. 근거 없음과는 다른 오류입니다.",
            }
            message = messages.get(category, safe_error(exc))
            logging.getLogger(__name__).warning("run_failed role=%s category=%s classes=%s", role, category, safe_exception_classes(exc))
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
