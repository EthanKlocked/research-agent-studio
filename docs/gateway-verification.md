# LiteLLM gateway verification — 2026-10-02

Implementation revision: `119e2ad8f7c73d77c30997d7749c3f70a56be813` (the tested source tree was committed unchanged). Base: `ed9e76fda38cc32b82ba3e8bb5da8b4f84122818`. Follow-up changes to this report/index are documentation only.

Environment: macOS 14.7 (23H124), arm64, Python 3.12.13, Node 22.22.0, Docker Desktop 4.40.0 / Engine 28.0.4, Compose 2.34.0. Image package version independently read with `importlib.metadata.version('litellm')`: **1.103.2**. Registry manifest lists amd64 and arm64; only arm64 was executed here. Image/digest and operator steps: [gateway guide](gateway.md).

## Commands and observed results

| Command | Result |
|---|---|
| Baseline `uv run --locked --extra dev python -m pytest tests -q` | 468 passed, 61.68s |
| Baseline frontend test / typecheck / build | 74 tests passed; typecheck/build exit 0 |
| `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests/gateway -q --tb=short` | 14 passed, 91.07s |
| Final `RAS_GATEWAY_TEST=1 PYTHON_DOTENV_DISABLED=1 uv run --locked --extra dev python -m pytest tests -q --tb=short` | **492 passed, 153.76s**, no skips |
| `npm --prefix frontend test` | **74 passed**, 5 files, 8.68s |
| `npm --prefix frontend run typecheck` | exit 0 |
| `npm --prefix frontend run build` | exit 0; 35 modules transformed |
| `git diff --check` / staged diff check | exit 0 |
| Added-line static scan | 0 matches for eval/exec, shell=True/os.system, pickle, private handoff wording, credential assignment patterns; not a comprehensive security audit |

Normal pytest without `RAS_GATEWAY_TEST=1` skips Docker tests intentionally; that is not gateway verification. The explicit all-tests command above includes them. Final tests disabled dotenv, used explicit mock keys/endpoints, and made no live model/Exa/public-document calls. Baseline was executed before new code; no actual secret file contents were inspected or copied.

## What was exercised

- A real pinned LiteLLM process inside Docker, a separate local HTTP mock upstream, actual authenticated HTTP chat-completions requests. Missing key: 401. Malformed/non-master key in this no-DB setup: 400. Rejected auth produced zero upstream arrivals.
- Both `research-primary` and `research-secondary`; separate mock upstream model names and upstream authentication. Normal response `model` is the public alias, not necessarily the upstream model name.
- Primary mock 401/429/503 and timeout fallback to secondary. Each failure path asserts exactly two actual upstream arrivals, not just eventual HTTP success. Both upstreams timing out yields 408 with two attempts in less than 25 seconds.
- Real `RunManager` → LangGraph → `RoleRunner`/`AgentFactory` → ChatOpenAI → LiteLLM → mock; real MCP stdio tool discovery/search/section retrieval; JSON/citation validation, Reporter and Evaluator. Normal: seven model events/log records and seven upstream attempts. All-primary-failure run: seven model requests and fourteen upstream attempts. Both graphs finish with evidence and report.
- Correlation of real run IDs, existing opaque model-call IDs and distinct `x-litellm-call-id` response IDs; safe selected-deployment hash. No metadata forwarding or arbitrary client-header forwarding was added.
- Mock response usage 11 input / 7 output / 18 total reaches app logs. Missing usage remains `null` rather than proxy-synthesized zero. Cost fields remain unknown; no real-price/billing verification.
- Actual configured deployment RPM limiter returning 429 before an additional upstream arrival. Counters are one-process memory, not persistent/distributed budgets.
- Whole-run deadline and user cancellation while primary has failed and secondary is pending. Terminal states are error/timeout or cancelled, never success. App termination is bounded in tests; upstream computation/billing cancellation is not promised.
- Operator `gateway/compose.yaml` validated and started with `up -d --wait`, using only temporary host-port/test-network overrides and mock endpoint/key injection. Health and a real completion succeeded. Blank gateway key fails Compose validation.
- Combined stdout/stderr Proxy logs checked for synthetic prompt/error/key markers, and app metadata redaction/unknown fields checked separately. Debug logging is not enabled. This does not prove arbitrary future provider/version logs are safe.
- Direct/fixture and existing graph/MCP/UI regression suites remain green. No workflow schema, evaluator rubric, MCP contract or frontend source changes.

## Failures encountered and corrected

- TDD observation/config tests initially failed three expected assertions; metric visibility without root logging and safe deployment-hash logging each had an additional expected RED before implementation.
- Guessed `-stable` / `main-v...` image tags were absent. The official release's plain `v1.103.2` tag and manifest digest were verified instead.
- Docker Desktop's internal-only test network did not publish host ports. The test harness uses a bridge with explicit local mock endpoints; it is **not** presented as an egress firewall.
- Initial test assumptions expected 401/403 for every wrong key and an upstream name in every successful `model` field. Observed no-DB 400 denial and normal alias normalization were recorded; upstream arrival assertions still prove rejection/routing.
- Proxy log assertions read both stdout and stderr. No fabricated successful output replaced failed runs.

## Remaining gates and limits

Independent review is pending; this report is not approval to bypass it. No independent-review pass or main merge is claimed here. No hosted CI workflow was added; local execution evidence is above.

**Not verified:** current Windows runtime, amd64 execution, live provider credentials, actual model tool/JSON compatibility, report semantic quality, real prices/billing, vLLM/GPU serving, production availability, persistent budgets, distributed enforcement, or immediate provider-side cancellation. No deployment/account/profile/infrastructure settings were changed. No new browser smoke was performed because the UI was unchanged.

Cleanup read-back after final tests: `docker ps -a --filter name=ras-gateway` and `docker network ls --filter name=ras-gateway` returned no task containers/networks. The downloaded pinned image remains reusable. No user browser or unrelated service was stopped.
