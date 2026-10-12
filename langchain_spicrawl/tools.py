"""Spicrawl tools."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool, ToolException
from langchain_core.utils import secret_from_env
from pydantic import BaseModel, Field, SecretStr

from langchain_spicrawl._client import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    ScrapeResult,
    SpicrawlClient,
    SpicrawlError,
)


class SpicrawlScrapeInput(BaseModel):
    """Input for :class:`SpicrawlScrapeTool`."""

    url: str = Field(description="Absolute http(s) URL of the page to read.")
    js_render: bool = Field(
        default=False,
        description=(
            "Set true only when a first attempt returned an empty page or a placeholder "
            "because the content is built by JavaScript. Costs 3 credits instead of 1."
        ),
    )


class SpicrawlScrapeTool(BaseTool):
    """Tool that reads a web page as markdown with the Spicrawl API.

    Setup:
        Install ``langchain-spicrawl`` and set the ``SPICRAWL_API_KEY`` environment variable.

        .. code-block:: bash

            pip install -U langchain-spicrawl
            export SPICRAWL_API_KEY="spicrawl_live_..."

    Instantiation:
        .. code-block:: python

            from langchain_spicrawl import SpicrawlScrapeTool

            tool = SpicrawlScrapeTool(max_chars=20_000)

    Invocation with args:
        .. code-block:: python

            tool.invoke({"url": "https://example.com"})

        .. code-block:: python

            "Example Domain\\n\\nThis domain is for use in documentation examples..."

    Invocation with ToolCall:
        .. code-block:: python

            tool.invoke(
                {
                    "args": {"url": "https://example.com"},
                    "id": "1",
                    "name": tool.name,
                    "type": "tool_call",
                }
            )

    Errors (a bad key, a quota, a blocked page) come back to the model as the tool's text
    output, so an agent can react instead of crashing.
    """

    name: str = "spicrawl_scrape"
    description: str = (
        "Read a web page and return its main content as markdown. Use it to open a URL you already "
        "have. Input is the page URL. Set js_render only if the first result is empty because the "
        "page is built by JavaScript."
    )
    args_schema: type[BaseModel] = SpicrawlScrapeInput
    handle_tool_error: bool = True

    api_key: SecretStr = Field(default_factory=secret_from_env("SPICRAWL_API_KEY"))
    """Spicrawl API key. Defaults to the ``SPICRAWL_API_KEY`` environment variable."""
    base_url: str | None = None
    """API base URL. Defaults to ``SPICRAWL_BASE_URL`` or ``https://api.spicrawl.com``."""
    scrape_options: dict[str, Any] = Field(default_factory=dict)
    """Extra ``POST /v1/scrape`` fields for every call, e.g. ``{"wait_for": ".content"}``.
    ``response_format`` is always ``markdown``."""
    max_chars: int = 30_000
    """The page is cut to this many characters before it reaches the model."""
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES

    def _client(self) -> SpicrawlClient:
        return SpicrawlClient(
            self.api_key.get_secret_value(),
            self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def _options(self, js_render: bool) -> dict[str, Any]:
        return {**self.scrape_options, "js_render": True} if js_render else self.scrape_options

    def _format(self, result: ScrapeResult) -> str:
        text = result.content.strip()
        if not text:
            return (
                f"{result.url} returned no readable content. If the page is built by JavaScript, "
                "call again with js_render=true."
            )
        if len(text) > self.max_chars:
            shown = f"{self.max_chars} of {len(text)}"
            return f"{text[: self.max_chars]}\n\n[truncated: showing {shown} characters]"
        return text

    def _run(
        self,
        url: str,
        js_render: bool = False,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            return self._format(self._client().scrape(url, self._options(js_render)))
        except SpicrawlError as err:
            raise ToolException(str(err)) from err

    async def _arun(
        self,
        url: str,
        js_render: bool = False,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            return self._format(await self._client().ascrape(url, self._options(js_render)))
        except SpicrawlError as err:
            raise ToolException(str(err)) from err
