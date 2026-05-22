import asyncio

import datasource.adapters.exa_client as exa_module
from datasource.adapters.exa_client import AsyncExaClient


class MemoryCache:
    def __init__(self, data):
        self.data = data

    def get(self, key):
        return self.data

    def set(self, key, data, ttl=None):
        self.data = data


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
    item = {
        "url": "https://example.com/c",
        "title": "Title",
        "publishedDate": "2025-12-18",
    }
    mapped = client._map_result(item)
    assert mapped["snippet"] == "Title"
    assert mapped["published_date"] == "2025-12-18"


def test_exa_map_result_truncates_snippet_and_content():
    client = AsyncExaClient(api_key="test-key")
    long_text = "A" * 5000

    mapped = client._map_result(
        {
            "url": "https://example.com/a",
            "title": "Example",
            "text": long_text,
            "summary": long_text,
            "highlights": [long_text],
            "score": 0.91,
            "publishedDate": "2026-05-22",
        }
    )

    assert mapped["url"] == "https://example.com/a"
    assert len(mapped["snippet"]) <= client.snippet_max_chars
    assert len(mapped["content"]) <= client.content_max_chars
    assert mapped["snippet"].endswith("...")
    assert mapped["content"].endswith("...")


def test_exa_error_metadata_extracts_status_tag_and_request_id():
    class Response:
        status_code = 429
        headers = {"x-request-id": "req-123"}

    exc = RuntimeError("rate limit exceeded")
    exc.response = Response()

    metadata = AsyncExaClient.error_metadata(exc)

    assert metadata["exa_http_status"] == 429
    assert metadata["exa_error_tag"] == "rate_limited"
    assert metadata["exa_error_type"] == "RuntimeError"
    assert metadata["exa_request_id"] == "req-123"
    assert "rate limit" in metadata["exa_error_message"]


def test_exa_search_truncates_cached_snippet_and_content():
    long_text = "C" * 5000
    cache = MemoryCache(
        {
            "results": [
                {
                    "url": "https://example.com/cached",
                    "title": "Cached",
                    "snippet": long_text,
                    "content": long_text,
                    "score": 0.5,
                    "published_date": "2026-05-22",
                }
            ],
            "query": "cached query",
            "cache_hit": False,
        }
    )
    client = AsyncExaClient(
        api_key="test-key",
        cache=cache,
        snippet_max_chars=4,
        content_max_chars=5,
    )

    result = asyncio.run(client.search(query="cached query"))

    cached_result = result["results"][0]
    assert result["cache_hit"] is True
    assert len(cached_result["snippet"]) <= 4
    assert len(cached_result["content"]) <= 5


def test_exa_truncate_respects_small_bounds():
    text = "abcdef"

    assert len(AsyncExaClient._truncate(text, 0)) <= 0
    assert len(AsyncExaClient._truncate(text, 1)) <= 1
    assert len(AsyncExaClient._truncate(text, 2)) <= 2


def test_exa_sdk_available_reflects_optional_dependency(monkeypatch):
    monkeypatch.setattr(exa_module, "Exa", None)
    assert AsyncExaClient.sdk_available() is False

    monkeypatch.setattr(exa_module, "Exa", object)
    assert AsyncExaClient.sdk_available() is True


def test_exa_search_preserves_response_request_id(monkeypatch):
    class FakeExa:
        def search(self, **kwargs):
            return {"results": [], "requestId": "exa-request-123"}

    monkeypatch.setattr(exa_module, "Exa", lambda api_key: FakeExa())
    client = AsyncExaClient(api_key="test-key")

    result = asyncio.run(client.search(query="request id query"))

    assert result["request_id"] == "exa-request-123"
