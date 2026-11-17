# Corporate Atlas: React + FastAPI

See [readme_ui.md](readme_ui.md) for installation and configuration.

```powershell
python -m pip install -r requirements.txt
python run_app.py
```

Open http://127.0.0.1:8501. The React application and FastAPI API are served
from the same local origin; API documentation is at
http://127.0.0.1:8501/docs. No SEC, market-data, or model requests are made
merely by starting the application.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Backend readiness |
| `GET /config` | Safe UI defaults (index batch, query top-k, chart ranges, currency, and polling interval) |
| `GET /status` | Current job and local artifact inventory |
| `POST /prepare` | Download SEC filings and build the paced vector index |
| `POST /stocks` | Fetch and index stock snapshots for one or more tickers |
| `GET /stocks` | List indexed stock snapshots |
| `GET /stocks/{ticker}?range=1mo` | Current quote and chart series |
| `POST /query` | Ask a question using saved context; accepts a bounded recent `history` of user/assistant messages |
| `GET /jobs/current` | Most recent job |
| `GET /jobs/{id}` | Job progress, output, and completion status |
| `POST /jobs/{id}/cancel` | Cancel a query, preparation, or stock indexing job |
| `GET /filings` | List downloaded fiscal quarters and indexes |
| `POST /filings/delete` | Delete explicitly selected ticker/accession pairs |
| `GET /companies/{ticker}/label` | Filing registrant name |
| `GET /usage` | Token usage totals |

Alpaca is the primary source for stock prices and OHLCV bars. Set
`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in `.env`; if credentials are
missing or Alpaca is unavailable, the app falls back to Yahoo Finance. When
Alpaca succeeds, Yahoo Finance is also queried opportunistically to supplement
fundamentals such as market cap, P/E, and 52-week high/low; those fields may be
unavailable when Yahoo is rate-limiting requests. Alpaca's free Basic
market-data plan provides IEX coverage, not consolidated SIP coverage. The
chart renders OHLC candlesticks and volume bars. Snapshots are persisted in the
existing Chroma collection with `source=stock_market`; refreshing a chart does
not embed it.

The web preparation workflow downloads filings and builds vectors without
running token-consuming graph extraction. Research chat defaults to vector
retrieval. Choose **Token usage** in the chat scope to ask the LLM about usage
metrics in the local SQLite database. Generated SQL is restricted to a
read-only connection and the `token_usage` table. Worker logs stay hidden until
you click **Show logs**. During indexing, hover over the ticker button's
spinner to reveal the stop control. The top-bar theme toggle switches between
light and dark appearance. Research follow-ups use recent messages from the
current chat to resolve references; retrieved filing excerpts remain the
factual source. Assistant responses render Markdown, including comparison
tables; chart requests render accessible bar charts from supported figures.
Token-consumption questions and their contextual follow-ups automatically use
the read-only token-usage database.
Use **New chat** to clear the conversation and start without that context.

Example requests:

```powershell
curl.exe -X POST http://127.0.0.1:8501/prepare `
  -H "Content-Type: application/json" `
  -d '{"tickers":"AAPL","batch_size":5,"batch_delay":0}'

curl.exe -X POST http://127.0.0.1:8501/stocks `
  -H "Content-Type: application/json" `
  -d '{"tickers":"AAPL"}'
```

Long-running requests return HTTP 202 with a job ID. Poll `GET /jobs/{id}` to
confirm completion. The React interface prepares SEC vectors first, then
fetches and indexes the stock snapshot.
The normal pause between successful filing-vector batches defaults to zero.
Provider quota retries still use increasing backoff, so embedding or market-data
rate limits can extend the job. Downloading SEC filings and embedding chunks
still require network and model work; opt in to the expandable
console to view worker output and workflow stages.

Keep the service bound to localhost. The backend has no authentication,
supports one active job at a time, and retains bounded job history in memory.
Use a single backend process/worker per data directory. A persistent task queue
and restart recovery are outside this local implementation. Do not run
index-writing CLI tasks concurrently with the API.

Non-secret runtime defaults are centralized in
`src/python/corporate_atlas/config.toml`. The backend and frontend development
server can use another TOML file through `ATLAS_CONFIG_FILE`; credentials stay
in `.env` and are not returned by `GET /config`.

## Frontend development

The React and TypeScript source is in `frontend/`. The built UI is served from
`src/ui/corporate_atlas_ui/static/` and included as Python package data. To
rebuild it after changing frontend code, install Node.js, then run:

```powershell
cd frontend
npm ci
npm run build
```

Tests (mocked providers and temporary data):

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

The backend package is under `src/python/corporate_atlas/`; the
`corporate_atlas_ui` package supplies the bundled frontend assets. Install the
project with `python -m pip install -e .` so imports resolve.
