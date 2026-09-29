# Verification scope

## Executed on macOS

- Locked Python install and clean npm install; TypeScript check and production build passed.
- Python suite: 124 passing tests, including 11 static PowerShell-launcher contract tests. Core tests include actual LangGraph/LangChain execution and real MCP stdio initialization, discovery, search and section retrieval.
- Frontend suite: 28 passing tests covering snapshots, streaming, reconnect, terminal lifecycle, revision selection, safe tool summaries and live-mode request selection.
- Browser checks at 1440×900 and 1366×768, plus 390px mobile: revise → retained evidence → second report; source links; revision comparison; page reload; pass/limit/empty/tool-error states and cancellation.
- Three browser-triggered cancellations finalized as cancelled with finish timestamps and no errors. No horizontal mobile overflow or browser console errors observed.
- Source/build secret-pattern inspection and npm audit (zero reported vulnerabilities). Neither is a comprehensive security guarantee.

Backend coverage includes malformed citations/evaluation schemas, timeouts, concurrency/input/retention limits, run isolation, SSE ordering, bounded tool permissions, startup/cleanup cancellation and subprocess exit. Model responses are deterministic fixtures or isolated HTTP mocks: **none of this verifies a live provider**.

## Live-path resilience checks

The real ChatOpenAI adapter, LangChain agents, LangGraph and MCP stdio are exercised together using `httpx.MockTransport` provider responses. Tests cover JSON fences, rejection of prose/malformed/oversized/non-object outputs, schema/citation failures, invalid-ID correction, unresolved/repeated errors, total call budgets, unknown-tool redaction, remote errors, timeout and cancellation. No real provider request or credential is involved.

Historical `bash scripts/test.sh` after the Windows-compatibility fixes: Python **104 passed in 21.80s**, frontend **28 passed**, TypeScript and Vite build passed. Explicit UTF-8 reads are covered by a project-scoped AST guard and fresh-interpreter cp949-default simulations for imports, app creation and dataset retrieval/search. Process-cleanup checks use retained process handles, return codes and bounded waits, with live/exited real-child regressions and real MCP cancellation coverage. These ran on macOS, not Windows.

The earlier browser smoke on the live-resilience changes confirmed an actual `tool_error` event shows an input-error warning distinct from an empty lookup, unresolved failure ends as error, and the ordinary revise scenario still produces a second report with four claims. Recovery-to-success is verified through the mock-provider/real-MCP integration tests and component tests, not a live model/browser run.

## Live output and retrieval fixes

Latest full `bash scripts/test.sh` on macOS: **124 Python tests passed in 26.47s**, **28 frontend tests passed**, TypeScript and production build passed. Mock HTTP provider tests exercise real agents/graph/local MCP: metadata-only search, search-without-retrieval errors versus zero hits, bounded validation repair with sanitized feedback, configured token budgets, length termination before tool dispatch, dataset scope and safe failure categories. These are not real Gemini/provider calls. No new browser smoke was performed for this backend-only change.

## Windows boundary

PowerShell launchers mirror the install/start/test commands, check native exit codes and restore caller location/environment. Static contract tests do not prove PowerShell parsing or Windows process behavior. Direct development-environment execution was on macOS.

User-provided Windows feedback reports PowerShell 5.1 / Python 3.12.14 installation, MCP child processes and 72 passing tests on an earlier revision, alongside implicit cp949 decoding and POSIX PID-helper failures. The user subsequently clarified that verification was **API-only; no Windows browser flow was checked**. The earlier browser-verification wording was incorrect. Exact tested commits and local adjustments were not supplied, so these results do not establish current-commit Windows/full-suite success.

Subsequent user-reported live API checks reached Gemini 2.5-family responses and exposed missing section retrieval, oversized schema fields and output-token truncation. They also reported Gemini 3.x tool-call failure from missing thought-signature roundtripping. These are externally reported observations, not locally reproduced live-provider verification or a blanket model-family compatibility guarantee. Current-fix Windows API and browser checks, exact-model compatibility and end-to-end output quality remain to be verified.

## Live verification remaining

After operator-local settings, verify provider authentication, model tool calls and JSON output, claim/evidence agreement, natural revise behavior and provider cancellation behavior. The real workflow may pass on its first evaluation. Explicit test scenarios must not be represented as real model judgment.

The corpus is small and historical, not live web research. Run state is in memory only. This is a loopback single-user prototype, not an internet-facing service.

## Screenshots

- [Initial screen](idle-1440.png)
- [Completed report](result-1440.png)
- [1366px report](result-1366.png)
- [Selected evidence](evidence-1366.png)
- [Cancelled run](cancelled-1440.png)
- [Tool input error](tool-input-error-1366.png)
