# Frontend workbench

Korean-first React + TypeScript workbench. Design direction: an editorial report on white paper, a pale sage work-notes rail, restrained charcoal/teal hierarchy, and a stable five-stage ribbon. The report, its revisions and source excerpts are primary; technical events are collapsed. No external fonts, CDNs or model credentials are used.

## Commands

Use Node.js 22.22+ and the committed lockfile:

```sh
npm ci
npm test
npm run typecheck
npm run build
```

`dist/` is the build artifact for the backend's single-origin static serving. Start the backend from the repository root with `bash scripts/start.sh --test` (Windows: `.\scripts\start.ps1 -TestMode`); in a second terminal, run `npm run dev` from `frontend/` for hot reload. Vite binds to loopback and proxies `/api` to `http://127.0.0.1:8765`. Production uses same-origin requests and needs no proxy.

## Runtime contract

`src/types.ts` defines the snapshot and event types described in [the architecture](../docs/architecture.md). The client reads `/api/config`, submits explicit `question`, `mode` and `scenario` to `/api/runs`, reads snapshots, and posts cancellation to `/api/runs/{id}/cancel`.

SSE uses ordinary `message` events from `/api/runs/{id}/events?after={last_seq}`. The envelope is `{seq, run_id, type, timestamp, data: {snapshot, ...safe_metadata}}`. Only newer same-run snapshots are applied. On disconnect the EventSource is closed; recovery reads the server snapshot before opening a new stream after its last sequence. Only a non-null `finished_at` or an explicit terminal event (using its server timestamp if needed) closes the stream; evaluator success/limit/empty statuses alone remain active. Unmount also closes streams. Server-restart 404s clear the stale run reference and enable a new run.

Recoverable `tool_error` events are displayed as tool input errors with a safe summary, not a completed empty lookup or a terminal run failure. Subsequent snapshots and the final terminal event remain authoritative. Tests exercise error → successful empty lookup → successful retrieval → updated report → completion without rendering raw arguments or exception details.

Only the run ID is optionally saved in sessionStorage (`research-studio.run-id`). Run content is never persisted in browser storage. The server remains authoritative; a saved ID does not promise durable recovery.

Fixtures exist **only in test files**. Test-mode progress and results always arrive from the backend, not timers or bundled fallback data. The only interval displays elapsed wall time.

## Coverage and verification

28 Vitest / Testing Library tests cover monotonic sequencing, deduplication, cross-run isolation, safe links, configuration/mode gating, explicit create payload, event-driven stage updates, citations/source focus, revision comparison, cancellation, empty/error/limit distinction, snapshot-first reconnection, 404 recovery, run-ID restoration and stream cleanup. Regressions cover unfinished evaluator statuses, final branch/terminal retention, stable elapsed time, live-mode `scenario: "pass"`, revision selection, and safe MCP `input_summary` display without raw inputs.

Verified on macOS: clean `npm ci`, all tests, standalone TypeScript check, production build, and `npm audit` with zero vulnerabilities. Lockfile resolves React 19.1.0, Vite 6.4.3 and Vitest 4.1.11.

Browser checks against the real backend covered 1366×768, 1440×900 and 390px widths, revision/source interactions, page reload and cancellation. See [verification scope](../docs/verification.md). Component tests mock the transport and are not proof of live-provider E2E execution. Live-provider verification requires operator-local configuration; Windows execution is not yet verified.
