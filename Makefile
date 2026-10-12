.PHONY: all format lint test tests integration_test integration_tests build help

all: help

TEST_FILE ?= tests/unit_tests/
integration_test integration_tests: TEST_FILE = tests/integration_tests/

# unit tests run with --disable-socket: any real network call fails the test
test tests:
	uv run --group test pytest --disable-socket --allow-unix-socket $(TEST_FILE)

# integration tests call the live API and spend credits; set SPICRAWL_API_KEY (a test key is fine)
integration_test integration_tests:
	uv run --group test pytest $(TEST_FILE)

lint:
	uv run --group lint ruff check .
	uv run --group lint ruff format . --diff
	uv run --group typing --group test mypy langchain_spicrawl tests

format:
	uv run --group lint ruff format .
	uv run --group lint ruff check --fix .

build:
	uv build

help:
	@echo 'test                 - run unit tests (no network)'
	@echo 'integration_test     - run live tests (needs SPICRAWL_API_KEY)'
	@echo 'lint                 - ruff + mypy'
	@echo 'format               - ruff format + fix'
	@echo 'build                - build sdist and wheel into dist/'
