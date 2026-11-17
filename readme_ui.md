# Corporate Atlas — React + FastAPI

Corporate Atlas uses React for the interface and FastAPI for jobs and data access.
The built interface and API run together on **http://127.0.0.1:8501**.

## Requirements

- Python **3.10+**.
- [Node.js 22.12+](https://nodejs.org/en/download) and npm for building/developing the frontend.
- Credentials for your chat and embedding providers and an identifying SEC User-Agent.

## 1. Create and activate the Python environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2. Install and build

Run from the repository root:

```bash
python -m pip install -r requirements.txt
npm --prefix src/ui ci
npm --prefix src/ui run build
```

`requirements.txt` installs Python packages. `src/ui/package.json` and its lockfile
manage React/Vite dependencies through npm. These are separate ecosystems, not
separate Python requirements files. Generated `node_modules/` and `dist/` are
ignored by Git. Every new checkout needs a frontend build.

## 3. Configure credentials

Copy `.env.example` to `.env` only if `.env` does not already exist. Edit it locally:

- `SEC_USER_AGENT`: identifying name/organization and a real contact email.
- `PRIMARY_MODEL`: the configured chat-provider prefix, such as `GOOGLE`.
- That prefix's model provider, accessible model name, and API key.
- `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and `EMBEDDING_API_KEY` if needed.

The default install includes Google and vector integrations. Install another
provider extra if selected. Credentials stay in the Python backend; never put
keys in React source or `VITE_` environment variables. Keep the embedding model
consistent between indexing and querying an existing Chroma collection.

## 4. Start the application

```bash
python run_app.py
```

Open **http://127.0.0.1:8501**. API documentation is at
**http://127.0.0.1:8501/docs**. FastAPI serves both the compiled React app and API,
so no separate frontend server or Node process is required after the build.

A second launch recognizes an already-running Corporate Atlas instance. For
another port:

```bash
python run_app.py --port 8502
```

Stop any older servers still occupying the selected port before launching.
For direct backend startup:

```bash
python -m uvicorn corporate_atlas.api.app:app --host 127.0.0.1 --port 8501 --workers 1
```

## 5. Research workflow

- **Overview** opens with real, source-linked company snapshots. Select a company
  from the indexed ticker tabs to see annual revenue, net income, growth,
  profitability, and a general company description.
- **Compare companies** compares up to four tracked companies. Reporting-period
  dates stay visible because fiscal calendars can differ.
- **Add company** integrates a public company profile and annual financial facts.
  Starter companies can be searched by name; additional companies are looked up
  by their US-listed ticker. This does not automatically run model-based indexing.
- **Refresh data** refreshes Wikimedia descriptions and SEC annual financial data.
  General profiles use Wikimedia's public REST API without an additional key.
  The sources and retrieval dates are linked on the page; cached data is not a
  live quote feed. Financial snapshots are six annual periods where available.
- **Research assistant** accepts your own question or a suggested prompt. Its
  selected-company scope combines public profile/financial context with local
  vector evidence when indexed. Switch scope to search all saved filings.
- **Download** in the left pane prepares full SEC filings. The workflow runs
  download → paced vectors, in the background with automatic page updates.
- **Usage** displays token totals. **Available company information** shows saved tickers.
- Research descriptions and charts stay available independently of a filing index.
  Removing a downloaded quarter does not remove public source snapshots.
- Color mode (light/dark), retrieval, and batch settings are in the left pane.

Company overview text is attributed to Wikipedia under CC BY-SA, with links to
source articles and their histories. Annual charts come from SEC XBRL facts;
comparative-period entries are reconciled by reporting dates, and missing values
are not filled with zero. Use the source details to inspect exact financial values.

## Stop and restart

Press **Ctrl+C** in the launcher terminal. Completed data remains saved. Interrupted
preparation attempts to clean up new downloads/indexes; existing completed data is
preserved. Closing the browser does not stop a job.

For subsequent runs, activate `.venv` and run `python run_app.py`. Rebuild with
`npm --prefix src/ui run build` whenever frontend source changes.

## Frontend development

Run the backend on 8501, then start Vite in a second terminal:

```bash
npm --prefix src/ui run dev
```

Open the Vite URL (normally http://127.0.0.1:5173). Vite proxies API requests to
8501; set `ATLAS_API_URL` in its process environment to change that target.
`ATLAS_UI_DIST` lets the backend/launcher use a different built-asset directory.

## Exploring companies

The left pane starts collapsed. Use its expand button to access settings,
company additions, downloads, fiscal-quarter deletion, and token usage. Add a
company by entering its ticker or choosing one of the listed public companies.
Browse all opens a catalog filter; there is no workspace overview page.

The landing page selects the first tracked
company. Filter indexed companies by name or sector, and open one to inspect it.
Use Download in the left pane to add another ticker. Browse all opens the company panel; Close hides it. The tab list and available company information both come from Chroma. Company tabs contain
tickers; financial charts use reported annual data, not simulated stock prices.
Use **3Y**, **5Y**, or **All** to change the annual financial history shown in the
charts and source table. Suggested questions fill the research assistant below
the analysis; answers run through FastAPI with the scope configured in the left
pane. Fiscal periods and source dates remain visible.

## Tests and source layout

```bash
python -m pytest -q
npm --prefix src/ui test
npm --prefix src/ui run build
```

Backend: `src/python/corporate_atlas/`. React: `src/ui/src/`. Public branding:
`src/ui/public/`. `.env`, downloaded filings, Chroma, and token records stay
at the project root. Keep the app on localhost: it has no user authentication.
Use one backend worker per data directory. Job history is in memory and resets
when the backend restarts; saved artifacts persist.
