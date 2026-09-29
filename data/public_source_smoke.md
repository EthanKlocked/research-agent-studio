# Live public-source smoke evidence

Command actually executed successfully:

```sh
RESEARCH_PUBLIC_SOURCES=1 .venv/bin/python -m mcp_server.smoke_public_sources
```

This is **actual Apple HTTP through real MCP stdio**, not mocked upstream data, and not a live LLM/provider test. No model key or model call was used. The tools listed were exactly `search_documents` and `get_section`; search discovered the new catalog sections, then `get_section` fetched and parsed the two allowlisted sources. Repeating the operations section returned an identical cached value, and both PDF sections shared their retrieval timestamp and original-byte hash.

| Source | Retrieved at (UTC) | HTTP body bytes | Original-byte SHA-256 |
|---|---|---:|---|
| [Apple financial statements PDF](https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf) | 2026-09-29T07:03:34.657735+00:00 | 4,919,216 | `af9646018330484238d357f1168ae74194fd768f4ea9921e4b2828c88309320c` |
| [Apple results newsroom HTML](https://www.apple.com/newsroom/2024/10/apple-reports-fourth-quarter-results/) | 2026-09-29T07:03:34.785259+00:00 | 139,831 | `e93362b442be85ed43030d9817e422c962814fff1510762df926b3f5cf06bccd` |

Initial direct HTTP inspection returned **200** for both URLs with redirects disabled (`application/pdf` and `text/html;charset=utf-8` respectively). The subsequent implementation's smoke also requires HTTP 200 and rejects redirects. PDF extraction used the installed Poppler `pdftotext` executable; no new Python dependency was installed.

Assertions against fetched excerpts passed for these FY2024 Q4 values, in **USD millions**:

- Net income: **14,736** (comparative FY2023 Q4: **22,956**).
- Gross margin dollar amount: **43,879** (comparative: **40,427**); not a margin percentage.
- iPhone net sales: **46,222** (comparative: **43,805**).
- The opening newsroom paragraph reported **$94.9 billion** quarterly revenue.

Publication metadata is **2024-10-31**; reporting period end is **2024-09-28**. Neither the fetch timestamp nor these historical figures represents current financial results. Only metadata and minimal factual observations are retained here; full source pages/PDFs were not saved to the repository.

A first live MCP attempt exposed FastMCP executing synchronous handlers on its running event loop. An offline regression reproduced the nested-`asyncio.run` failure; the registered get-section tool now dispatches its bounded synchronous store through `asyncio.to_thread`. The successful observation above was made **after** that fix.

Future access is not guaranteed. Default required tests stay offline using explicit HTTP/parser fixtures; their passing status is separate from this live-source evidence.
