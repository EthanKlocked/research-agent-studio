"""Offline Exa contract/security tests; never use credentials or a live API."""
import importlib
import json
import asyncio

import httpx
import pytest

URL = "https://example.com/report"
KEY = "fake-unit-test-secret"


def module():
    try:
        return importlib.import_module("mcp_server.general_web")
    except ModuleNotFoundError:
        pytest.fail("isolated general_web module has not been implemented")


def result(**kw):
    return {"id": URL, "url": URL, "title": "Report", "publishedDate": None, **kw}


def store(handler=None, **kwargs):
    calls = []
    def respond(req):
        calls.append(req)
        if handler:
            return handler(req)
        if req.url.path == "/search":
            return httpx.Response(200, json={"results": [result(text="not evidence", summary="not evidence")]})
        return httpx.Response(200, json={"results": [result(text="  Clean extracted page body.  ")], "statuses": [{"id": URL, "status": "success"}]})
    return module().GeneralWebStore(api_key=KEY, transport=httpx.MockTransport(respond), **kwargs), calls


async def test_metadata_then_contents_contract_and_nullable_dates():
    s, calls = store()
    metadata = (await s.web_search('x", "type":"deep", "numResults":100'))
    assert len(metadata) == 1
    m = metadata[0]
    assert "excerpt" not in m and "text" not in m and "summary" not in m and "id" not in m
    assert m["published_at"] is None and m["retrieval_status"] == "metadata_only"
    assert json.loads(calls[0].content) == {"query": 'x", "type":"deep", "numResults":100', "type": "auto", "numResults": 5, "contents": {"text": False, "highlights": False, "summary": None}}
    evidence = (await s.read_page(m["source_id"]))
    assert evidence["excerpt"] == "Clean extracted page body."
    assert evidence["published_at"] is None and evidence["as_of"] is None
    assert evidence["id"] == m["source_id"] + ":page"
    assert evidence["document_id"] == m["source_id"] and evidence["section_id"] == "page"
    assert evidence["provenance"] == "exa_contents"
    assert s.validate_evidence(evidence)
    assert not s.validate_evidence(m)
    assert not s.validate_evidence({**evidence, "excerpt": "invented"})
    assert json.loads(calls[1].content) == {"ids": [URL], "text": {"maxCharacters": 12000}, "highlights": False, "summary": None, "subpages": 0, "livecrawlTimeout": 8000}
    assert [str(c.url) for c in calls] == ["https://api.exa.ai/search", "https://api.exa.ai/contents"]
    assert all(c.headers["authorization"] == "Bearer " + KEY for c in calls)
    (await s.close())


@pytest.mark.parametrize("query,limit", [(None, 5), ({"query": "x"}, 5), (" ", 5), ("x" * 1001, 5), ("x", True), ("x", 0), ("x", 6), ("x", "5"), ("x\x00", 5)])
async def test_strict_search_arguments(query, limit):
    s, calls = store()
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search(query, limit))
    assert e.value.category == "invalid_input" and not calls


@pytest.mark.parametrize("url", ["http://localhost/a", "https://foo.local/a", "http://127.0.0.1/", "http://[::1]/", "http://10.1.1.1/", "http://169.254.169.254/", "http://2130706433/", "http://0177.0.0.1/", "http://0x7f000001/", "file:///etc/passwd", "https://u:p@example.com/", "https://example.com:444/a", "https://example.com\\@localhost/a", "https://example.com/%0aevil", "https://example.com/#fragment"])
async def test_private_or_ambiguous_urls_never_registered(url):
    s, calls = store(lambda _: httpx.Response(200, json={"results": [result(url=url)]}))
    assert (await s.web_search("q")) == []
    assert len(calls) == 1


@pytest.mark.parametrize("source_id", [URL, "../secret", "gw_" + "a" * 32, None, {"url": URL}])
async def test_unknown_ids_are_local_errors(source_id):
    s, calls = store()
    with pytest.raises(module().GeneralWebError) as e:
        (await s.read_page(source_id))
    assert e.value.category == "invalid_input" and not calls


async def test_cross_store_ids_and_evidence_rejected():
    a, _ = store()
    b, calls = store()
    m = (await a.web_search("q"))[0]
    with pytest.raises(module().GeneralWebError):
        (await b.read_page(m["source_id"]))
    assert not b.validate_evidence((await a.read_page(m["source_id"]))) and not calls


async def test_caches_defensive_copies_singleflight_and_caps():
    s, calls = store(search_limit=1, read_limit=1)
    results = await asyncio.gather(*(s.web_search("q") for _ in range(8)))
    sid = results[0][0]["source_id"]
    results[0][0]["url"] = "http://localhost/"
    assert (await s.web_search("q"))[0]["url"] == URL
    pages = await asyncio.gather(*(s.read_page(sid) for _ in range(8)))
    pages[0]["excerpt"] = "tampered"
    assert (await s.read_page(sid))["excerpt"] != "tampered" and len(calls) == 2
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("new"))
    assert e.value.category == "budget"


@pytest.mark.parametrize("status,category", [(401, "auth"), (403, "auth"), (402, "quota"), (429, "quota"), (500, "unavailable"), (302, "security")])
async def test_errors_are_sanitized_cached_and_quota_auth_latch(status, category):
    s, calls = store(lambda _: httpx.Response(status, headers={"location": "http://localhost/"}, text=KEY))
    for q in ["q", "q", "different" if status in (401, 403, 402, 429) else "q"]:
        with pytest.raises(module().GeneralWebError) as e:
            (await s.web_search(q))
        assert e.value.category == category and KEY not in str(e.value)
    assert len(calls) == 1


async def test_timeout_no_exception_details_and_negative_cache():
    def handler(req):
        raise httpx.ReadTimeout(KEY, request=req)
    s, calls = store(handler)
    for _ in range(2):
        with pytest.raises(module().GeneralWebError) as e:
            (await s.web_search("q"))
        assert e.value.category == "timeout" and KEY not in str(e.value)
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"results": "wrong"}, {"results": [result(title=KEY)]}, {"results": [result(url=URL + "?token=" + KEY)]}])
async def test_malformed_or_secret_responses_fail_closed(payload):
    s, _ = store(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category in {"security", "unavailable"} and KEY not in str(e.value)


async def test_response_byte_bound():
    s, _ = store(lambda _: httpx.Response(200, content=b" " * 262145))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category == "oversize"


@pytest.mark.parametrize("changes", [{"text": ""}, {"text": " "}, {"text": 123}, {"text": "x" * 12001}, {"text": "<html><body>raw</body></html>"}, {"text": KEY}, {"url": "http://127.0.0.1/"}, {"url": "https://other.example/page"}])
async def test_invalid_contents_never_become_evidence(changes):
    def handler(req):
        item = result() if req.url.path == "/search" else result(text="valid", **{}) | changes
        return httpx.Response(200, json={"results": [item]})
    s, calls = store(handler)
    sid = (await s.web_search("q"))[0]["source_id"]
    for _ in range(2):
        with pytest.raises(module().GeneralWebError):
            (await s.read_page(sid))
    assert len(calls) == 2


async def test_empty_key_disabled_without_network():
    s = module().GeneralWebStore(api_key=" ", transport=httpx.MockTransport(lambda _: pytest.fail("network")))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category == "unavailable"


async def test_dates_preserved_and_failed_status_rejected():
    def handler(req):
        return httpx.Response(200, json={"results": [result(publishedDate="2024-10-31T01:23:45Z", text="body")], "statuses": [{"id": URL, "status": "error", "error": KEY}]})
    s, _ = store(handler)
    m = (await s.web_search("q"))[0]
    assert m["published_at"] == "2024-10-31T01:23:45Z"
    with pytest.raises(module().GeneralWebError) as e:
        (await s.read_page(m["source_id"]))
    assert e.value.category == "unavailable"


async def test_compressed_responses_rejected_before_decompression():
    import gzip
    s, calls = store(lambda _: httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(b'{"results": []}')))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category == "security" and len(calls) == 1


async def test_absolute_deadline_while_awaiting_response_headers(monkeypatch):
    monkeypatch.setattr(module(), "REQUEST_TIMEOUT", .02)
    exited = asyncio.Event()
    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()
    s = module().GeneralWebStore(api_key=KEY, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(module().GeneralWebError) as e:
            await asyncio.wait_for(s.web_search("q"), .3)
        assert e.value.category == "timeout" and exited.is_set()
    finally:
        await s.close()


async def test_read_cap_and_untrusted_upstream_id_never_used():
    def handler(req):
        return httpx.Response(200, json={"results": [result(id="http://localhost/", url=URL + str(i)) for i in range(2)]})
    s, calls = store(handler, read_limit=0)
    found = (await s.web_search("q"))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.read_page(found[0]["source_id"]))
    assert e.value.category == "budget" and len(calls) == 1


async def test_request_config_disables_environment_and_redirects(monkeypatch):
    original = httpx.AsyncClient
    config = {}
    def client(**kwargs):
        config.update(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    s, _ = store()
    assert config["trust_env"] is False and config["follow_redirects"] is False
    assert config["timeout"] == 15.0
    (await s.close())
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category == "unavailable"


@pytest.mark.parametrize("kwargs", [{"search_limit": 7}, {"read_limit": 9}, {"search_limit": True}, {"read_limit": -1}])
async def test_operator_caps_can_only_be_lowered(kwargs):
    with pytest.raises(module().GeneralWebError) as e:
        store(**kwargs)
    assert e.value.category == "invalid_input"


async def test_oversized_results_and_invalid_dates_fail_closed():
    for items in [[result() for _ in range(6)], [result(publishedDate="not-a-date")]]:
        s, _ = store(lambda _: httpx.Response(200, json={"results": items}))
        with pytest.raises(module().GeneralWebError):
            (await s.web_search("q"))


async def test_contents_uses_registered_url_not_provider_id():
    def handler(req):
        return httpx.Response(200, json={"results": [result(id="http://localhost/", text="page")]})
    s, calls = store(handler)
    sid = (await s.web_search("q"))[0]["source_id"]
    assert (await s.read_page(sid))["excerpt"] == "page"
    assert json.loads(calls[-1].content)["ids"] == [URL]


async def test_chunked_oversize_closes_stream():
    class Chunks(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b" " * 131072
            yield b" " * 131073
        async def aclose(self):
            self.closed = True
    stream = Chunks()
    s, _ = store(lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(module().GeneralWebError) as e:
        (await s.web_search("q"))
    assert e.value.category == "oversize" and stream.closed
