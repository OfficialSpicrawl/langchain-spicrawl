# langchain-spicrawl: load web pages into LangChain as Markdown

**How do I load web pages into LangChain as Markdown?** Use `SpicrawlLoader` from
`langchain-spicrawl`. Give it one URL or a list and call `load()`: you get LangChain `Document`s
whose `page_content` is each page as Markdown, with the final URL, the site's HTTP status and the
credits charged in `metadata`, ready for a text splitter and a vector store. The package also has
`SpicrawlScrapeTool`, a LangChain tool that lets an agent open a URL and read it. Both call the
[Spicrawl](https://docs.spicrawl.com) web scraping API with your API key, and `js_render` renders
pages that need JavaScript first. Python 3.10 or later, `langchain-core` 1.x.

[LangChain](https://docs.langchain.com) integration for [Spicrawl](https://docs.spicrawl.com), a web
scraping API that returns a URL as clean markdown, optionally rendering JavaScript first.

This package provides:

| Component | Class | Use it to |
|---|---|---|
| Document loader | `SpicrawlLoader` | Turn URLs into `Document` objects (markdown content plus metadata) for RAG and indexing |
| Tool | `SpicrawlScrapeTool` | Let an agent open a URL and read it |

## Installation

```bash
pip install "git+https://github.com/OfficialSpicrawl/langchain-spicrawl.git"
```

The package is not on PyPI yet, so install it from this repository.

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

## Use cases

- **RAG over web content.** Load a list of URLs with `SpicrawlLoader`, split the documents and put
  them in any vector store (see [Index pages for RAG](#index-pages-for-rag)). Spicrawl fetches only
  the URLs you list; it does not crawl a site, split text or embed it, so the URL list (from a
  sitemap, for example) and the vector store are yours.
- **Agents that read the web.** Give a LangChain agent `SpicrawlScrapeTool` and it can open a URL the
  user mentions, or one it found, and read the page as Markdown (see [Agent tool](#agent-tool)).
- **Pages built by JavaScript.** Set `scrape_options={"js_render": True}` and, if needed, `wait_for`
  for a selector to wait for.
- **Large URL lists.** `lazy_load()` and `alazy_load()` yield one document at a time, so a large
  URL list can be indexed as it loads.

## FAQ

### How do I load a web page into LangChain as Markdown?

```python
from langchain_spicrawl import SpicrawlLoader

docs = SpicrawlLoader("https://example.com").load()
print(docs[0].page_content)  # the page as Markdown
```

Set `SPICRAWL_API_KEY` first. Each `Document` carries `source`, `final_url`, `target_status`,
`credits_charged` and more in `metadata`; see [Metadata](#metadata).

### How do I build a RAG pipeline over a website with LangChain?

Collect the URLs, load them with `SpicrawlLoader`, split the documents with a LangChain text
splitter and add the chunks to a vector store. A complete example is under
[Index pages for RAG](#index-pages-for-rag).

### Can it load pages that need JavaScript?

Yes. Pass `scrape_options={"js_render": True}` to the loader. A plain fetch costs 1 credit and
JavaScript rendering costs 3. The agent tool lets the model set `js_render` itself when the first
attempt comes back empty.

### Does it crawl a whole website?

No. It fetches the URLs you pass. To cover a site, collect its URLs first and load them as a list.

### How do I give a LangChain agent access to web pages?

Pass `SpicrawlScrapeTool()` in the agent's `tools`, as in [Agent tool](#agent-tool). To give an
agent all 24 `spicrawl_*` tools (batch jobs, sessions, usage and more), connect it to the hosted
Spicrawl MCP server instead; see [Agent frameworks](https://docs.spicrawl.com/agents/frameworks).

### Does it support async?

Yes: `aload()` and `alazy_load()` on the loader, and the tool's async `ainvoke`.

### What happens when a page is blocked or the site returns an error?

A site that answers 4xx or 5xx raises `SpicrawlError` with `code == "TARGET_STATUS"`. Pass
`continue_on_failure=True` to log a warning and skip that URL. The agent tool returns the error text
to the model instead of raising. Failed requests cost 0 credits.

### Do I need an API key, and what does it cost?

Yes: create a key in the [Spicrawl dashboard](https://app.spicrawl.com/dashboard/keys). Credits are
charged only for successful requests; see [Credits](https://docs.spicrawl.com/credits).

### Is there a JavaScript version?

Yes: [`@spicrawl/langchain`](https://github.com/OfficialSpicrawl/langchain-spicrawl-js) for
LangChain.js, with the same classes and the same metadata keys.

### What license is it under?

MIT.

## Development

```bash
make test               # unit tests, HTTP mocked, sockets disabled
make lint               # ruff and mypy
make integration_test   # live; needs SPICRAWL_API_KEY, spends credits
```

## License

MIT
