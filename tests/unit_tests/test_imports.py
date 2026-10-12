from langchain_spicrawl import __all__

EXPECTED = [
    "SpicrawlError",
    "SpicrawlLoader",
    "SpicrawlScrapeInput",
    "SpicrawlScrapeTool",
    "__version__",
]


def test_all_imports() -> None:
    assert sorted(EXPECTED) == sorted(__all__)
