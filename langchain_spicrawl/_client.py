"""Minimal client for ``POST /v1/scrape``. Internal: use the loader or the tool."""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from importlib import metadata
from typing import Any

import httpx

try:
    VERSION = metadata.version("langchain-spicrawl")
except metadata.PackageNotFoundError:  # pragma: no cover - not installed
    VERSION = "0.0.0"

DEFAULT_BASE_URL = "https://api.spicrawl.com"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_WAIT = 30.0
"""Never sleep longer than this for a ``Retry-After``; a longer wait is raised instead."""


class SpicrawlError(Exception):
    """A failed scrape.

    ``code`` is the API's stable error code (``ERR::FAMILY::NAME``) or one of
    ``TARGET_STATUS`` (the site answered 4xx/5xx) and ``CONNECTION`` (no response).
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.request_id = request_id


@dataclass(frozen=True)
class ScrapeResult:
    """One successfully scraped page."""

    url: str
    content: str
    final_url: str | None = None
    target_status: int | None = None
    credits_charged: int | None = None
    engine: str | None = None
    cache_state: str | None = None
    request_id: str | None = None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def _problem(resp: httpx.Response) -> SpicrawlError:
    """Turn an ``application/problem+json`` (or any non-2xx) response into an error."""
    request_id = resp.headers.get("x-request-id")
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or "code" not in body:
        return SpicrawlError(
            f"Spicrawl API returned HTTP {resp.status_code}.",
            status=resp.status_code,
            request_id=request_id,
        )
    message = f"{body['code']}: {body.get('detail') or body.get('title') or 'request failed'}"
    hint = (body.get("diagnostics") or {}).get("hint")
    if hint:
        message += f" Hint: {hint}"
    retry_after = body.get("retry_after_seconds")
    if retry_after is None:
        try:
            retry_after = float(resp.headers["retry-after"])
        except (KeyError, ValueError):
            retry_after = None
    return SpicrawlError(
        message,
        code=body["code"],
        status=resp.status_code,
        retryable=body.get("retryable") is True,
        retry_after=retry_after,
        request_id=body.get("request_id") or request_id,
    )


def _parse(url: str, resp: httpx.Response) -> ScrapeResult:
    if not resp.is_success:
        raise _problem(resp)
    h = resp.headers
    target_status = _int(h.get("x-target-status"))
    if h.get("content-type", "").split(";")[0].strip().lower().endswith("json"):
        # extract / links / autoparse / ... force the JSON envelope; the page is `content`.
        body = resp.json()
        text = body.get("content") or ""
        target_status = target_status or body.get("status")
    else:
        text = resp.text
    request_id = h.get("x-request-id")
    if target_status is not None and target_status >= 400:
        # HTTP 200 + X-Target-Status 403/500 is a block or error page, billed 0: not content.
        raise SpicrawlError(
            f"{url} answered HTTP {target_status}; no usable content was returned.",
            code="TARGET_STATUS",
            status=resp.status_code,
            request_id=request_id,
        )
    return ScrapeResult(
        url=url,
        content=text,
        final_url=h.get("x-final-url"),
        target_status=target_status,
        credits_charged=_int(h.get("x-credits-charged")),
        engine=h.get("x-engine"),
        cache_state=h.get("cache-state"),
        request_id=request_id,
    )


def _wait(err: SpicrawlError, attempt: int, max_retries: int) -> float | None:
    """Seconds to wait before retrying, or ``None`` to raise.

    Only errors the server marks ``retryable`` are retried. They are refusals, billed 0, so a
    retry cannot bill twice. A dropped connection is never retried: the scrape may have run.
    """
    if attempt >= max_retries or not err.retryable:
        return None
    if err.retry_after is None:
        return float(min(0.5 * 2**attempt, 8.0) * (0.5 + random.random() / 2))
    return err.retry_after if err.retry_after <= MAX_RETRY_WAIT else None


class SpicrawlClient:
    """Sync and async ``/v1/scrape`` calls with retries."""

    # ponytail: one HTTP connection per call; share a client if a loader scrapes thousands of URLs
    # (for that, use the batch API instead).

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._api_key = api_key
        self.base_url = (
            base_url or os.environ.get("SPICRAWL_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

    def __repr__(self) -> str:
        return f"SpicrawlClient(base_url={self.base_url!r})"

    def _request(self, url: str, options: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "headers": {
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "text/markdown, application/json",
                "User-Agent": f"langchain-spicrawl/{VERSION}",
            },
            # the loader and tool promise markdown, so it overrides any `response_format` option
            "json": {**(options or {}), "url": url, "response_format": "markdown"},
        }

    def scrape(self, url: str, options: dict[str, Any] | None = None) -> ScrapeResult:
        """Scrape ``url`` and return it as markdown. Raises :class:`SpicrawlError`."""
        attempt = 0
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as http:
            while True:
                try:
                    return _parse(url, http.post("/v1/scrape", **self._request(url, options)))
                except httpx.HTTPError as exc:
                    raise SpicrawlError(
                        f"Could not reach Spicrawl: {exc}", code="CONNECTION"
                    ) from exc
                except SpicrawlError as err:
                    wait = _wait(err, attempt, self.max_retries)
                    if wait is None:
                        raise
                    time.sleep(wait)
                    attempt += 1

    async def ascrape(self, url: str, options: dict[str, Any] | None = None) -> ScrapeResult:
        """Async :meth:`scrape`."""
        attempt = 0
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as http:
            while True:
                try:
                    return _parse(url, await http.post("/v1/scrape", **self._request(url, options)))
                except httpx.HTTPError as exc:
                    raise SpicrawlError(
                        f"Could not reach Spicrawl: {exc}", code="CONNECTION"
                    ) from exc
                except SpicrawlError as err:
                    wait = _wait(err, attempt, self.max_retries)
                    if wait is None:
                        raise
                    await asyncio.sleep(wait)
                    attempt += 1
