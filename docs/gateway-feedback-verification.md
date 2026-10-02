# Gateway runtime-feedback verification

Base: `492d12612205b87280b2b2ec4cfacc2938efce84`. This report covers the Issue #26 follow-up, not the original gateway implementation. No live models, operator secrets or Windows environment were used. User-reported Windows/live results are attributed separately in [gateway.md](gateway.md).

Environment directly checked: macOS 14.7 (23H124), arm64, Python 3.12.13, Node 22.22.0, Docker Engine 28.0.4, Compose 2.34.0-desktop.1.

## Verified contracts and design

- Inspected the pinned image package source, not guessed header meanings: `router.py:9342–9349` retains explicit `model_info.id`; `proxy/common_request_processing.py:1692–1698` emits the selected model ID. Actual HTTP tests confirm primary ID, explicitly requested secondary ID, and secondary ID after 401/429/503 fallback. Body `model` differs by path (public alias versus mock upstream name), so it is not routing evidence.
- Public `served_by` uses only the two bundled explicit deployment IDs and requires opt-in. Unknown/custom IDs and direct connections stay unknown. It identifies the public alias, not a private upstream name. No admin model-info endpoint or secrets-derived hash mapping is used.
- Inspected additional pinned header implementations: `common_request_processing.py:1692–1698,2313–2330` emits deployment model names; `router_utils/add_retry_fallback_headers.py:295–309` records attempted fallback count; `router.py:11134,11140–11164` supplies remaining requests. Actual fresh-stack responses prove `openai/mock-primary / 0 / 29` and `openai/mock-secondary / 1 / 29`. Names are exposed only after an exact served-alias public-name allowlist match. Missing/untrusted fields remain unknown; remaining requests is not account balance.
- Added authoritative per-run cost summary, deduped by model call ID rather than browser events. Unknown/pending/failed calls keep the total unknown and expose only the known subtotal. Normal/fallback real-proxy graph tests exercise different explicit synthetic deployment prices; fixture runs have no cost summary. No real prices are assumed.
- Inspected native Gemini usage transformation at `llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py:1884–1919`: explicit thoughts are placed in details and conditionally included in completion tokens. This is not proof of a user's OpenAI-compatible endpoint semantics. Explicit reasoning and unexplained residual are separate; estimates never add reasoning twice.
- Operator config allows 60s per upstream, Router125s; host profile130s request,270s simple roles,600s Researcher,1800s run. Direct-mode defaults unchanged. Failure tests derive a temporary1s/3s config; operator test exercises a12s primary with no fallback.
- Price config is empty by default. A served-alias two-rate estimate requires both counts, explicit rates, and zero residual. Actual billing and failed-attempt cost stay unknown.

## Execution evidence

Baseline before edits: full Python + real Docker proxy suite **492 passed in156.55s**; frontend **74 passed**. TDD:31 new feedback cases failed for missing settings/metrics and10s timeout; then38 focused feedback/legacy-observation cases passed. Real graph tests failed2 routing assertions before wiring settings/observations; frontend failed4 routing display assertions before implementation. Explicit usage-detail proxy tests failed 2 assertions before adding the mock detail scenarios. Additional missing-total cases failed 2 assertions before preserving explicit reasoning details independently; all 32 feedback cases then passed. The expanded header/run-cost tests then failed for missing fields/summary; the frontend metric assertions failed before their components were added. Final tests include invalid/overflow prices, unknown/zero/partial totals, duplicate call IDs, bounded event retention, terminal replay, restore and reconnect.

| Command | Observed result |
|---|---|
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short` | **548 passed in 183.88s**, no skips, includes **17 real proxy/mock tests** |
| `npm --prefix frontend test` | **88 passed**, 6 files, 9.56s |
| `npm --prefix frontend run typecheck` | exit 0 |
| `npm --prefix frontend run build` | exit 0, 36 modules |
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -k "real_rpm or proxy_logs" -q --tb=short` | **2 passed**, 12 deselected in 51.46s (before the two usage cases were added) |
| `git diff --check` | exit 0 |

Post-regression Docker read-back: no containers or networks matching `ras-gateway`. The pinned image remains reusable. Task browser closed; isolated HTTP server terminated and port 5199 confirmed without a listener.

Browser fixture QA: `frontend/qa/gateway-browser.js`, production build served on isolated loopback5199. Actual browser interactions open the run and activity disclosure; mock SSE supplies known-primary/secondary-fallback/unknown observations. At1440/768/390px all three routing labels, fallback badge, public model names, latency, token/reasoning/residual metrics and partial cost summary visible with no horizontal page overflow. A later event preserves measured scrollY. No page errors. This is frontend fixture QA, not a live provider/browser-to-proxy test. Backend proxy/graph tests independently verify emitted observations. Desktop timeline and mobile cost-summary screenshots were visually inspected and retained outside the repo in the task QA output directory. Metrics fit; the timeline remains an internally scrollable feed.

## Failures corrected and boundaries

- A Docker restart reassigned the ephemeral published port; stale health URLs caused a test timeout. The harness now re-reads the port after restart. The timed-out test project was explicitly removed before rerunning; no failure was called success.
- The old event-field regression allowlist needed the new `observation` envelope; its nested keys are now checked explicitly, with unknown direct-mode routing.
- Browser QA first used obsolete button text and an unscoped duplicate text locator; selectors now target the real accessible name and timeline. The final actual browser run passed.
- RPM test resets the proxy process and proves exactly30 accepted,31st rejected without upstream arrival. Log-redaction test creates its own primary failure/fallback even when selected independently.
- Pinned image availability is a hard preflight failure with an exact pull command, not a silent skip. Normal non-opt-in pytest skips are not gateway verification.

## Independent-review RPM regression and re-verification

The independent review of `23f5733d62938ad37ff12bf669e4be308cc92994` ran the full suite and observed **547 passed, 1 failed**: request31 returned200 instead of429. The isolated RPM test passed. Preserve that failure alongside the earlier548-pass run above; the earlier run did not establish boundary safety. Minute rollover was supported by source inspection, but timestamps were not captured during the original failing review, so it is not a directly measured cause of that failure.

Re-inspected the pinned image's installed source: `router.py:8060,8230,10983` and `router_strategy/lowest_tpm_rpm_v2.py:75,153,234,272,430,547` use `get_utc_datetime().strftime("%H-%M")` for fixed-minute counters, not a rolling60-second interval. The inspection container had `--network none` and was removed automatically; package import attempted a model-price metadata fetch, which failed with DNS unavailable and used its bundled fallback. No live provider request was made.

The test-only fix reads UTC timestamps **inside the gateway container** before and after each burst. Each measurement restarts the proxy, refreshes its published port, resets mock history, and waits until the first10seconds of a minute. It accepts evidence only when both timestamps are in the same UTC minute. At most one retry is allowed, only after an observed forward minute crossing, with fresh counters again. Early429, unexpected statuses, an upstream arrival for429, backwards time, and same-window threshold mismatches fail rather than retry. Waiting and rollover retries are bounded; there is no skip or eventual429 relaxation.

Six deterministic helper regressions first failed against the unimplemented helper (**6 failed in0.04s**), then passed: early-window waiting, returning a same-window all200 result without retry, observed rollover/reset, exhausted rollover budget, immediate burst failure, bounded waiting, and backwards-clock rejection (waiting/result checks share one test).

| Re-verification command | Observed result |
|---|---|
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway/test_rpm_window.py tests/gateway/test_proxy.py -k 'rpm or window' -q --tb=short -s` | **7 passed,16 deselected in44.85s** |
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short` | **554 passed in218.31s**, no skips |

The focused real-proxy run directly observed gateway UTC `2026-10-02T06:12:01.450272+00:00` through `2026-10-02T06:12:03.859548+00:00`: exactly30 responses200, request31 response429, and exactly30 upstream arrivals, all within one accounting minute. No rollover retry was needed in that measured run. These timestamps are observed test evidence, not a correction to other workflow dates. Frontend and application code are unchanged; frontend checks were not rerun for this test-only fix. Post-suite Docker read-back (`docker ps -a --filter name=ras-gateway` and `docker network ls --filter name=ras-gateway`) found no task containers or networks; `git diff --check` passed.

No paid calls, model-quality evaluation, real cost verification, current Windows/amd64 validation, host infrastructure changes or merge are included. Independent re-review remains required.
