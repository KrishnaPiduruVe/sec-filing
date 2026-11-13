# SEC Quarterly Filing Knowledge Graph

Fetches the latest 10-Q for each requested ticker from SEC EDGAR, extracts
filing facts into local NetworkX graphs, and answers questions grounded only
in retrieved graph triples.

## Setup

Use Python 3.10 or newer. Install the core dependencies and the integration
for the provider selected in `.env`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[google,vector]"
Copy-Item .env.example .env
```

Set `PRIMARY_MODEL` to one of the configured prefixes and provide that
provider's API key. Available extras are `google`, `openai`, `anthropic`, and
`groq`; use `.[all-providers]` to install every integration. Each uses
`<PREFIX>_MODEL_PROVIDER`, `<PREFIX>_MODEL_NAME`, and `<PREFIX>_API_KEY`.
`init_chat_model` selects the implementation from the active provider/model
configuration.

Embedding selection is independent of the chat model and is controlled by
`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and `EMBEDDING_API_KEY` in `.env`.
`EMBEDDING_PROVIDER` selects the embedding integration independently from the
chat model. Install the matching provider integration; `.[google,vector]`
includes the Google GenAI, Chroma, and OpenAI integrations. Google GenAI and
other providers supported by LangChain can be selected in `.env` without
changing the query/indexing code. Set optional provider-specific arguments in
`EMBEDDING_OPTIONS` as a JSON object. If the embedding and chat providers match,
the configured chat API key can be reused; otherwise set
`EMBEDDING_API_KEY` or the provider's usual environment-based credentials.

Before fetching, replace `SEC_USER_AGENT` in `.env` with an identifying
application or organization name and a real contact email address. Every SEC
request sends that User-Agent.

## Fetch filings

```powershell
python sec_quarterly_filings.py
python sec_quarterly_filings.py AAPL WFC MSFT
```

The primary HTML filing and all PDF files listed in its SEC accession index
are saved in `sec_filings/<TICKER>/<ACCESSION>/`.

## Build knowledge graphs

```powershell
python build_knowledge_graph.py
python build_knowledge_graph.py --tickers AAPL WFC
```

Each HTML filing is converted to text, chunked with overlap, and processed
using Pydantic structured output (30,000-character chunks with 500-character
overlap by default). Graphs are written to
`knowledge_graphs/<TICKER>.graphml` and `knowledge_graphs/combined.graphml`.
PDF attachments are preserved by the fetcher but are not parsed by the graph
builder.

## Build the vector index

```powershell
python build_vector_store.py
python build_vector_store.py --tickers AAPL WFC
```

This converts each downloaded HTML filing to readable text, splits it into
overlapping chunks, embeds those chunks, and persists them in `chroma_db/`.
Rebuilding selected tickers updates their chunks and removes stale chunks
without replacing other tickers' vectors.

## Query filings

```powershell
python query_graph.py "What risks did the company report?"
python query_graph.py --ticker AAPL "What was the revenue trend?"
python query_graph.py --tickers AAPL,WFC "Compare the reported risks"
python query_graph.py --mode graph "What risks did the company report?"
python query_graph.py --mode vector "What risks did the company report?"
python query_graph.py
```

The default `hybrid` mode combines ranked graph triples with semantically
retrieved filing excerpts. `--mode graph` retains the original graph-only
keyword retrieval, and `--mode vector` searches only Chroma. Use
`--ticker AAPL` or `--tickers AAPL,WFC` to limit retrieval. Answers are grounded
only in retrieved filing context and the model is instructed to say when that
context is insufficient.

## Token usage

Every graph extraction and answer call records input/output token counts in
`token_usage.sqlite3` (override with `TOKEN_USAGE_DB`). Provider-reported chat
usage is stored when available; estimated counts are marked as estimated.
Filing and query embeddings are reported separately; their input usage is
estimated locally with `tiktoken`, and vector embeddings do not generate output
tokens. View totals with:

```powershell
python token_usage.py
```

Downloaded filings, generated graphs, virtual environments, and `.env` are
ignored by Git. Keep API keys and actual contact information in `.env`, not in
tracked files.
