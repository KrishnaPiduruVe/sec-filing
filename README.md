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
python -m pip install -e ".[google]"
Copy-Item .env.example .env
```

Set `PRIMARY_MODEL` to one of the configured prefixes and provide that
provider's API key. Available extras are `google`, `openai`, `anthropic`, and
`groq`; use `.[all-providers]` to install every integration. Each uses
`<PREFIX>_MODEL_PROVIDER`, `<PREFIX>_MODEL_NAME`, and `<PREFIX>_API_KEY`.
`init_chat_model` selects the implementation from the active provider/model
configuration.

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

## Query graphs

```powershell
python query_graph.py "What risks did the company report?"
python query_graph.py --ticker AAPL "What was the revenue trend?"
python query_graph.py --tickers AAPL,WFC "Compare the reported risks"
python query_graph.py
```

By default, the query tool merges all available per-ticker GraphML files,
then ranks graph triples against the question's locally tokenized keywords.
Use `--ticker AAPL` or `--tickers AAPL,WFC` to limit the graphs searched. The
selected model answers using only retrieved triples and is instructed to say
when they do not support an answer.

Downloaded filings, generated graphs, virtual environments, and `.env` are
ignored by Git. Keep API keys and actual contact information in `.env`, not in
tracked files.
