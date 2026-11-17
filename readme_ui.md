# Start Corporate Atlas (React + FastAPI)

Corporate Atlas runs as a single local FastAPI service that serves the React
interface and its API. Python 3.10 or newer and the selected chat/embedding
provider credentials are required. Node.js is only needed when rebuilding the
frontend; the launcher runs the checked-in bundled frontend.

## 1. Install Python dependencies

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Configure the application

Copy `.env.example` to `.env` if needed and edit it locally:

- Set `SEC_USER_AGENT` to your name or organization and a real contact email.
- Set `PRIMARY_MODEL` and that provider's model name and API key.
- Set `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and embedding credentials if
  they differ from the chat provider.

Keep `.env` private and do not commit it. Provider requests may incur charges.
Keep the embedding model consistent with the existing vector index.

Non-secret operational settings are in
`src/python/corporate_atlas/config.toml`. Set `ATLAS_CONFIG_FILE` to a
different TOML file to override local paths, endpoints, timeouts, indexing
defaults, and other runtime settings. Keep API keys and credentials in `.env`,
not in the TOML file.

## 3. Launch

```powershell
python run_app.py
```

Open **http://127.0.0.1:8501**. The React frontend and backend API share that
origin; API documentation is at **http://127.0.0.1:8501/docs**. Keep the
launcher running while using the app. Choose another local port with
`python run_app.py --port 8502`.

The left panel lists companies with stock information already indexed in the
vector database. Enter a ticker there to download and index its SEC filing
information and current stock snapshot. Select a saved company to view the
OHLC candlestick chart and company information. Use the chat scope selector to
ask questions over saved SEC/stock vectors or local token-usage metrics.

Stock quotes and chart bars use Alpaca when `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY` are configured in `.env`, with Yahoo Finance as a fallback.
Yahoo Finance is also used opportunistically to supplement Alpaca's quote with
fundamentals such as market cap and 52-week high/low; those fields may be
unavailable when Yahoo is rate-limiting requests. Alpaca's free Basic plan uses
IEX data rather than consolidated SIP data. Market information may be delayed
or unavailable and is for research purposes only; confirm figures with a
licensed market-data provider before relying on them.

The web app skips knowledge-graph generation to avoid its extra LLM calls and
uses vector retrieval by default. During indexing, click **Show logs** to open
the optional console. Hover over the indexing spinner in the ticker button to
reveal the stop control and cancel the active preparation/indexing job. Choose
light or dark appearance with the theme toggle in the top bar.

## Rebuild the React frontend

The React/TypeScript source is in `frontend/`. Node.js is not needed to launch
the app when the bundled files in `src/ui/corporate_atlas_ui/static/` are
present. To rebuild after a frontend change:

```powershell
cd frontend
npm ci
npm run build
```

## Stop and restart

Press **Ctrl+C** in the launcher terminal to stop the service. Saved filings,
existing graphs, vector data, and usage history remain on disk. Activate the existing
Python environment and run `python run_app.py` for future sessions; you do not
need to reinstall Python dependencies or recreate `.env`.

This is a local application without user authentication. Keep the service
bound to localhost and use one backend worker per shared data directory. One
background job runs at a time. Job history is in memory and clears when the
service restarts; saved indexes remain on disk.
