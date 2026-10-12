"""LangChain integration for Spicrawl, the web scraping API."""

from langchain_spicrawl._client import VERSION as __version__
from langchain_spicrawl._client import SpicrawlError
from langchain_spicrawl.document_loaders import SpicrawlLoader
from langchain_spicrawl.tools import SpicrawlScrapeInput, SpicrawlScrapeTool

__all__ = [
    "SpicrawlError",
    "SpicrawlLoader",
    "SpicrawlScrapeInput",
    "SpicrawlScrapeTool",
    "__version__",
]
