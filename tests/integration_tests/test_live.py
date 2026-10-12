"""Live tests. They spend credits: run with `make integration_test` and a test key."""

import os
from typing import Any

import pytest
from langchain_tests.integration_tests import ToolsIntegrationTests

from langchain_spicrawl import SpicrawlLoader, SpicrawlScrapeTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("SPICRAWL_API_KEY"), reason="SPICRAWL_API_KEY is not set"
)


class TestSpicrawlScrapeToolIntegration(ToolsIntegrationTests):
    @property
    def tool_constructor(self) -> type[SpicrawlScrapeTool]:
        return SpicrawlScrapeTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"url": "https://example.com"}


def test_loader_loads_example_com() -> None:
    docs = SpicrawlLoader("https://example.com").load()
    assert len(docs) == 1
    assert "Example Domain" in docs[0].page_content
    assert docs[0].metadata["target_status"] == 200
