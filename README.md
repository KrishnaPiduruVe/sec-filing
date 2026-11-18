# SEC Quarterly Filing Knowledge Graph

Fetches the latest 10-Q for each requested ticker from SEC EDGAR, extracts
filing facts into local NetworkX graphs, and answers questions grounded in
retrieved filing and indexed stock context.

## Web application

Corporate Atlas uses a React interface served by FastAPI, which also provides
background jobs and data access. After installing the core/provider dependencies
and configuring `.env` as below:

```bash
python -m pip install -r requirements.txt
python run_app.py
```

Open http://127.0.0.1:8501. API documentation: http://127.0.0.1:8501/docs.
See [UI setup](readme_ui.md) and [API overview](WEB_APP.md) for details.
The web preparation workflow skips graph extraction and uses vector retrieval
by default; the graph-building CLI remains available as an explicit operation.

### Stop the web application

Press **Ctrl+C** in the terminal where you ran `python run_app.py`. Wait for
the server to report that shutdown is complete.

On macOS or Linux, you can also stop it from another terminal.

1. Find the process listening on the app's port. Replace `8501` with the port
   you passed to `--port` if you used a different one.

   ```bash
   lsof -nP -iTCP:8501 -sTCP:LISTEN
   ```

2. Confirm the PID belongs to the Corporate Atlas Uvicorn process, then send
   it a termination signal. Replace `12345` with the PID from the first step.

   ```bash
   ps -p 12345 -o command=
   kill -TERM 12345
   ```

3. Run the same `lsof` command again. No output means the port is free.

## Setup

Use Python 3.10 or newer. Install the core dependencies and the integration
for the provider selected in `.env`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
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

## Runtime configuration

Non-secret operational settings are centralized in
[`src/python/corporate_atlas/config.toml`](src/python/corporate_atlas/config.toml).
It includes service hosts and ports, provider endpoints, timeouts, SEC pacing,
stock-data defaults, chunking and embedding batch behavior, query limits, and
local data paths. Python and the Vite development server read the same file.
Set `ATLAS_CONFIG_FILE` to an alternate TOML file when deploying or testing
with different settings. The file is validated at startup; invalid or missing
settings are reported rather than silently replaced.

Keep credentials and other secrets in `.env` or the process environment, never
in `config.toml`. Existing environment overrides such as `ATLAS_PROJECT_ROOT`,
`ATLAS_DATA_DIR`, and `TOKEN_USAGE_DB` continue to take precedence for their
respective paths.

## Fetch filings

```powershell
python -m corporate_atlas.core.sec_quarterly_filings
python -m corporate_atlas.core.sec_quarterly_filings AAPL WFC MSFT
```

The primary HTML filing and all PDF files listed in its SEC accession index
are saved in `sec_filings/<TICKER>/<ACCESSION>/`.

## Build knowledge graphs

```powershell
python -m corporate_atlas.core.build_knowledge_graph
python -m corporate_atlas.core.build_knowledge_graph --tickers AAPL WFC
```

Each HTML filing is converted to text, chunked with overlap, and processed
using Pydantic structured output (30,000-character chunks with 500-character
overlap by default). Graphs are written to
`knowledge_graphs/<TICKER>.graphml` and `knowledge_graphs/combined.graphml`.
PDF attachments are preserved by the fetcher but are not parsed by the graph
builder.

## Build the vector index

```powershell
python -m corporate_atlas.core.build_vector_store
python -m corporate_atlas.core.build_vector_store --tickers AAPL WFC
```

This converts each downloaded HTML filing to readable text, splits it into
overlapping chunks, embeds those chunks, and persists them in `chroma_db/`.
Rebuilding selected tickers updates their chunks and removes stale chunks
without replacing other tickers' vectors.

## Query filings

```powershell
python -m corporate_atlas.core.query_graph "What risks did the company report?"
python -m corporate_atlas.core.query_graph --ticker AAPL "What was the revenue trend?"
python -m corporate_atlas.core.query_graph --tickers AAPL,WFC "Compare the reported risks"
python -m corporate_atlas.core.query_graph --mode graph "What risks did the company report?"
python -m corporate_atlas.core.query_graph --mode vector "What risks did the company report?"
python -m corporate_atlas.core.query_graph
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
python -m corporate_atlas.core.token_usage
```

Downloaded filings, generated graphs, virtual environments, and `.env` are
ignored by Git. Keep API keys and actual contact information in `.env`, not in
tracked files.

## Project structure

```text
src/
  python/corporate_atlas/
    api/app.py          # FastAPI application, request models, and endpoints
    services/           # Jobs, preparation, queries, inventory, and deletion
    core/               # SEC client, graph extraction, vectors, models, token usage
    paths.py            # Shared configuration and data paths
    launcher.py         # Starts the backend and interface
  ui/corporate_atlas_ui/
    static/             # Built React application served by FastAPI
frontend/               # React + TypeScript frontend source
run_app.py              # Thin launcher; python run_app.py still works
tests/                  # Core, service, API, client, and UI integration tests
```

The backend and UI are separate Python packages discovered by setuptools.
Install the checkout with `python -m pip install -r requirements.txt` before
running it. If updating an existing checkout to this layout, reinstall it with
`python -m pip install -e . --no-deps` to refresh package discovery.

Run backend commands as modules, for example:

```bash
python -m corporate_atlas.core.sec_quarterly_filings AAPL
python -m corporate_atlas.core.build_knowledge_graph --tickers AAPL
python -m corporate_atlas.core.build_vector_store_paced --tickers AAPL
```

`.env`, `sec_filings/`, `knowledge_graphs/`, `chroma_db/`, and the usage database
remain at the repository root. Moving source files does not move existing data.
Paths are resolved independently of the working directory. Set
`ATLAS_PROJECT_ROOT` to override the configuration/project directory, or
`ATLAS_DATA_DIR` to store data separately (relative paths resolve under the
project root). For non-editable package deployments, set `ATLAS_PROJECT_ROOT`
explicitly to your application configuration directory.
