import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPICRAWL_API_KEY", "spicrawl_test_unit")
    monkeypatch.delenv("SPICRAWL_BASE_URL", raising=False)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries never really wait in unit tests."""
    monkeypatch.setattr("time.sleep", lambda _s: None)

    async def instant(_s: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", instant)
