# Corporate Atlas

Research public companies using SEC filings, company profiles, annual financial
charts, and vector retrieval from Chroma. React provides the interface; FastAPI
runs background preparation and answer jobs.

## Install and run

Install Python 3.10+ and Node.js 22.12+ with npm. From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
npm --prefix src/ui ci
npm --prefix src/ui run build
python run_app.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. Configure
`.env` before starting: set `SEC_USER_AGENT` to your application name and real
contact email, choose `PRIMARY_MODEL`, and supply that provider's credentials.
The provider uses `<PREFIX>_MODEL_PROVIDER`, `<PREFIX>_MODEL_NAME`, and
`<PREFIX>_API_KEY`. Supported integrations include Google, OpenAI, Anthropic, and
Groq; install the corresponding project extra if needed.

Embeddings are independent of the answer model: configure `EMBEDDING_PROVIDER`,
`EMBEDDING_MODEL`, and `EMBEDDING_API_KEY`, with optional `EMBEDDING_OPTIONS` JSON.
Changing embedding models requires rebuilding the vector index. The default
requirements include Google, Chroma, OpenAI, and test integrations.

Open http://127.0.0.1:8501. API documentation is at `/docs`. Ctrl+C in the launch
terminal stops the app. Node is needed to build the frontend, not to serve an
existing build. See [UI setup](readme_ui.md) and [API reference](WEB_APP.md).

## Research and downloads

Chroma is the single source of available companies. No starter or cached-only
company is shown. The first indexed company is selected on launch. Ticker tabs switch companies;
**Browse all** opens the company catalog, with filtering.
The left pane contains company additions, downloads, settings, saved tickers,
and token usage. Light/dark mode is saved in your browser.

**Download** accepts a ticker and starts a background preparation job:

1. Fetch the latest quarterly filing HTML and available PDF attachments from SEC.
2. Fetch and cache the Wikimedia company profile and SEC annual financial facts,
   and index the available source content into Chroma. Source outages show warnings. Either SEC content or a verified Wikimedia
   profile can be indexed on its own; if neither is usable, a popup asks you to
   check the ticker and lists SEC EDGAR and Wikimedia.
3. Split readable HTML into 4,000-character chunks with 400-character overlap,
   embed them, and persist them in Chroma.

Existing downloads and complete vectors are reused. Vector batches default to
five chunks with a 65-second pause. On failure or interruption the pipeline
attempts to clean up newly created downloads and their vectors, preserving old
data. PDFs are retained as attachments; only HTML is indexed.

You can switch companies and read charts while preparation runs. A compact
background status shows progress, and saved tickers update automatically on
completion. Questions, charts, usage, and company refreshes remain available during a
download. A separate query job runs against indexed data. Another download is
disabled until the current preparation finishes.

Answers use semantically retrieved filing excerpts, with filing identifiers as
citations. Selected-company research also includes cached public profiles and
annual financial facts. All saved filing evidence is searched unless the
question names a ticker or company. No relationship database is required.

Wikimedia supplies general company descriptions (CC BY-SA attribution is shown),
and SEC company facts supply annual USD revenue and net income. Charts show
reporting periods and source timestamps. Annual fiscal calendars may differ;
these are historical financial results, not stock-price feeds or forecasts.
Public profiles and financial snapshots are stored in Chroma. A company can
appear with only Wikimedia content when SEC filings are unavailable.

## Command line

```bash
python -m corporate_atlas.services.prepare --tickers AAPL MSFT
python -m corporate_atlas.core.sec_quarterly_filings AAPL MSFT
python -m corporate_atlas.core.build_vector_store_paced --tickers AAPL --batch-size 5 --batch-delay 65
python -m corporate_atlas.services.query "What risks did Apple report?"
python -m corporate_atlas.services.research_query --tickers AAPL -- "Explain its revenue trend."
python -m corporate_atlas.core.token_usage
```

Token usage includes embedding and answer calls. Usage records are retained when
company downloads are removed. The API also supports deleting explicit filing
accessions. Available tickers come from the Chroma collection.

## Source layout and tests

Python: `src/python/corporate_atlas/` (`api`, `services`, `core`, and bundled data).
React: `src/ui/src/`. `.env`, `sec_filings/`, `chroma_db/`, and usage records stay
in the project root. `ATLAS_DATA_DIR` changes the runtime data directory.

```bash
python -m pytest -q
npm --prefix src/ui test
npm --prefix src/ui run build
```

Keep the application on localhost and run one backend worker per data directory.
The app has no authentication or multi-user isolation. One preparation and one
query may run concurrently; deletions remain exclusive. Jobs are held in memory;
restarting the server clears job history. Avoid separate CLI index writers while
an API job is active.
