# SEC Filing Workspace (Streamlit)

This local, single-page application wraps the existing command-line scripts.
Existing source files, configuration, and indexes are unchanged by installation.
Tasks write their normal output files when you run them.

From the repository root on macOS/Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements-web.txt
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Open **http://127.0.0.1:8501**. On Windows, activate with
`.\.venv\Scripts\Activate.ps1` instead. Core project dependencies and the
provider/vector integrations must already be installed, for example
`python -m pip install -e ".[google,vector]"`.

Configure credentials, chat/embedding models, and SEC_USER_AGENT in the existing
`.env`. Keys stay on the Python side; the UI does not display them. Use the same
embedding provider/model when building and querying an existing vector index.

1. Enter a ticker (or comma-separated tickers) in the main page and click **Download**.
2. An animated workflow appears only after submission: download filings → build
   knowledge graphs → build vector store. Each stage turns green when complete.
3. Existing downloads are reused with an “already have downloaded information”
   message. Existing graphs and complete vector chunk IDs are reused too;
   missing stages run automatically. A repeat download reuses local data rather
   than checking EDGAR for a newer quarter.
4. Ask a question. By default it searches all available saved graph and vector
   context, independent of the ticker in the Download form. Mention a ticker
   or recognized company/registrant name in the question to filter it. Hybrid
   uses both sources when present, or falls back to the available source.
5. Read formatted answers, save answer text, or expand preparation details for
   logs. Use the Stop button to interrupt a task.

The sidebar is collapsed by default. Open it for retrieval mode, context size,
and paced batching settings. Streamlit's Deploy shortcut is hidden.

Each task stops automatically on completion. The page and server remain open
for the next task. Closing a browser tab does not stop a running task; use the
Stop button. Stop the server with Ctrl+C in its terminal. Completed batches may
remain after stopping or failure. Reruns re-embed all chunks using stable IDs;
indexing is not a skip-completed resume mechanism.

Only one task runs at a time across browser tabs. The latest task output is
kept in memory (up to 200,000 characters) until the next task or server restart.
Downloaded filings, graphs, vectors, and usage records persist in their existing
folders. Model and embedding operations can incur charges. Missing indexes,
credentials, provider errors, and quota errors appear in the output pane.
The vector-directory indicator only checks folder presence, not index contents.

Keep this application bound to localhost: it runs tasks using your local
credentials and is intended for your own computer.

Offline tests (no SEC or provider calls):

```bash
python -m unittest discover -s tests -p 'test_sec_*.py'
```
