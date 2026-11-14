# Start the Streamlit application

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
python -m pip install -e ".[google,vector]"
python -m pip install -r requirements-web.txt
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

## 4. Launch Streamlit

From the project folder, with the virtual environment activated:

```bash
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
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
recognized company name in the question to narrow the search. Open the collapsed
sidebar to change retrieval or batch settings. **Usage** is at the bottom of
the page.

## Stop and restart

Press **Ctrl+C** in the terminal to stop the web server. Downloaded filings and
completed indexes remain saved locally.

For subsequent launches, activate the existing environment and start Streamlit;
you do not need to reinstall dependencies or recreate `.env`:

**macOS / Linux**

```bash
source .venv/bin/activate
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

If the browser shows `ERR_CONNECTION_REFUSED`, check that the Streamlit command
is still running and use the URL printed in its terminal. If port 8501 is in use,
choose another port:

```bash
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

Then open **http://127.0.0.1:8502**.
