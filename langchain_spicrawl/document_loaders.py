"""Spicrawl document loader."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

from langchain_spicrawl._client import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    ScrapeResult,
    SpicrawlClient,
    SpicrawlError,
)

logger = logging.getLogger(__name__)

_TITLE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _document(result: ScrapeResult) -> Document:
    title = _TITLE.search(result.content)
    metadata: dict[str, Any] = {
        "source": result.url,
        "title": title.group(1) if title else None,
        "final_url": result.final_url,
        "target_status": result.target_status,
        "credits_charged": result.credits_charged,
        "engine": result.engine,
        "cache_state": result.cache_state,
        "request_id": result.request_id,
    }
    return Document(
        page_content=result.content, metadata={k: v for k, v in metadata.items() if v is not None}
    )


class SpicrawlLoader(BaseLoader):
    """Load web pages as markdown `Document` objects with the Spicrawl API.

    Setup:
        Install ``langchain-spicrawl`` and set the ``SPICRAWL_API_KEY`` environment
        variable (keys start with ``spicrawl_live_`` or ``spicrawl_test_``).

        .. code-block:: bash

            pip install -U langchain-spicrawl
            export SPICRAWL_API_KEY="spicrawl_live_..."

    Instantiate:
        .. code-block:: python

            from langchain_spicrawl import SpicrawlLoader

            loader = SpicrawlLoader(
                ["https://example.com", "https://example.org"],
                scrape_options={"js_render": True},
            )

    Lazy load:
        .. code-block:: python

            for doc in loader.lazy_load():
                print(doc.metadata["source"], doc.page_content[:100])

    Async load:
        .. code-block:: python

            docs = await loader.aload()

    Each page costs 1 credit (3 with ``js_render``). Pages are fetched one after the other;
    for thousands of URLs use the Spicrawl batch API.

    Metadata keys: ``source`` (the URL you passed), ``title`` (first ``#`` heading),
    ``final_url``, ``target_status`` (the site's HTTP status), ``credits_charged``,
    ``engine`` (rendering tier), ``cache_state`` and ``request_id``.
    """

    def __init__(
        self,
        urls: str | Sequence[str],
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        scrape_options: dict[str, Any] | None = None,
        continue_on_failure: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Create a loader.

        Args:
            urls: One URL or a list of URLs.
            api_key: Spicrawl API key. Defaults to the ``SPICRAWL_API_KEY`` environment variable.
            base_url: API base URL. Defaults to ``SPICRAWL_BASE_URL`` or ``https://api.spicrawl.com``.
            scrape_options: Extra ``POST /v1/scrape`` fields sent with every URL, for example
                ``js_render``, ``wait_for``, ``proxy``, ``include_tags``, ``exclude_tags`` or
                ``main_content_only``. ``response_format`` is always ``markdown``.
            continue_on_failure: Log and skip a URL that fails instead of raising.
            timeout: Seconds to wait for each response.
            max_retries: Retries of errors the API marks retryable (rate limits, timeouts).
        """
        key = api_key or os.environ.get("SPICRAWL_API_KEY")
        if not key:
            msg = "No API key: pass api_key=... or set the SPICRAWL_API_KEY environment variable."
            raise ValueError(msg)
        self.urls = [urls] if isinstance(urls, str) else list(urls)
        self.scrape_options = dict(scrape_options or {})
        self.continue_on_failure = continue_on_failure
        self._client = SpicrawlClient(key, base_url, timeout=timeout, max_retries=max_retries)

    def lazy_load(self) -> Iterator[Document]:
        """Scrape each URL in order and yield one `Document` per page."""
        for url in self.urls:
            try:
                yield _document(self._client.scrape(url, self.scrape_options))
            except SpicrawlError as err:
                if not self.continue_on_failure:
                    raise
                logger.warning("Skipping %s: %s", url, err)

    async def alazy_load(self) -> AsyncIterator[Document]:
        """Async :meth:`lazy_load`."""
        for url in self.urls:
            try:
                yield _document(await self._client.ascrape(url, self.scrape_options))
            except SpicrawlError as err:
                if not self.continue_on_failure:
                    raise
                logger.warning("Skipping %s: %s", url, err)
