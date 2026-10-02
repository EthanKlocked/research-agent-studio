# Gateway runtime-feedback verification

Base: `492d12612205b87280b2b2ec4cfacc2938efce84`. This report covers the Issue #26 follow-up, not the original gateway implementation. No live models, operator secrets or Windows environment were used. User-reported Windows/live results are attributed separately in [gateway.md](gateway.md).

Environment directly checked: macOS 14.7 (23H124), arm64, Python 3.12.13, Node 22.22.0, Docker Engine 28.0.4, Compose 2.34.0-desktop.1.

## Verified contracts and design

- Inspected the pinned image package source, not guessed header meanings: `router.py:9342–9349` retains explicit `model_info.id`; `proxy/common_request_processing.py:1692–1698` emits the selected model ID. Actual HTTP tests confirm primary ID, explicitly requested secondary ID, and secondary ID after 401/429/503 fallback. Body `model` differs by path (public alias versus mock upstream name), so it is not routing evidence.
- Public `served_by` uses only the two bundled explicit deployment IDs and requires opt-in. Unknown/custom IDs and direct connections stay unknown. It identifies the public alias, not a private upstream name. No admin model-info endpoint or secrets-derived hash mapping is used.
- Inspected native Gemini usage transformation at `llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py:1884–1919`: explicit thoughts are placed in details and conditionally included in completion tokens. This is not proof of a user's OpenAI-compatible endpoint semantics. Explicit reasoning and unexplained residual are separate; estimates never add reasoning twice.
- Operator config allows 60s per upstream, Router125s; host profile130s request,270s simple roles,600s Researcher,1800s run. Direct-mode defaults unchanged. Failure tests derive a temporary1s/3s config; operator test exercises a12s primary with no fallback.
- Price config is empty by default. A served-alias two-rate estimate requires both counts, explicit rates, and zero residual. Actual billing and failed-attempt cost stay unknown.

## Execution evidence

Baseline before edits: full Python + real Docker proxy suite **492 passed in156.55s**; frontend **74 passed**. TDD:31 new feedback cases failed for missing settings/metrics and10s timeout; then38 focused feedback/legacy-observation cases passed. Real graph tests failed2 routing assertions before wiring settings/observations; frontend failed4 routing display assertions before implementation. Explicit usage-detail proxy tests failed 2 assertions before adding the mock detail scenarios. Additional missing-total cases failed 2 assertions before preserving explicit reasoning details independently; all 32 feedback cases then passed.

| Command | Observed result |
|---|---|
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short` | **526 passed in 148.61s**, no skips, includes **16 real proxy/mock tests** |
| `npm --prefix frontend test` | **79 passed**, 5 files, 7.32s |
| `npm --prefix frontend run typecheck` | exit 0 |
| `npm --prefix frontend run build` | exit 0, 35 modules |
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -k "real_rpm or proxy_logs" -q --tb=short` | **2 passed**, 12 deselected in 51.46s (before the two usage cases were added) |
| `git diff --check` | exit 0 |

Post-regression Docker read-back: no containers or networks matching `ras-gateway`. The pinned image remains reusable. Task browser closed; isolated HTTP server terminated and port 5199 confirmed without a listener.

Browser fixture QA: `frontend/qa/gateway-browser.js`, production build served on isolated loopback5199. Actual browser interactions open the run and activity disclosure; mock SSE supplies known-primary/secondary-fallback/unknown observations. At1440/768/390px all three labels visible and no horizontal page overflow. A later event preserves measured scrollY. No page errors. This is frontend fixture QA, not a live provider/browser-to-proxy test. Backend proxy/graph tests independently verify emitted observations. Screenshot retained outside the repo in the task QA output directory.

## Failures corrected and boundaries

- A Docker restart reassigned the ephemeral published port; stale health URLs caused a test timeout. The harness now re-reads the port after restart. The timed-out test project was explicitly removed before rerunning; no failure was called success.
- The old event-field regression allowlist needed the new `observation` envelope; its nested keys are now checked explicitly, with unknown direct-mode routing.
- Browser QA first used obsolete button text and an unscoped duplicate text locator; selectors now target the real accessible name and timeline. The final actual browser run passed.
- RPM test resets the proxy process and proves exactly30 accepted,31st rejected without upstream arrival. Log-redaction test creates its own primary failure/fallback even when selected independently.
- Pinned image availability is a hard preflight failure with an exact pull command, not a silent skip. Normal non-opt-in pytest skips are not gateway verification.

No paid calls, model-quality evaluation, real cost verification, current Windows/amd64 validation, host infrastructure changes or merge are included. Independent review remains required.
