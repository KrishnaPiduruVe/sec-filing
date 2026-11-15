# Start Corporate Atlas (Streamlit + FastAPI)

After downloading and extracting the code, open a terminal in the project folder.
You need **Python 3.10 or newer**, an internet connection, and credentials for your
chosen chat and embedding providers. The instructions below use Google for both.

## 1. Create and activate a virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2. Install dependencies

With the virtual environment activated, run:

```bash
python -m pip install -r requirements.txt
```

If you choose a different provider, install its corresponding extra as well.
Chat and embedding providers can be configured independently.

## 3. Configure the application

Copy `.env.example` to `.env` if `.env` does not already exist.

**macOS / Linux**

```bash
cp .env.example .env
```

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally:

- Set `SEC_USER_AGENT` to your name or organization and a real contact email.
- Set `PRIMARY_MODEL=GOOGLE` for the Google setup above.
- Set `GOOGLE_MODEL_PROVIDER=google_genai`, choose a `GOOGLE_MODEL_NAME`
  available to your account, and enter your `GOOGLE_API_KEY`.
- Set `EMBEDDING_PROVIDER=google_genai` and choose an `EMBEDDING_MODEL` available
  to your account. Set `EMBEDDING_API_KEY` if needed; matching Google chat and
  embedding providers can reuse the chat API key.

Keep `.env` private and do not commit it to Git. Chat and embedding calls use
your provider account and may incur charges. Keep the embedding model consistent
when building and querying an existing vector index.

## 4. Launch both services

From the project folder, with the virtual environment activated:

```bash
python run_app.py
```

Open **http://127.0.0.1:8501** in your browser. Keep the terminal running while
using the application. This address serves the application on your own computer.

## 5. Prepare a company and ask questions

1. Expand **Add a company to your research**.
2. Enter a ticker such as `AAPL`, or multiple tickers such as `AAPL, WFC`.
3. Click **Download**. The workflow automatically downloads filings, builds
   knowledge graphs, and builds the vector store. Progress appears on the page.
4. Wait until preparation completes, then enter a question and click
   **Explore insights**.

Existing downloads are reused with a message indicating the information is
already available. Missing preparation stages run automatically. The paced
vector build pauses between batches, so preparation may take several minutes.

Questions search available saved indexes by default. Mention a ticker or
recognized company name in the question to narrow the search. Use the top-right settings icon
to change retrieval or batch settings. **Usage** is at the bottom of
the page.

## Stop and restart

Press **Ctrl+C** in the launcher terminal to stop both services. Completed data
remains saved locally. Interrupted preparation cleans up new downloads where possible;
existing completed filings are preserved.

For subsequent launches, activate the existing environment and start the application;
you do not need to reinstall dependencies or recreate `.env`:

**macOS / Linux**

```bash
source .venv/bin/activate
python run_app.py
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
python run_app.py
```

If the browser shows `ERR_CONNECTION_REFUSED`, check that the launcher
is still running and use the URL printed in its terminal. If port 8501 is in use,
choose another port:

```bash
python run_app.py --ui-port 8502
```

Then open **http://127.0.0.1:8502**.

## API access and separate startup

The launcher starts Streamlit on **8501** and FastAPI on **8000**. API documentation
is available at **http://127.0.0.1:8000/docs**. Stop an existing Streamlit server
before launching both services on the same ports.

To run the services in separate terminals (activate `.venv` in each):

```bash
# Terminal 1: backend
python -m uvicorn corporate_atlas.api.app:app --host 127.0.0.1 --port 8000 --workers 1
```

```bash
# Terminal 2: interface
python -m streamlit run src/ui/corporate_atlas_ui/app.py --server.address 127.0.0.1
```

Streamlit calls FastAPI over HTTP. Only the backend accesses the filings,
knowledge graphs, Chroma database, token database, and provider credentials.
To use a different backend port, `python run_app.py --api-port 8001` configures
the frontend automatically. With separate startup, set `ATLAS_API_URL` in the
Streamlit process environment (for example `http://127.0.0.1:8001`).

This is a local application without user authentication. Keep both services
bound to localhost. Use **one FastAPI worker** and one backend instance for the
shared data directory. One background job runs at a time. The latest job and
up to 100 previous job snapshots are held in memory; restarting FastAPI clears
job history. Saved files and indexes remain on disk. This implementation does
not include a persistent queue, restart recovery, or multi-user isolation.

## Source layout

Backend code is under `src/python/corporate_atlas/`; Streamlit and its assets
are under `src/ui/corporate_atlas_ui/`. Both are installed by the editable
project install in step 2. After updating from the old flat layout, run:

```bash
python -m pip install -e . --no-deps
```

`python run_app.py` still starts both services. Existing configuration and data
stay at the project root; do not copy `.env` into the source folders.
