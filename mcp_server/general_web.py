"""Run-local, opt-in Exa search/contents store for explicit MCP registration.

Contract references: https://exa.ai/docs/reference/search,
https://exa.ai/docs/reference/get-contents, /contents/quickstart, /admin/pricing.
Bearer auth, POST JSON, contents uses ids + top-level text.maxCharacters.
Summary is object|null (NOT false); null disables it. No generated synthesis,
agent/deep endpoints, SDK, retries, fallback provider, or account management.

Instantiate once per run with an explicitly supplied server-side key. Keep the
same object across revisions. Await search, read and close on the owning event loop.
web_search returns metadata ONLY; read_page returns citation-shaped evidence.
validate_evidence checks exact content against this store's successful read cache.
Call close at run teardown. No env reads, global credentials or persistence.

Default hard ceilings: 6 searches, 8 reads, 5 results/search, 1000 query chars,
12000 page chars, 256 KiB JSON responses, 15s HTTP operation timeout. Failure
results are cached; quota/auth latch off ALL new requests in this store. Caps
can only be lowered. These are request caps, NOT a free-balance guarantee:
free-credit/no-auto-recharge enforcement belongs to the operator's Exa account.

Source URLs are syntactically public, never resolved or fetched locally. Exa
extracts text remotely; contents URLs must exactly match registered search URLs.
This intentionally rejects canonical URL changes rather than trusting redirects.
Extracted text remains untrusted data, not instructions or independent truth.
"""
from copy import deepcopy
from datetime import datetime
import ipaddress
import json
import re
import secrets
import asyncio
from urllib.parse import unquote, urlsplit

import httpx

MAX_RESPONSE_BYTES = 262144
MAX_TEXT_CHARS = 12000
REQUEST_TIMEOUT = 15.0
SOURCE_ID_PATTERN = r"gw_[a-f0-9]{32}"
_CATEGORIES = frozenset({"invalid_input", "unavailable", "quota", "auth", "timeout", "security", "oversize", "budget"})


class GeneralWebError(RuntimeError):
    """Closed category and fixed message; never carries upstream error payloads."""

    def __init__(self, category):
        self.category = category if category in _CATEGORIES else "unavailable"
        super().__init__("General web retrieval: " + self.category)


def _public_url(value):
    """Conservative syntactic allowlist; not a DNS/SSRF resolver."""
    if type(value) is not str or not 1 <= len(value) <= 2048:
        return False
    decoded = unquote(value)
    if any(ord(c) <= 32 or ord(c) == 127 for c in decoded) or "\\" in decoded:
        return False
    try:
        p = urlsplit(value)
        host = p.hostname
        if (p.scheme not in {"https", "http"} or not host or p.username is not None
                or p.password is not None or p.fragment or p.port not in {None, 80, 443}):
            return False
        if host.endswith(".") or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            # Reject alternate numeric IP formats and single-label/private names.
            labels = host.split(".")
            return (len(labels) > 1 and re.fullmatch(r"[a-zA-Z]{2,63}", labels[-1]) is not None
                    and all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in labels))
    except ValueError:
        return False


def _date(value):
    if value is None:
        return None
    if type(value) is not str or len(value) > 40:
        raise GeneralWebError("unavailable")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GeneralWebError("unavailable") from None
    return value


class GeneralWebStore:
    """Bounded async run-local provider/registry, with single-flight caching."""

    def __init__(self, *, api_key=None, transport=None, search_limit=6, read_limit=8):
        if (type(search_limit) is not int or not 0 <= search_limit <= 6
                or type(read_limit) is not int or not 0 <= read_limit <= 8):
            raise GeneralWebError("invalid_input")
        self._key = api_key.strip() if type(api_key) is str else ""
        self._limits = {"search": search_limit, "contents": read_limit}
        self._counts = {"search": 0, "contents": 0}
        self._lock = asyncio.Lock()
        self._searches = {}
        self._pages = {}
        self._sources = {}
        self._urls = {}
        self._blocked = None
        self._closed = False
        self._client = httpx.AsyncClient(transport=transport, trust_env=False,
                                  follow_redirects=False, timeout=REQUEST_TIMEOUT)

    async def close(self):
        async with self._lock:
            self._closed = True
            await self._client.aclose()

    @staticmethod
    def _cached(value):
        if isinstance(value, str):
            raise GeneralWebError(value)
        return deepcopy(value)

    async def _request(self, operation, payload):
        if self._closed or not self._key:
            raise GeneralWebError("unavailable")
        if self._blocked:
            raise GeneralWebError(self._blocked)
        if self._counts[operation] >= self._limits[operation]:
            raise GeneralWebError("budget")
        self._counts[operation] += 1
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT), self._client.stream("POST", "https://api.exa.ai/" + operation,
                                     headers={"Authorization": "Bearer " + self._key,
                                              "Accept": "application/json", "Accept-Encoding": "identity"},
                                     json=payload) as response:
                status = response.status_code
                if status in {401, 403, 402, 429}:
                    self._blocked = "auth" if status in {401, 403} else "quota"
                    raise GeneralWebError(self._blocked)
                if 300 <= status < 400:
                    raise GeneralWebError("security")
                if status != 200:
                    raise GeneralWebError("unavailable")
                # Enforce identity before iter_bytes can expand a compressed bomb.
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise GeneralWebError("security")
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise GeneralWebError("oversize")
                    raw.extend(chunk)
                data = json.loads(raw)
                if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                    raise GeneralWebError("unavailable")
                return data
        except (TimeoutError, httpx.TimeoutException):
            raise GeneralWebError("timeout") from None
        except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
            raise GeneralWebError("unavailable") from None

    def _no_secret(self, value):
        if self._key and self._key in value:
            raise GeneralWebError("security")

    def _metadata(self, item):
        if not isinstance(item, dict):
            raise GeneralWebError("unavailable")
        url, title = item.get("url"), item.get("title")
        if isinstance(url, str):
            self._no_secret(url)
        if not _public_url(url):
            return None
        if type(title) is not str or not title.strip() or len(title) > 500:
            raise GeneralWebError("unavailable")
        self._no_secret(title)
        date = _date(item.get("publishedDate"))
        return {"url": url, "title": title.strip(), "published_at": date}

    async def web_search(self, query, limit=5):
        """Only query:str and limit:int; provider options cannot be supplied."""
        if (type(query) is not str or not query.strip() or len(query) > 1000
                or any(ord(c) < 32 or ord(c) == 127 for c in query)
                or type(limit) is not int or not 1 <= limit <= 5):
            raise GeneralWebError("invalid_input")
        self._no_secret(query)
        cache_key = (query, limit)
        async with self._lock:
            if cache_key in self._searches:
                return self._cached(self._searches[cache_key])
            try:
                data = await self._request("search", {"query": query, "type": "auto", "numResults": limit,
                                                "contents": {"text": False, "highlights": False, "summary": None}})
                if len(data["results"]) > limit:
                    raise GeneralWebError("oversize")
                # Validate the entire batch before adding anything to the registry.
                metadata = [self._metadata(item) for item in data["results"]]
                found = []
                seen = set()
                for m in metadata:
                    if m is None or m["url"] in seen:
                        continue
                    seen.add(m["url"])
                    sid = self._urls.get(m["url"])
                    if sid is None:
                        sid = "gw_" + secrets.token_hex(16)
                        self._sources[sid] = {**m, "source_id": sid, "retrieval_status": "metadata_only"}
                        self._urls[m["url"]] = sid
                    found.append(self._sources[sid])
                self._searches[cache_key] = deepcopy(found)
            except GeneralWebError as exc:
                # Don't let unlimited rejected calls grow the cache beyond the cap.
                if len(self._searches) < self._limits["search"]:
                    self._searches[cache_key] = exc.category
                raise
            return deepcopy(found)

    async def read_page(self, source_id):
        """Read one known opaque ID via Exa only, never an arbitrary URL."""
        if type(source_id) is not str or not re.fullmatch(SOURCE_ID_PATTERN, source_id):
            raise GeneralWebError("invalid_input")
        async with self._lock:
            if source_id not in self._sources:
                raise GeneralWebError("invalid_input")
            if source_id in self._pages:
                return self._cached(self._pages[source_id])
            try:
                source = self._sources[source_id]
                url = source["url"]
                data = await self._request("contents", {"ids": [url], "text": {"maxCharacters": MAX_TEXT_CHARS},
                                                  "highlights": False, "summary": None, "subpages": 0,
                                                  "livecrawlTimeout": 8000})
                statuses = data.get("statuses")
                if statuses is not None and (not isinstance(statuses, list) or len(statuses) != 1
                        or not isinstance(statuses[0], dict) or statuses[0].get("id") != url
                        or statuses[0].get("status") != "success"):
                    raise GeneralWebError("unavailable")
                if len(data["results"]) != 1:
                    raise GeneralWebError("unavailable")
                item = data["results"][0]
                metadata = self._metadata(item)
                if metadata is None or metadata["url"] != url:
                    raise GeneralWebError("security")
                text = item.get("text")
                if type(text) is not str or not text.strip():
                    raise GeneralWebError("unavailable")
                if len(text) > MAX_TEXT_CHARS:
                    raise GeneralWebError("oversize")
                self._no_secret(text)
                if re.search(r"<(?:!doctype|html|body|script|iframe)\b", text, re.I) or "\x00" in text:
                    raise GeneralWebError("unavailable")
                evidence = {**metadata, "id": source_id + ":page", "document_id": source_id,
                            "section_id": "page", "as_of": None, "excerpt": text.strip(),
                            "provenance": "exa_contents"}
                self._pages[source_id] = evidence
            except GeneralWebError as exc:
                if len(self._pages) < self._limits["contents"]:
                    self._pages[source_id] = exc.category
                raise
            return deepcopy(evidence)

    def validate_evidence(self, evidence):
        """Accept only exact successful read output from this run, not metadata."""
        if type(evidence) is not dict or type(evidence.get("document_id")) is not str:
            return False
        # No awaits: registry snapshots are atomic on the owning event loop.
        original = self._pages.get(evidence["document_id"])
        return isinstance(original, dict) and original == evidence
