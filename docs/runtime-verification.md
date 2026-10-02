# Workflow runtime verification

## Scope and evidence boundary

Issue #28 follows merged gateway PR #27 (`a12edecf11fae4922b938feaca17451c1367090c`). This change covers stable server date/timezone input, recoverable **local per-run Exa** ceilings, safe web error reasons, and a normal unsupported-request terminal outcome. No PostgreSQL, deployment, credential changes, live model/search calls or paid calls were performed.

Verification below ran on macOS arm64. Mock model responses test the real ChatOpenAI wire adapter, LangChain agents, LangGraph routing and real MCP stdio. Injected Exa HTTP transports never contact Exa. These checks prove context delivery and typed routing, **not live-model date reasoning, unsupported-request classification accuracy, evidence semantics or investment suitability**.

## Commands and observed results

```bash
RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

- Python: **583 passed in 189.61s**, no skips, including the existing 17 actual LiteLLM proxy/local mock-upstream tests.
- Frontend: **96 passed**; TypeScript and production build passed.
- Initial test-first runtime checks failed for missing clock/support/budget contracts; UI checks failed for missing terminal labels. The separate no-MCP-startup regression failed before Listener was moved ahead of the general-web session.
- First full Python run: 581 passed / 1 failed (the exact API snapshot-key assertion still described the old contract). Updated that assertion for the three additive fields, then reran the full suite above. No production failure was hidden by removing a test.
- Self-review added a failing regression for generic non-web tool error wording, restored its original message rather than labelling it a web failure, and reran the full suite to the final result above.

## Deterministic acceptance coverage

| Requirement | Exercised behavior |
| --- | --- |
| Stable date/timezone | Fixed 2026-10-02 00:01 +09:00 clock, one capture across all five roles and revisions; each real model wire payload carries the context; same-day publication date and distinct reporting date remain unchanged; naive clock rejected |
| Local search ceiling | Actual MCP store reaches six searches; next request returns typed budget failure to Researcher, not an empty result; existing evidence yields a limited report, zero evidence yields no report; both evaluator pass and revise remain budget-limited |
| Read ceiling on revision | Actual run store with lowered read limit retains first evidence across revision; second unique page is blocked; remaining budget does not reset; report and unresolved evaluation remain visible |
| Bounded retries | A model repeatedly retrying an exhausted read operation still hits the independent Researcher call cap and retains the previous evaluated report as an error, rather than looping or gaining requests |
| Provider failures | quota/auth/timeout/security/oversize/invalid_input/unavailable remain errors with closed categories and fixed reasons; secret query/provider prose is absent from public events; prior cache/latch/transport tests remain green |
| Unsupported request | Validated explicit support enum and required explanation; Listener ends before MCP startup even when general search is enabled; no discovery/retrieval/report/evaluation; API snapshot/SSE terminal preserved |
| Supported/legacy requests | Same topic wording with supported/partial/unknown labels continues to Planner; missing legacy fields remain valid; closed-corpus scope tests and full prior regressions pass |
| UI contract | Unsupported explanation, run clock and budget-limited report/no-report states; stream stays active before terminal; restoration/reconnect; safe budget/quota category labels, no false research-success status |

Relevant suites: `tests/test_runtime_context.py`, `tests/test_runtime_edges.py`, `tests/test_api.py`, existing general-web/scope/cancellation/gateway suites, and frontend App/Timeline tests.

## Browser verification

Production `frontend/dist` was served on isolated `127.0.0.1:5200`. `frontend/qa/runtime-browser.js` injects **browser-only deterministic API/SSE fixtures**, not a real backend research run. At **1440, 768 and 390px**, each of unsupported, budget-without-evidence, budget-with-evidence, and provider-quota failure passed:

- Explicit outcome and UTC run date visible; no successful-research label.
- No premature stream closure; terminal closes the stream.
- Unsupported explanation and insufficient-evidence explanation visible.
- Limited report, Sources tab, source detail and report return exercised by real pointer clicks.
- No horizontal overflow or page errors.

The first browser attempt used a hidden duplicate title locator; it timed out without a product failure. The final script selects the source button and visible blockquote explicitly and passed all viewport/outcome combinations.

Visually inspected browser-only screenshots:

- [Unsupported desktop](runtime-unsupported-desktop.png)
- [Budget-limited mobile](runtime-budget-mobile.png)

Owned browser tab and static server were closed. Port 5200 no longer listened; task proxy containers/networks were absent. Unrelated existing services were not stopped.

## Remaining limitations

- Default server reference is UTC, not an inferred user/browser timezone. Explicit user timezone interpretation is prompted, not separately normalized by a date parser. A long run retains its start date across midnight.
- Remaining budgets are supplied at Researcher invocation and again on budget errors; successful tool replies retain their existing result shapes. Local limits are not a provider balance or free-credit guarantee.
- A budget-limited run ends conservatively even if its Evaluator passes. Its report remains evidence/citation-validated but completeness is not asserted. Other provider/tool failures remain fatal.
- Live model adherence and classification quality require separately authorized evaluation. There was **no current live or Windows execution**.
- Prior Windows gateway evidence remains **user-reported**, unknown SHA: Docker Desktop 4.93, Engine 29.8.1, WSL2, mock 14 pass / live gateway 4 of 4 pass. It is not validation of this revision.
- Independent review remains a merge gate; this implementation does not claim an independent-review pass.
