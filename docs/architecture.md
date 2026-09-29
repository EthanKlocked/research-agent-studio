# Architecture

## Workflow

```text
Listener → Planner → Researcher → Reporter → Evaluator
              ↑                                 │
              └──── revise, within budget ──────┘
```

FastAPI serves the built React client and JSON/SSE endpoints on one loopback origin. Each role is a LangChain agent invoked by a LangGraph node. Only Researcher receives the read-only MCP tools. A local stdio subprocess provides bounded search and section retrieval from the bundled historical dataset. No remote MCP port or arbitrary fetch/shell tool is exposed.

## State and validation

Per-run shared state includes request interpretation, plan, deduplicated evidence, report revisions, evaluation, feedback, iteration, errors and lifecycle fields. Each role gets a fresh inner message history; validated public JSON outputs map back into shared state. Plain JSON objects and one enclosing JSON/unlabelled code fence are accepted; prose extraction, automatic repair and content-block lists are not. Provider-native structured output is not forced across unknown compatible servers. Prior evidence and evaluation feedback survive replanning. Citation IDs must refer to retrieved evidence; existence is not proof of semantic truth.

Evaluator outcomes can appear before workflow cleanup. A final lifecycle snapshot with `finished_at`, or an explicit terminal event, determines completed UI state. Cancellation records intent before signalling the actual task and publishes one terminal event after cleanup. Provider-side immediate cancellation is not guaranteed.

## Observation API

- `GET /api/config`: safe configured/missing status, historical dataset date, limits.
- `POST /api/runs`: explicit question, test/live mode and test scenario.
- `GET /api/runs/{run_id}`: current snapshot.
- `GET /api/runs/{run_id}/events?after=N`: ordered normal SSE messages with sequence, run ID, timestamp, event type and full safe snapshot.
- `POST /api/runs/{run_id}/cancel`: actual task cancellation.

Node start/completion, tool start/completion/input-error, evaluation, branch and terminal events drive the client. Locally validated input/section-ID errors return a fixed structured ToolMessage through LangChain middleware. Every attempt shares the call budget; at most two errors permit correction. A subsequent successful section retrieval clears unresolved error state. Search alone does not. Forbidden tools, exhausted budgets and remote/protocol failures remain fatal. MCP calls are serialized within a research node so an older concurrent retrieval cannot clear a newer input failure. Tool summaries expose bounded search lengths/result limits and allowlisted section IDs, not arbitrary raw arguments. The UI shows explicit plans and evaluation reasons, never hidden reasoning or raw provider prompts/configuration.

The client deduplicates events, isolates runs, and reads a snapshot before reconnecting. It keeps only the run ID in sessionStorage. Memory retention is bounded; restart loses runs. Use one server worker.

## Dependencies

Python 3.12; LangChain 1.4.3, LangChain Core 1.6.5, LangChain OpenAI 1.6.6, LangGraph 1.2.12, MCP SDK 1.30.0, FastAPI 0.141.1, Uvicorn 0.54.0. Lockfiles are authoritative for all transitive versions.

API references: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents), [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api), [MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/).
