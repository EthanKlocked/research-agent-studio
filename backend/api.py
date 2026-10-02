"""Loopback single-origin API and built frontend. No remote endpoint editing."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import Settings, ROOT
from backend.manager import RunManager, RunRejected, TERMINAL
from backend.schemas import RunRequest
from mcp_server.dataset import general_dataset_scope

def create_app(settings=None, frontend_dir=None):
    settings = settings or Settings.from_env()
    manager = RunManager(settings)
    dataset = general_dataset_scope() if settings.general_web_enabled else json.loads((ROOT / "data/apple_fy2024.json").read_text(encoding="utf-8"))
    dist = Path(frontend_dir) if frontend_dir else ROOT / "frontend/dist"

    @asynccontextmanager
    async def lifespan(app):
        settings.warn_gateway_timeouts()
        yield
        await manager.close()

    app = FastAPI(title="Research Agent Studio", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_boundary(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail":"다른 출처의 요청은 허용되지 않습니다."}, status_code=403)
            try:
                content_length = int(request.headers.get("content-length", "0") or "0")
            except ValueError:
                return JSONResponse({"detail":"잘못된 요청 크기입니다."}, status_code=400)
            if content_length > 16000:
                return JSONResponse({"detail":"요청이 너무 큽니다."}, status_code=413)
            body = bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > 16000:
                            return JSONResponse({"detail":"요청이 너무 큽니다."}, status_code=413)
                        body.extend(chunk)
            except TimeoutError:
                return JSONResponse({"detail":"요청 시간이 초과되었습니다."}, status_code=408)
            # Starlette's cached request replays this bounded body to the endpoint.
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail":"입력 형식 또는 길이를 확인하세요."}, status_code=422)

    @app.get("/api/config")
    async def config():
        return {"configured":settings.configured, "test_mode_available":settings.test_mode, "capabilities":{"general_web":settings.general_web_enabled, "search_provider":"exa" if settings.general_web_enabled else None}, "dataset":{k:dataset[k] for k in ("name", "as_of")}, "limits":{"max_iterations":settings.max_iterations}}

    @app.post("/api/runs", status_code=202)
    async def start(body: RunRequest):
        try:
            return await manager.start(body)
        except RunRejected as exc:
            raise HTTPException(exc.status_code, str(exc)) from None

    def exists(run_id):
        if run_id not in manager.runs:
            raise HTTPException(404, "실행 기록이 없습니다. 서버 재시작 또는 보관 한도에 의해 삭제될 수 있습니다.")

    @app.get("/api/runs/{run_id}")
    async def snapshot(run_id: str, include_events: bool = False):
        exists(run_id)
        result = manager.snapshot(run_id)
        if include_events:
            # No await between snapshot and history: one event-loop-consistent cut.
            # Existing bounded log only; never place history inside event snapshots.
            result["retained_events"] = list(manager.runs[run_id].events)
        return result

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        exists(run_id)
        return await manager.cancel(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = Query(0, ge=0)):
        exists(run_id)
        record = manager.runs[run_id]
        async def stream():
            cursor = after
            while True:
                if await request.is_disconnected():
                    return
                record.changed.clear()
                pending = [e for e in record.events if e["seq"] > cursor]
                for event in pending:
                    cursor = event["seq"]
                    yield "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"
                    if event["type"] == "terminal":
                        return
                if record.state["finished_at"] is not None:
                    return
                try:
                    await asyncio.wait_for(record.changed.wait(), 10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-store", "X-Accel-Buffering":"no"})

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail":"프론트엔드를 먼저 빌드하세요."}, status_code=503)
    return app

app = create_app()
