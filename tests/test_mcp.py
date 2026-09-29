import pytest

@pytest.mark.asyncio
async def test_real_stdio_tools_search_section_and_bounds():
    from backend.mcp_client import document_session, ToolFailure
    async with document_session() as client:
        assert set(await client.list_tools()) == {"search_documents", "get_section"}
        hits = await client.call("search_documents", {"query": "revenue", "limit": 2})
        assert 0 < len(hits) <= 2
        item = hits[0]
        section = await client.call("get_section", {"document_id": item["document_id"], "section_id": item["section_id"]})
        assert section["id"] == item["id"]
        assert section["url"].startswith("https://")
        assert section["as_of"] == "2024-09-28"
        assert await client.call("search_documents", {"query": "nonexistentxyz"}) == []
        with pytest.raises(ToolFailure):
            await client.call("get_section", {"document_id": "../../etc/passwd", "section_id": "x"})
        with pytest.raises(ToolFailure):
            await client.call("search_documents", {"query": "x" * 301})
        with pytest.raises(ToolFailure):
            await client.call("shell", {"command": "pwd"})
