from datasource.adapters.exa_client import AsyncExaClient


def test_exa_map_result_prefers_highlights():
    client = AsyncExaClient(api_key="test")
    item = {
        "url": "https://example.com/a",
        "title": "Title",
        "text": "Long text content",
        "summary": "Summary",
        "highlights": ["A", "B"],
        "published_date": "2025-12-18",
    }
    mapped = client._map_result(item)
    assert mapped["snippet"] == "A B"
    assert mapped["content"] == "Long text content"
    assert mapped["published_date"] == "2025-12-18"


def test_exa_map_result_fallback_to_summary():
    client = AsyncExaClient(api_key="test")
    item = {"url": "https://example.com/b", "title": "Title", "summary": "Summary"}
    mapped = client._map_result(item)
    assert mapped["snippet"] == "Summary"
    assert mapped["content"] == "Summary"


def test_exa_map_result_fallback_to_title():
    client = AsyncExaClient(api_key="test")
    item = {"url": "https://example.com/c", "title": "Title", "publishedDate": "2025-12-18"}
    mapped = client._map_result(item)
    assert mapped["snippet"] == "Title"
    assert mapped["published_date"] == "2025-12-18"
