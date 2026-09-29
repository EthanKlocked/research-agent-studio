# Verification scope

## Request/Reporter deadlines and omitted search limits

`PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q` passes **468 Python tests in 61.44s** on macOS. Before production changes, the new regression file produced **20 expected failures and 70 passes**: old 30s/60s request/Reporter defaults and invalid summaries for omitted limits. After the fix, the focused new/default, summary and stabilization suites passed **114 tests**.

Default model request timeout is now **60s** and the whole Reporter budget is **120s**, allowing more room for long revision evidence and the existing single schema/citation repair. Excerpts are not further truncated. Listener/Planner/Evaluator remain **60s**, Researcher **180s**, whole run **600s**, MCP operation **10s**. Independent explicit overrides remain authoritative; missing/blank/whitespace timeout values select defaults, and finite positive values up to 7200s are accepted. A role/run deadline can still interrupt a request or repair: two full 60s requests plus overhead are not guaranteed inside 120s.

Tests cover default/override/boundary behavior for every configurable request/role/run timeout, existing provider timeout forwarding and whole-role enforcement, omitted search limits matching each named tool's shared schema default (currently 5), and explicit invalid/null/bool/string/out-of-range limits remaining invalid without coercion or argument disclosure. Existing mock-provider tests continue to cover bounded Reporter schema/citation repair and revision evidence handling.

This is offline backend verification with deterministic fixtures, injected HTTP responses and real local MCP subprocesses, not live latency/quality or evidence-completeness validation. No actual `.env` was read, no existing server on port 8765 was accessed, and no paid/live provider calls were made. Frontend tests/build, browser smoke and Windows execution were not rerun for this backend-only change. Earlier counts below describe historical verification stages.

## Citation repair and remaining web allowances

`PYTHON_DOTENV_DISABLED=1 bash scripts/test.sh` passes **378 Python tests and 59 frontend tests**, including TypeScript and production build. Reporter receives only the exact citation `id`, not competing retrieval identifiers. Citation failures are `validation`; correction shares the existing single schema/citation repair allowance and does not perform extra retrieval. Wrong document IDs and forged citations are rejected rather than silently accepted.

Mock-provider and real local MCP tests cover seven shortened citations corrected to exact evidence IDs, structured allowlisted web failure categories, sanitized `web_category` logging, and authoritative remaining per-run search/read allowances supplied to Planner. Revision runs may reuse previously admitted evidence. Missing or malformed budget resources fail closed to zero remaining allowance. These checks do not establish why an earlier live second-iteration lookup failed, or prove live citation accuracy. No live server access, Exa calls, credential inspection or current Windows execution was performed.

## Scope outcome and portable path regression checks

After the scope fix, `bash scripts/test.sh` on macOS passes **345 Python tests and 59 frontend tests**, including TypeScript and production build. Listener provides a validated scope classification: explicit `out_of_scope` with general web disabled ends before retrieval, with a distinct outcome rather than a tool error. Partial/unknown or omitted legacy classifications continue; web-enabled live runs do not reject based on closed-corpus scope. Empty results and real tool failures retain their existing behavior. Scope classification is model-authored: these offline protocol tests do not prove live classification accuracy, and an unknown or incorrect classification can still enter ordinary retrieval.

Frontend tests cover provisional versus terminal scope snapshots, stream closure, restoration and reconnect. Both parser-path assertions now compare `Path` values, with Windows-style path semantics covered separately; this is not direct Windows execution. The MCP session comment documents the narrowly scoped Exa credential forwarding. No live provider calls or new browser smoke were used for these checks.

## General web and dashboard verification

Frontend capability-contract TDD: three new regressions first failed on missing capability/offline labels, then passed. The final frontend suite passes **56 tests across 4 files**; `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` also pass on macOS. Checks cover Exa configured versus actual offline test execution, live-model configuration without general web, observed web tool labels not implying availability, and nullable dataset dates. Existing dashboard coverage includes granular model/validation/repair progress, terminal lifecycle, evidence dates/provenance, reconnect and retained reports.

General-web backend tests use injected Exa HTTP responses, mock model-provider responses and real local MCP/graph paths. They cover search-versus-evidence separation, run-local IDs, immutable reads, request limits, quota/auth failures and offline test isolation. **These are mock/protocol checks, not live Exa or live LLM validation.** They do not establish account credit balance, billing safety, external service availability or report truth. The frontend checks above use mocked API/SSE data, not a new browser or Windows run. Historical suite counts and browser results below describe earlier verification stages, not new Exa validation.

Final local `bash scripts/test.sh`: **333 Python tests and 56 frontend tests passed**, with production build and separate TypeScript check. Async-provider regressions verify an absolute deadline around headers and streamed bytes, plus active cancellation and stream/client cleanup. Independent backend and frontend reviews passed after fixes for the slow-drip deadline, retained-report identity and generic tool-error labeling.

A separate browser smoke used the actual local API/graph/MCP/SSE with deterministic test responses: two research iterations completed, four sources and two reviewed revisions survived snapshot restoration, and 390/768/1440px layouts had no horizontal overflow. Initial inspection encountered stale browser-only fixture interception; it was discarded and these observations were made in a fresh isolated context. Browser contexts and the temporary server were closed. This was not live Exa/LLM or Windows verification.

Reproduce local automated checks:

```bash
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

An operator-authorized live Exa smoke remains separate: check no card/no purchase and auto recharge OFF in the account first, configure only local credentials, then inspect search/read evidence, dates, source links and account usage. A zero recharge limit may mean unlimited; local caps cannot enforce free-credit-only use. Do not send private questions or URLs. No live request, credential inspection or account change was performed for this frontend/documentation verification.

## Earlier verification on macOS

- Locked Python install and clean npm install; TypeScript check and production build passed.
- Python suite: 221 passing tests, including 11 static PowerShell-launcher contract tests. Core tests include actual LangGraph/LangChain execution and real MCP stdio initialization, discovery, search and section retrieval.
- Frontend suite: 32 passing tests covering snapshots, streaming, reconnect, terminal lifecycle, revision selection, safe tool summaries and live-mode request selection.
- Browser checks at 1440×900 and 1366×768, plus 390px mobile: revise → retained evidence → second report; source links; revision comparison; page reload; pass/limit/empty/tool-error states and cancellation.
- Three browser-triggered cancellations finalized as cancelled with finish timestamps and no errors. No horizontal mobile overflow or browser console errors observed.
- Source/build secret-pattern inspection and npm audit (zero reported vulnerabilities). Neither is a comprehensive security guarantee.

Backend coverage includes malformed citations/evaluation schemas, timeouts, concurrency/input/retention limits, run isolation, SSE ordering, bounded tool permissions, startup/cleanup cancellation and subprocess exit. Model responses are deterministic fixtures or isolated HTTP mocks: **none of this verifies a live provider**.

## Live-path resilience checks

The real ChatOpenAI adapter, LangChain agents, LangGraph and MCP stdio are exercised together using `httpx.MockTransport` provider responses. Tests cover JSON fences, rejection of prose/malformed/oversized/non-object outputs, schema/citation failures, invalid-ID correction, unresolved/repeated errors, total call budgets, unknown-tool redaction, remote errors, timeout and cancellation. No real provider request or credential is involved.

Historical `bash scripts/test.sh` after the Windows-compatibility fixes: Python **104 passed in 21.80s**, frontend **28 passed**, TypeScript and Vite build passed. Explicit UTF-8 reads are covered by a project-scoped AST guard and fresh-interpreter cp949-default simulations for imports, app creation and dataset retrieval/search. Process-cleanup checks use retained process handles, return codes and bounded waits, with live/exited real-child regressions and real MCP cancellation coverage. These ran on macOS, not Windows.

The earlier browser smoke on the live-resilience changes confirmed an actual `tool_error` event shows an input-error warning distinct from an empty lookup, unresolved failure ends as error, and the ordinary revise scenario still produces a second report with four claims. Recovery-to-success is verified through the mock-provider/real-MCP integration tests and component tests, not a live model/browser run.

## Live output and retrieval fixes

Historical full `bash scripts/test.sh` on macOS: **124 Python tests passed in 26.47s**, **28 frontend tests passed**, TypeScript and production build passed. Mock HTTP provider tests exercise real agents/graph/local MCP: metadata-only search, search-without-retrieval errors versus zero hits, bounded validation repair with sanitized feedback, configured token budgets, length termination before tool dispatch, dataset scope and safe failure categories. These are not real Gemini/provider calls. No new browser smoke was performed for this backend-only change.

## Official sources and revision resilience

Full `bash scripts/test.sh` on macOS: **211 Python passed in 27.33s**, **32 frontend passed**, TypeScript/build passed. Financial-row extraction uses bounded tokenization and exact four-column validation; isolated malformed-long-row regressions cover parser and store paths, including lock release and negative caching. Coverage includes optional-source unavailability without fabricated evidence, offline test-mode isolation, deadlines, bounded class-chain diagnostics and partial report preservation.

Actual public Apple HTTP through real MCP stdio was independently repeated; see [source smoke evidence](../data/public_source_smoke.md). Both fixed documents returned parsed facts and cache lineage. No real LLM was called. Poppler was already installed on this Mac; Windows parser availability remains unverified.

Browser QA used real graph/MCP/API/SSE and deterministic model responses. A local-only harness injected a Researcher timeout at revision 2: prior report/evidence, non-pass banner, unresolved evaluation and timeout message remained visible, including after reload. A subsequent ordinary revise scenario completed with a second report. [Partial result screenshot](partial-result-1440.png) is 1280px wide (legacy filename), from the injected-error test—not a live-model failure. QA page and server were closed afterward.

## MCP contract refactor

Full `bash scripts/test.sh` on macOS: **221 Python passed in 30.15s**, **32 frontend passed**, TypeScript/build passed. `uv pip check` reported compatible installed packages. Adapter 0.3.2 is the only added lockfile package; no existing package versions changed. Tests exercise real MCP discovery and model metadata parity, inventory mismatch/duplicate rejection, bounded discovery/cancellation, no adapter double-dispatch and existing safety controls. OpenAI wire conversion removes JSON Schema titles; parity tests normalize only those titles at the wire layer and require exact adapter schema parity. No new live-provider, public-source or browser run was performed for this internal refactor.

## Windows verification — user-reported results

The user reported final verification on **commit `4c672b8`, with no local modifications**, using **Windows 11, PowerShell 5.1 and Python 3.12.14**. These are operator-provided results, not a Windows execution independently reproduced on the macOS development host.

- Backend: **378/378 tests passed**.
- Frontend: **59/59 tests passed**; TypeScript typecheck and production build passed.
- Live model: **`gemini-2.5-flash`**. Apple questions succeeded in every reported attempt (reported success rate 100%; number of attempts not specified).
- Exa web questions covering KOSPI, today's stock market and electric-vehicle batteries: **4/4 live runs succeeded**. This is four total runs across those topics, not four per topic.
- With web search disabled, an out-of-scope question terminated normally with **`out_of_scope`**.
- Successful runs took approximately **30–70 seconds**, with most time spent waiting for the LLM. Thinking-budget limits and streaming are deferred performance work, not changes implemented or validated here.

### Official public sources — separate earlier revision

The user also reported **Poppler 26.09** PDF and HTML extraction working normally, with **4/5 live-model runs successful on commit `1e734a6`**. This result belongs to that earlier revision and must not be presented as a `4c672b8` public-source rerun.

These observed successes do not establish universal model compatibility or independently audited report accuracy. Earlier Gemini 3.x thought-signature/tool-call failures remain a separate known limitation; this report verifies `gemini-2.5-flash`, not Gemini 3.x.

## Live verification remaining

After operator-local settings, verify provider authentication, model tool calls and JSON output, claim/evidence agreement, natural revise behavior and provider cancellation behavior. The real workflow may pass on its first evaluation. Explicit test scenarios must not be represented as real model judgment.

The default corpus and offline test scenario are small and historical. General public web research requires explicit Exa configuration in live mode. The Windows report above establishes successful runs in the reported environment; other environments/models, billing behavior, provider cancellation and detailed factual quality still require operator-local validation. Run state is in memory only. This is a loopback single-user prototype, not an internet-facing service.

## Screenshots

- [Initial screen](idle-1440.png)
- [Completed report](result-1440.png)
- [1366px report](result-1366.png)
- [Selected evidence](evidence-1366.png)
- [Cancelled run](cancelled-1440.png)
- [Tool input error](tool-input-error-1366.png)
