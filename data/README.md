# Bundled historical dataset

`apple_fy2024.json` contains five original, short Korean factual summaries, not full source documents or copied quotations. Public accessibility is not treated as a republication license. Source copyright remains with its owners; the project redistributes only its independently written summaries and bibliographic metadata. No affiliation with Apple is implied.

- Financial period / UI data basis: **2024-09-28**.
- Sources published: earnings release and financial statements **2024-10-31**, Form 10-K **2024-11-01**.
- Source acquisition / verification: **2026-09-29**. Acquisition date does not make these current figures.
- [Apple Q4 release](https://www.apple.com/newsroom/2024/10/apple-reports-fourth-quarter-results/): quarterly revenue, GAAP/non-GAAP EPS and forward-looking risk disclosure.
- [Accompanying financial statements](https://www.apple.com/newsroom/pdfs/fy2024-q4/FY24_Q4_Consolidated_Financial_Statements.pdf): twelve-month net sales, net income and services revenue, in USD millions.
- [FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm), Item 1A, pp. 7–8: manufacturing and logistics outsourcing risk.

IDs identify our summary sections, not original filing paragraph IDs. `excerpt` is an original factual summary, **not a verbatim quotation**. Financial figures are historical, risk disclosures are possibilities rather than predictions, and this small corpus is neither exhaustive research nor investment advice. Annual and quarterly values and GAAP/non-GAAP values must be distinguished. With public sources disabled (the default), runtime tools read only this allowlisted bundle.

## Optional official Apple public documents

Set `RESEARCH_PUBLIC_SOURCES=1` explicitly to discover and retrieve three additional sections through the same `search_documents` / `get_section` MCP tools. No LLM key, paid API, generic web search, crawler, user URL, or path argument is involved. The optional extension does **not** fetch SEC pages or expand the approved historical period.

| Document ID | Section ID | Source location |
|---|---|---|
| `apple-official-fy2024-q4` | `operations` | Apple financial statements PDF, page 1: sales, cost of sales, gross margin, net income |
| `apple-official-fy2024-q4` | `product-revenue` | Same PDF, page 1: net sales by category |
| `apple-official-q4-2024-newsroom` | `results` | Apple newsroom release, opening results paragraph |

Both exact source URLs are linked above and hardcoded in `mcp_server/public_sources.py`. Publication is **2024-10-31**, financial period end **2024-09-28**. Section IDs are application-defined; `source_locator` identifies the original location. PDF columns retain both quarterly and annual comparisons, in USD millions. Gross margin in the statements is a **dollar amount**, not a percentage.

Search returns catalog metadata marked `retrieval_status=not_fetched`, never fetched evidence. `get_section` downloads only the selected exact document, then returns a bounded factual extraction with `retrieved_at`, original-byte `source_sha256`, `source_bytes`, publication date, and original source URL. The newsroom excerpt is a short source paragraph; PDF excerpts are selected factual rows reformatted with explicit column labels. These differ from the independently authored bundled summaries.

### Bounds and prerequisites

- Opt-in is exactly `1`; other values do not enable network access.
- Two exact documents / three sections; at most **two HTTP attempts per MCP session**, one per document. Successes and failures are cached for that process lifetime. No refresh, retries, persistent source cache, or background updates.
- Redirects disabled; proxies/environment HTTP configuration ignored; TLS verification enabled; GET only. Compressed responses are rejected to avoid decompression expansion.
- **6 MiB per source**, including streams without Content-Length; HTTP total deadline **6 seconds**, per-operation timeout **2 seconds**.
- PDF extraction requires **Poppler `pdftotext`**, on the backend's PATH or selected by trusted operator setting `RESEARCH_PDFTOTEXT`. The client forwards only its resolved executable path to the sanitized child environment. Tool callers cannot select an executable or local file.
- Parser deadline **2 seconds**, output cap **32 KiB**, page 1 only. Temporary PDF bytes are deleted. Only the three small extracted sections remain in memory.
- HTTP denials, redirects, rate limits, timeouts, size limits, unsupported content, missing parser, or changed document layout fail explicitly; they never become fabricated values or empty search results. Ordinary availability failures produce a typed unavailable result, retained as a report limitation if other evidence exists. Security-bound violations stay fatal. A new MCP session is required to retry.
- No full scraped page/PDF is committed or persistently cached. Public accessibility is not a republication license; original copyright remains with Apple. This is an independent prototype, not an Apple service.

### Verification

Offline tests: `.venv/bin/python -m pytest tests/test_public_sources.py -q` (HTTP mocks, no external verification).

Optional actual-source smoke, using real MCP stdio and no LLM/provider call:

```sh
RESEARCH_PUBLIC_SOURCES=1 .venv/bin/python -m mcp_server.smoke_public_sources
```

See `public_source_smoke.md` for observed live-source evidence. Availability at that observation does not guarantee future access.
