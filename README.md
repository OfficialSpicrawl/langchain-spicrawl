# langchain-spicrawl

[![smithery badge](https://smithery.ai/badge/spicrawl/web-scraper)](https://smithery.ai/servers/spicrawl/web-scraper)

Also available as an MCP server: [Smithery](https://smithery.ai/servers/spicrawl/web-scraper) · [MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.OfficialSpicrawl/mcp)

[LangChain](https://docs.langchain.com) integration for [Spicrawl](https://docs.spicrawl.com), a web
scraping API that returns any URL as clean markdown, optionally rendering JavaScript first.

This package provides:

| Component | Class | Use it to |
|---|---|---|
| Document loader | `SpicrawlLoader` | Turn URLs into `Document` objects (markdown content plus metadata) for RAG and indexing |
| Tool | `SpicrawlScrapeTool` | Let an agent open a URL and read it |

## Installation

```bash
pip install -U langchain-spicrawl
```

Create an API key in the [Spicrawl dashboard](https://app.spicrawl.com/dashboard/keys) and export it.
Keys start with `spicrawl_live_` (spends credits) or `spicrawl_test_`.

```bash
export SPICRAWL_API_KEY="spicrawl_live_..."
```

## Document loader

```python
from langchain_spicrawl import SpicrawlLoader

loader = SpicrawlLoader(["https://example.com", "https://example.org"])
docs = loader.load()

print(docs[0].page_content)
# 'Example Domain\n\nThis domain is for use in documentation examples without needing permission. ...'
print(docs[0].metadata)
# {'source': 'https://example.com', 'final_url': 'https://example.com/',
#  'target_status': 200, 'credits_charged': 1, 'engine': 'fetch',
#  'cache_state': 'hit', 'request_id': '01M4QYNXGPFF9VRGS64F0JE092'}
```

`lazy_load()`, `aload()` and `alazy_load()` work too. A page that needs JavaScript, or any other
`POST /v1/scrape` option, goes in `scrape_options`:

```python
loader = SpicrawlLoader(
    "https://example.com/pricing",
    scrape_options={"js_render": True, "wait_for": ".plans", "exclude_tags": ["nav", "footer"]},
    continue_on_failure=True,  # log and skip a URL that fails instead of raising
)
```

### Index pages for RAG

```python
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

docs = SpicrawlLoader(["https://example.com/docs/intro", "https://example.com/docs/api"]).load()
chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_documents(docs)
store = InMemoryVectorStore.from_documents(chunks, OpenAIEmbeddings())
print(store.similarity_search("How do I authenticate?", k=3))
```

### Loader parameters

| Parameter | Default | Meaning |
|---|---|---|
| `urls` | required | One URL or a list of URLs. Scraped one after the other, in order. |
| `api_key` | `$SPICRAWL_API_KEY` | Spicrawl API key. |
| `base_url` | `$SPICRAWL_BASE_URL` or `https://api.spicrawl.com` | API base URL. |
| `scrape_options` | `{}` | Extra [`POST /v1/scrape`](https://docs.spicrawl.com/api-reference/scrape/scrape-post) fields sent with every URL. `response_format` is always `markdown`. |
| `continue_on_failure` | `False` | Skip failed URLs (logged as warnings) instead of raising. |
| `timeout` | `120` | Seconds to wait for each response. |
| `max_retries` | `2` | Retries of errors the API marks `retryable` (rate limits, timeouts). |

### Metadata

| Key | Value |
|---|---|
| `source` | The URL you passed |
| `title` | First `#` heading in the markdown (omitted when the page has none) |
| `final_url` | URL after redirects |
| `target_status` | The site's HTTP status |
| `credits_charged` | Credits this page cost |
| `engine` | Rendering tier that served the page: `fetch`, `js` or `browser` |
| `cache_state` | `hit`, `miss` or `bypass` |
| `request_id` | Quote it to Spicrawl support, or look it up with `GET /v1/requests/{id}` |

## Agent tool

```python
from langchain.agents import create_agent
from langchain_spicrawl import SpicrawlScrapeTool

tool = SpicrawlScrapeTool(max_chars=20_000)

agent = create_agent("openai:gpt-4.1", tools=[tool])
result = agent.invoke(
    {"messages": [{"role": "user", "content": "Read https://example.com and summarize it."}]}
)
print(result["messages"][-1].content)
```

Call it directly:

```python
tool.invoke({"url": "https://example.com"})
# 'Example Domain\n\nThis domain is for use in documentation examples without needing permission. ...'
```

The model sees two arguments: `url` and `js_render` (set only when the first attempt came back empty
because the page is built by JavaScript). Everything else is fixed by you at construction:

| Parameter | Default | Meaning |
|---|---|---|
| `api_key` | `$SPICRAWL_API_KEY` | Spicrawl API key. Held as a `SecretStr`, never printed. |
| `base_url` | `$SPICRAWL_BASE_URL` or `https://api.spicrawl.com` | API base URL. |
| `scrape_options` | `{}` | Extra `POST /v1/scrape` fields for every call. `response_format` is always `markdown`. |
| `max_chars` | `30000` | The page is cut to this length, with a notice, before it reaches the model. |
| `timeout` | `120` | Seconds to wait for each response. |
| `max_retries` | `2` | Retries of errors the API marks `retryable`. |

Failures (a blocked page, an exhausted credit allowance, a bad key) are returned to the model as the
tool's text output, for example `ERR::LIMIT::QUOTA_EXCEEDED: ...`, so the agent can react instead of
crashing the run.

## Cost, retries and errors

- A plain fetch costs 1 credit and `js_render` costs 3. Failures cost 0. A cached result is billed at
  the price of the fetch that stored it. See [Credits](https://docs.spicrawl.com/credits).
- Only errors the API marks `retryable` are retried, after `Retry-After`. A dropped connection is never
  retried, because the scrape may already have run and been billed.
- A site that answers 4xx or 5xx (an access-denied page, a 404) is raised as `SpicrawlError` with
  `code == "TARGET_STATUS"`, not returned as content.
- Every `SpicrawlError` carries `code` (for example `ERR::LIMIT::RATE_LIMITED`), `status`, `retryable`
  and `request_id`. All codes are listed in the [error reference](https://docs.spicrawl.com/errors).

```python
from langchain_spicrawl import SpicrawlError, SpicrawlLoader

try:
    SpicrawlLoader("https://example.com").load()
except SpicrawlError as err:
    print(err.code, err.status, err.request_id)
```

## Development

```bash
make test               # unit tests, HTTP mocked, sockets disabled
make lint               # ruff and mypy
make integration_test   # live; needs SPICRAWL_API_KEY, spends credits
```

## License

MIT
