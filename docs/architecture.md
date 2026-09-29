# Architecture

## Workflow

```text
Listener → Planner → Researcher → Reporter → Evaluator
              ↑                                 │
              └──── revise, within budget ──────┘
```

FastAPI serves the built React client and JSON/SSE endpoints on one loopback origin. Each role is a LangChain agent invoked by a LangGraph node. Only Researcher receives the read-only MCP tools. A local stdio subprocess provides bounded search and section retrieval from the bundled historical dataset, optionally extended with two exact Apple official documents. When operator-local `SEARCH_PROVIDER=exa` and `EXA_API_KEY` are set, live runs also discover `web_search` and `read_page` for general public web research. Test mode forces both external-source extensions off and uses fixed offline model responses. No remote MCP port or arbitrary fetch/shell tool is exposed.

## State and validation

Per-run shared state includes request interpretation, plan, deduplicated evidence, report revisions, evaluation, feedback, iteration, errors and lifecycle fields. Each role gets a fresh inner message history; validated public JSON outputs map back into shared state. Plain JSON objects and one enclosing JSON/unlabelled code fence are accepted; prose extraction, automatic field coercion and content-block lists are not. JSON/schema rejection permits one sanitized model repair request within the same role timeout and tool budgets. Provider-native structured output is not forced across unknown compatible servers. Prior evidence and evaluation feedback survive replanning. Optional-source unavailability travels separately from evidence, becomes explicit report limitations, and cannot be cited; zero usable evidence remains an error. Scope-aware prompts distinguish unavailable coverage from missing retrievable evidence. Revision failure restores the last evaluated report/evidence, retains error status and unresolved evaluation, and exposes partial_result for a non-pass UI banner. Citation IDs must refer to retrieved evidence; existence is not proof of semantic truth.

Evaluator outcomes can appear before workflow cleanup. A final lifecycle snapshot with `finished_at`, or an explicit terminal event, determines completed UI state. Cancellation records intent before signalling the actual task and publishes one terminal event after cleanup. Provider-side immediate cancellation is not guaranteed.

## MCP contract ownership

`langchain-mcp-adapters==0.3.2` loads server contracts with `load_mcp_tools(session)` under the discovery deadline before Researcher invocation. The independent client ALLOWED policy rejects extra, missing or duplicate tool names. Server definitions own model-visible names/descriptions/schemas; workflow no longer redeclares tools.

Shared `mcp_server/tool_schemas.py` defines strict argument constraints/defaults; `mcp_server/dataset.py` centralizes dataset loading, IDs and dynamic scope. Separate processes may each load their own dataset copy. The existing raw-call middleware remains the sole execution path through DocumentClient, retaining budgets, lock ordering, recovery, events and result validation. Adapter executable callbacks are not used by this workflow.

## Observation API

- `GET /api/config`: safe model `configured` status, `test_mode_available`, `capabilities: {general_web: boolean, search_provider: "exa" | null}`, dataset name and nullable `as_of`, limits. Capabilities describe configuration, not successful authentication, network availability or credit balance; no credentials are returned.
- `POST /api/runs`: explicit question, test/live mode and test scenario.
- `GET /api/runs/{run_id}`: current snapshot.
- `GET /api/runs/{run_id}/events?after=N`: ordered normal SSE messages with sequence, run ID, timestamp, event type and full safe snapshot.
- `POST /api/runs/{run_id}/cancel`: actual task cancellation.

Node start/completion, discovery start/completion, model start/completion, output validation/repair, tool start/completion/input-error, evaluation, branch and terminal events drive the client. Discovery carries purpose/tool count; model events carry opaque call IDs; validation carries scope and repair attempt where applicable. Model request completion is separate from valid structured output. These are public operation events, not response-token streaming or hidden reasoning. Locally validated input/section-ID errors return a fixed structured ToolMessage through LangChain middleware. Every attempt shares the call budget; at most two errors permit correction. A subsequent successful section retrieval clears unresolved error state. Search alone does not. Forbidden tools, exhausted budgets and remote/protocol failures remain fatal. MCP calls are serialized within a research node so an older concurrent retrieval cannot clear a newer input failure. Tool summaries expose bounded search lengths/result limits and allowlisted section IDs, not arbitrary raw arguments. The UI shows explicit plans and evaluation reasons, never hidden reasoning or raw provider prompts/configuration.

The dashboard separates report, collected sources and revision views, with a bounded chronological timeline and explicit unavailable-source/retained-report states. It derives general web availability from configuration capabilities, never observed tool labels. Offline test mode stays explicit even with Exa configured. Missing/invalid evidence and dataset dates render as unknown; provenance is escaped plain text, not a provider inferred from labels. The client deduplicates events, isolates runs, and reads a snapshot before reconnecting. It keeps only the run ID in sessionStorage. Memory retention is bounded; restart loses runs. Use one server worker.

## Resource and source boundaries

Request, per-role and whole-run deadlines are independently configured (see README). Exception classification traverses bounded groups/causes, prioritizing timeout over tool failures. Only allowlisted class labels—not messages—enter diagnostic chains.

Optional Apple retrieval uses exact document/section IDs, disabled redirects/proxies, bounded bytes and fetch/parser time, and per-session positive/negative cache. Ordinary source unavailability has a typed safe contract; security limits, tool budgets and transport failures stay fatal. PDF extraction uses operator-installed Poppler pdftotext with bounded output and temporary-file cleanup.

## General web evidence and cost boundary

A live run owns one MCP session across discovery, planning and revisions, preserving its opaque web IDs, read cache and request counters until teardown. Planner receives sanitized tool metadata, not executable tools. The model cannot supply a URL to `read_page`: only a registered run-local source ID is accepted. Exa requests use fixed `/search` and `/contents` endpoints; source URLs are validated syntactically as public, not fetched locally. Contents must match the registered URL exactly. Search snippets never become evidence; evidence is validated against immutable successful read snapshots, not merely ID existence. Extracted text remains untrusted.

Exa has hard per-run ceilings of 6 searches and 8 reads, at most 5 results per search, bounded queries/responses/text and cached failures. Authentication/quota failures stop new requests across the store; there is no automatic provider fallback or retry. These limits are separate from per-iteration Researcher call budgets and timeouts. Search and contents are separate cost-bearing operations; model costs are also separate. Local counters cannot verify free credits or enforce account billing. Operators must keep card registration/purchases absent and auto recharge OFF if requiring free-credit-only use; a zero recharge limit can mean unlimited, not disabled.

Questions/evidence go to the configured model; search queries and requested URLs go to Exa. Keys stay server-side and are passed only to the dedicated live MCP child. Test-mode children remain offline. No account management, balance verification or purchase automation is included. See README for local setup and account-side checks.

## Dependencies

Python 3.12; LangChain 1.4.3, LangChain Core 1.6.5, LangChain OpenAI 1.6.6, LangGraph 1.2.12, MCP SDK 1.30.0, FastAPI 0.141.1, Uvicorn 0.54.0. Lockfiles are authoritative for all transitive versions.

API references: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents), [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api), [MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/).
