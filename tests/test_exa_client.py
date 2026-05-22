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
