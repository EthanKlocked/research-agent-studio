# Verification scope

## Executed on macOS

- Locked Python install and clean npm install; TypeScript check and production build passed.
- Python suite: 45 passing tests: 34 core backend tests plus 11 static PowerShell-launcher contract tests. Core tests include actual LangGraph/LangChain execution and real MCP stdio initialization, discovery, search and section retrieval.
- Frontend suite: 27 passing tests covering snapshots, streaming, reconnect, terminal lifecycle, revision selection, safe tool summaries and live-mode request selection.
- Browser checks at 1440×900 and 1366×768, plus 390px mobile: revise → retained evidence → second report; source links; revision comparison; page reload; pass/limit/empty/tool-error states and cancellation.
- Three browser-triggered cancellations finalized as cancelled with finish timestamps and no errors. No horizontal mobile overflow or browser console errors observed.
- Source/build secret-pattern inspection and npm audit (zero reported vulnerabilities). Neither is a comprehensive security guarantee.

Backend coverage includes malformed citations/evaluation schemas, timeouts, concurrency/input/retention limits, run isolation, SSE ordering, bounded tool permissions, startup/cleanup cancellation and subprocess exit. Model responses are deterministic fixtures or isolated HTTP mocks: **none of this verifies a live provider**.

## Windows boundary

PowerShell launchers mirror the install/start/test commands, check native exit codes and restore caller location/environment. Static contract tests do not prove PowerShell parsing or Windows process behavior. Windows installation, MCP subprocess lifecycle and browser use remain unverified until exercised on a Windows machine. macOS Bash is the verified runtime path.

## Live verification remaining

After operator-local settings, verify provider authentication, model tool calls and JSON output, claim/evidence agreement, natural revise behavior and provider cancellation behavior. The real workflow may pass on its first evaluation. Explicit test scenarios must not be represented as real model judgment.

The corpus is small and historical, not live web research. Run state is in memory only. This is a loopback single-user prototype, not an internet-facing service.

## Screenshots

- [Initial screen](idle-1440.png)
- [Completed report](result-1440.png)
- [1366px report](result-1366.png)
- [Selected evidence](evidence-1366.png)
- [Cancelled run](cancelled-1440.png)
