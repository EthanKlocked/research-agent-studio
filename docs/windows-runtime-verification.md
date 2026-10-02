# Windows-reported runtime feedback: verification

Issue #30. Base `2ee521cbe522bf7c8d764d9d1a266f7adafcc0d5`. Implements approved items 1–5; role-specific aliases (item 6) remain proposal-only. No merge or independent-review verdict is claimed here.

## Reported environment — not independently executed

The user reported **Windows 11, Python 3.12.14, Docker Desktop 4.93 with WSL2, gemini-2.5-flash**, commit `2ee521c`, no local modifications. Preserve those version strings as supplied, not a correction or independent environment check. Reported results: backend **566 passed / 17 Docker tests skipped**, frontend **96 passed**, unsupported request about **5s**, Korean market “today” first pass **67.8s**, prior future-date/budget issues not reproduced, gateway **60.9s / 8 primary / 0 fallback**, expected metadata visible. Reported per-call residual **133–2672 tokens**, per-run estimate approximately **$0.017 excluding / $0.038 including residual**. These amounts are not our billing measurements or provider-price verification.

## Implemented contracts

1. **Residual pricing:** `LLM_RESIDUAL_PRICING=unknown` remains conservative. Explicit `output` opt-in prices only positive `total-input-output` residuals at the configured output rate. It never calls residual “reasoning,” never adds explicit reasoning details again, and marks each estimate assumption. A separate input/output-only subtotal explicitly excludes residual. Direct connections use `configured-model`; gateway uses only the verified served alias, including fallback. Unknown deployment, missing/zero/inconsistent usage or missing prices stay unknown. Server cost summaries count assumption-priced requests independently of bounded event retention and duplicate events. Failed upstream attempts and actual billing remain excluded/unknown.
2. **Run clock:** blank `RUN_TIMEZONE` uses **server local**, not forced UTC or browser timezone. An optional IANA value such as `Asia/Seoul` converts the one captured aware run instant; the configured IANA name is retained in provenance. Every role/repair/revision keeps this run context. Source dates are not rewritten. Project `tzdata` supplies Windows IANA data without changing OS settings. Invalid configuration fails safely.
3. **Gateway timeouts:** real app lifespan logs safe actionable warnings when gateway observation is enabled without a known router budget, when request deadline is not greater than explicit `LLM_GATEWAY_ROUTER_TIMEOUT`, or when a role can preempt a request. Bundled `gateway/app.env.example` declares125s router and130s client. Unknown/custom proxies are **not** assumed to use125s. Warnings direct operators to review the example and align budgets; no budget, timeout, cost cap or key is automatically changed.
4. **Timeline recovery:** optional `include_events=true` snapshot response captures the latest state and retained server events without yielding between them. Existing bounded server log (default160) remains process-local; history is never nested into event snapshots. UI merges by run/sequence ID, sorts and keeps at most150 events; SSE resumes after the accepted snapshot cursor. Stale/duplicate delivery cannot duplicate rows or costs. Active, completed and reconnect paths restore served-model/fallback/tokens/latency. Evicted history is explicitly incomplete, not fabricated or durable. Browser storage still contains only the run ID.
5. **Researcher prompt:** encourages useful independent batches of at most three calls, bounded by remaining shared search/read allowances and existing role tool-call cap. Dependent search→read calls must wait for returned registered IDs. No dispatcher, budgets or concurrency settings changed; **no measured latency improvement is claimed**.

### Deferred proposal only (item 6)

Role-specific model aliases could be considered in a separate change after choosing role→alias mappings, fallback policy, token rates, quality criteria and cost limits. Such routing changes affect quality, latency and cost. This PR adds no role routing, model override, extra deployment or role-specific alias setting. Existing single configured model / gateway primary-secondary behavior is preserved.

## Pinned usage contract and test evidence

Inspected installed `langchain-openai1.6.6` `BaseChatOpenAI._create_chat_result` and `openai3.20.0`: the adapter retains response usage in `response_metadata.token_usage`; SDK model serialization adds nullable detail fields but does not reconcile total/input/output. The new HTTP `MockTransport` tests verify counts and explicit reasoning details through the actual adapter with both policies. The actual pinned LiteLLM proxy is exercised with local mock upstream reasoning-in-output and residual responses under both policies. These are **offline protocol tests**, not proof of Gemini's live OpenAI-compatible endpoint usage or real billing.

Directly checked implementation environment: macOS14.7 (23H124), arm64, Python3.12.13, Node22.22.0, Docker Engine28.0.4, Compose2.34.0-desktop.1. `uv.lock` pins the new project dependency `tzdata2026.4`. A subprocess with `zoneinfo.reset_tzpath([])` verifies IANA loading without an OS zoneinfo database; this is not Windows execution.

| Command | Result |
|---|---|
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short` | **615 passed in219.50s**, no skips; **19 actual proxy/mock tests** |
| `npm --prefix frontend test` | **101 passed**,7 files,12.59s |
| `npm --prefix frontend run typecheck` | exit0 |
| `npm --prefix frontend run build` | exit0,36 modules |
| `git diff --check` | exit0 |

Regression coverage includes KST00:01/08:59 versus previous UTC date, New York spring DST transition, stable all-role/revision context, source-date preservation, invalid config, dependency-supplied timezone data, default local clock, startup warnings without secrets, residual pricing and reasoning separation, served-rate selection, bounded snapshot restore, server cost dedup/eviction, client restore/reconnect/SSE overlap and150-entry bound.

### Browser execution

`frontend/qa/windows-reload-browser.js` ran against the production build on isolated loopback5201. Actual interactions: start, open activity details, reload while active, duplicate SSE replay, terminal delivery, reload again. Restored served secondary, fallback badge, input100/output50/total170,123ms latency, residual assumption and input/output-only subtotal remained visible; the authoritative partial run cost did not change. Layout/metrics checked at1440/768/390px with no horizontal overflow and no page errors. Desktop/mobile full-page screenshots were visually inspected; metrics wrap inside the internally scrollable timeline. This uses mocked browser API/SSE fixtures, not a live browser-to-provider execution. API/proxy tests separately verify backend contracts. Screenshots are local QA outputs `/tmp/ras-windows-reload-{1440,768,390}.png`.

### Failures corrected, not hidden

- Initial test collection used reserved pytest parameter `request`; renamed it before the required red run. New backend regressions then **25 failed** for missing settings, subtotal, clock conversion, startup warning and history. Focused implementation run then **80 passed**.
- New aggregate-assumption test failed before implementation (**1 failed /9 passed**). New UI restoration/merge cases failed before implementation (**4 failed**).
- First frontend full run was **99 passed /1 failed**: existing request-URL expectation omitted the newly explicit `include_events=true`; corrected that contract expectation. Final101-pass run includes the later SSE overlap regression.
- First full actual-proxy suite was **607 passed /2 failed**: the observation-field allowlist needed the two new public cost fields, and a legacy test asserted the old UTC default. Updated expectations to the approved contracts without weakening the safety allowlist.
- Initial raw-wire test asserted whole SDK usage-dict identity and failed3 cases because the pinned SDK adds null detail fields. Source inspection confirmed the behavior; tests now check exact count/detail values rather than falsely claiming byte-identical objects.
- Browser script file loading initially failed the tool's allowed-root restriction; copied the exact QA script into its permitted output root, then the real browser run passed. No browser failure was represented as success.

Task cleanup read-back: browser closed with no tabs; isolated HTTP server terminated and port5201 has no listener; no `ras-gateway` task containers/networks remain. Cached pinned Docker image is retained. No operator `.env` was read, credentials changed, paid/live model/search call made, or current Windows execution performed. Independent review is required before merge.
