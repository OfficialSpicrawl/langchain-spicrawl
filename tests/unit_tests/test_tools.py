import json
from typing import Any

import httpx
import pytest
import respx
from langchain_core.messages import ToolMessage
from langchain_tests.unit_tests import ToolsUnitTests

from langchain_spicrawl import SpicrawlScrapeTool

API = "https://api.spicrawl.com/v1/scrape"
PAGE = "# Pricing\n\nFree: 1000 credits.\n"
OK = {"content-type": "text/markdown", "x-target-status": "200", "x-credits-charged": "1"}


class TestSpicrawlScrapeToolUnit(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[SpicrawlScrapeTool]:
        return SpicrawlScrapeTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_key": "spicrawl_test_unit"}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"url": "https://example.com"}

    @property
    def init_from_env_params(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return {"SPICRAWL_API_KEY": "spicrawl_test_env"}, {}, {"api_key": "spicrawl_test_env"}


@respx.mock
def test_invoke_returns_markdown() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=OK))
    tool = SpicrawlScrapeTool(scrape_options={"main_content_only": True})

    assert tool.invoke({"url": "https://example.com/pricing"}) == PAGE.strip()
    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "main_content_only": True,
        "url": "https://example.com/pricing",
        "response_format": "markdown",
    }


@respx.mock
def test_js_render_argument_reaches_the_api() -> None:
    route = respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=OK))
    SpicrawlScrapeTool().invoke({"url": "https://example.com", "js_render": True})
    assert json.loads(route.calls.last.request.content)["js_render"] is True


@respx.mock
def test_tool_call_returns_tool_message() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=OK))
    tool = SpicrawlScrapeTool()
    msg = tool.invoke(
        {"args": {"url": "https://example.com"}, "id": "1", "name": tool.name, "type": "tool_call"}
    )
    assert isinstance(msg, ToolMessage)
    assert msg.content == PAGE.strip()


@respx.mock
def test_long_pages_are_truncated() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, text="x" * 100, headers=OK))
    out = SpicrawlScrapeTool(max_chars=10).invoke({"url": "https://example.com"})
    assert out.startswith("x" * 10 + "\n\n[truncated")
    assert "10 of 100" in out


@respx.mock
def test_empty_page_suggests_js_render() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, text="  \n", headers=OK))
    assert "js_render=true" in SpicrawlScrapeTool().invoke({"url": "https://example.com"})


@respx.mock
def test_errors_come_back_as_text_for_the_agent() -> None:
    body = {"code": "ERR::UPSTREAM::CHALLENGE", "retryable": False, "detail": "Bot challenge."}
    respx.post(API).mock(
        return_value=httpx.Response(
            502, json=body, headers={"content-type": "application/problem+json"}
        )
    )
    out = SpicrawlScrapeTool().invoke({"url": "https://example.com"})
    assert out == "ERR::UPSTREAM::CHALLENGE: Bot challenge."


@respx.mock
async def test_ainvoke() -> None:
    respx.post(API).mock(return_value=httpx.Response(200, text=PAGE, headers=OK))
    assert await SpicrawlScrapeTool().ainvoke({"url": "https://example.com"}) == PAGE.strip()


@respx.mock
async def test_ainvoke_error_text() -> None:
    respx.post(API).mock(
        return_value=httpx.Response(
            401,
            json={"code": "ERR::AUTH::INVALID_KEY", "retryable": False, "detail": "Unknown key."},
            headers={"content-type": "application/problem+json"},
        )
    )
    out = await SpicrawlScrapeTool().ainvoke({"url": "https://example.com"})
    assert out.startswith("ERR::AUTH::INVALID_KEY")


def test_api_key_is_secret() -> None:
    tool = SpicrawlScrapeTool(api_key="spicrawl_test_secret")
    assert "spicrawl_test_secret" not in repr(tool)
    assert "spicrawl_test_secret" not in str(tool.model_dump())


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPICRAWL_API_KEY")
    with pytest.raises(ValueError, match="SPICRAWL_API_KEY"):
        SpicrawlScrapeTool()
