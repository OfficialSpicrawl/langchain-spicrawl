import json
import logging

import httpx
import pytest
import respx

from langchain_spicrawl import SpicrawlError, SpicrawlLoader

API = "https://api.spicrawl.com/v1/scrape"
PAGE = "# Example Domain\n\nThis domain is for use in illustrative examples.\n"
HEADERS = {
    "content-type": "text/markdown; charset=utf-8",
    "x-request-id": "01M0HF5WFWE7PRE8KZHDTNETWN",
    "x-target-status": "200",
    "x-final-url": "https://example.com/",
    "x-credits-charged": "1",
    "x-engine": "fetch",
    "cache-state": "miss",
}


def problem(code: str, status: int, *, retryable: bool, **extra: object) -> httpx.Response:
    body = {"code": code, "status": status, "retryable": retryable, "detail": "It broke.", **extra}
    return httpx.Response(status, json=body, headers={"content-type": "application/problem+json"})


@respx.mock
def test_load_returns_markdown_documents_with_metadata() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=HEADERS))
    docs = SpicrawlLoader("https://example.com").load()

    assert len(docs) == 1
    assert docs[0].page_content == PAGE
    assert docs[0].metadata == {
        "source": "https://example.com",
        "title": "Example Domain",
        "final_url": "https://example.com/",
        "target_status": 200,
        "credits_charged": 1,
        "engine": "fetch",
        "cache_state": "miss",
        "request_id": "01M0HF5WFWE7PRE8KZHDTNETWN",
    }
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer spicrawl_test_unit"
    assert json.loads(sent.content) == {"url": "https://example.com", "response_format": "markdown"}


@respx.mock
def test_many_urls_keep_order_and_scrape_options_are_sent() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, text="body", headers=HEADERS))
    loader = SpicrawlLoader(
        ["https://a.test", "https://b.test"],
        api_key="spicrawl_test_explicit",
        scrape_options={"js_render": True, "response_format": "html"},
    )
    docs = list(loader.lazy_load())

    assert [d.metadata["source"] for d in docs] == ["https://a.test", "https://b.test"]
    assert docs[0].metadata.get("title") is None  # no heading in the body: key omitted
    first = route.calls[0].request
    assert first.headers["authorization"] == "Bearer spicrawl_test_explicit"
    # js_render passes through; response_format is always markdown
    assert json.loads(first.content) == {
        "js_render": True,
        "url": "https://a.test",
        "response_format": "markdown",
    }


@respx.mock
async def test_aload() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=HEADERS))
    docs = await SpicrawlLoader(["https://example.com"]).aload()
    assert [d.page_content for d in docs] == [PAGE]
    assert docs[0].metadata["title"] == "Example Domain"


@respx.mock
def test_json_envelope_uses_content() -> None:
    envelope = {
        "url": "https://example.com",
        "status": 200,
        "content": PAGE,
        "links": ["https://iana.org"],
    }
    respx.post(API).mock(
        return_value=httpx.Response(
            200, json=envelope, headers={**HEADERS, "content-type": "application/json"}
        )
    )
    docs = SpicrawlLoader("https://example.com", scrape_options={"links": True}).load()
    assert docs[0].page_content == PAGE


@respx.mock
def test_api_error_raises_with_code_hint_and_request_id() -> None:
    respx.post(API).mock(
        return_value=problem(
            "ERR::LIMIT::QUOTA_EXCEEDED",
            402,
            retryable=False,
            request_id="01ABC",
            diagnostics={"hint": "Raise the monthly ceiling."},
        )
    )
    with pytest.raises(SpicrawlError) as info:
        SpicrawlLoader("https://example.com").load()
    err = info.value
    assert err.code == "ERR::LIMIT::QUOTA_EXCEEDED"
    assert err.status == 402
    assert err.request_id == "01ABC"
    assert "It broke." in str(err)
    assert "Hint: Raise the monthly ceiling." in str(err)


@respx.mock
def test_blocked_target_page_is_not_content() -> None:
    respx.post(API).mock(
        return_value=httpx.Response(
            200, text="Access denied", headers={**HEADERS, "x-target-status": "403"}
        )
    )
    with pytest.raises(SpicrawlError) as info:
        SpicrawlLoader("https://example.com").load()
    assert info.value.code == "TARGET_STATUS"
    assert "403" in str(info.value)


@respx.mock
def test_continue_on_failure_skips_bad_urls(caplog: pytest.LogCaptureFixture) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["url"] == "https://bad.test":
            return problem("ERR::UPSTREAM::DNS_FAILED", 502, retryable=False)
        return httpx.Response(200, text=PAGE, headers=HEADERS)

    respx.post(API).mock(side_effect=answer)
    loader = SpicrawlLoader(["https://bad.test", "https://example.com"], continue_on_failure=True)
    with caplog.at_level(logging.WARNING):
        docs = loader.load()

    assert [d.metadata["source"] for d in docs] == ["https://example.com"]
    assert "https://bad.test" in caplog.text


@respx.mock
def test_retryable_errors_are_retried_then_succeed() -> None:
    route = respx.post(API).mock(
        side_effect=[
            problem("ERR::LIMIT::RATE_LIMITED", 429, retryable=True, retry_after_seconds=0),
            problem("ERR::UPSTREAM::TIMEOUT", 504, retryable=True),
            httpx.Response(200, text=PAGE, headers=HEADERS),
        ]
    )
    docs = SpicrawlLoader("https://example.com", max_retries=2).load()
    assert route.call_count == 3
    assert docs[0].page_content == PAGE


@respx.mock
def test_retries_stop_at_max_retries() -> None:
    route = respx.post(API).mock(
        return_value=problem("ERR::UPSTREAM::TIMEOUT", 504, retryable=True)
    )
    with pytest.raises(SpicrawlError, match="TIMEOUT"):
        SpicrawlLoader("https://example.com", max_retries=1).load()
    assert route.call_count == 2


@respx.mock
def test_non_retryable_error_is_not_retried() -> None:
    route = respx.post(API).mock(
        return_value=problem("ERR::AUTH::INVALID_KEY", 401, retryable=False)
    )
    with pytest.raises(SpicrawlError):
        SpicrawlLoader("https://example.com").load()
    assert route.call_count == 1


@respx.mock
def test_dropped_connection_is_not_retried() -> None:
    # the scrape may have run and been billed, so it is never repeated
    route = respx.post(API).mock(side_effect=httpx.ReadTimeout("timed out"))
    with pytest.raises(SpicrawlError) as info:
        SpicrawlLoader("https://example.com").load()
    assert info.value.code == "CONNECTION"
    assert route.call_count == 1


@respx.mock
async def test_async_retry() -> None:
    route = respx.post(API).mock(
        side_effect=[
            problem("ERR::LIMIT::CONCURRENCY_EXCEEDED", 429, retryable=True, retry_after_seconds=1),
            httpx.Response(200, text=PAGE, headers=HEADERS),
        ]
    )
    docs = await SpicrawlLoader("https://example.com").aload()
    assert route.call_count == 2
    assert len(docs) == 1


@respx.mock
def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPICRAWL_BASE_URL", "https://api.example.test/")
    route = respx.post("https://api.example.test/v1/scrape").mock(
        return_value=httpx.Response(200, text=PAGE, headers=HEADERS)
    )
    SpicrawlLoader("https://example.com").load()
    assert route.called


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPICRAWL_API_KEY")
    with pytest.raises(ValueError, match="SPICRAWL_API_KEY"):
        SpicrawlLoader("https://example.com")


def test_key_is_not_in_repr() -> None:
    assert "spicrawl_test_unit" not in repr(SpicrawlLoader("https://example.com")._client)
