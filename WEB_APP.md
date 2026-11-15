# Corporate Atlas: Streamlit + FastAPI

See [readme_ui.md](readme_ui.md) for full installation and configuration.

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_app.py
```

Interface: http://127.0.0.1:8501

API documentation: http://127.0.0.1:8000/docs

Streamlit handles presentation and HTTP requests. FastAPI owns jobs, data access,
and subprocesses running the existing filing/index/query scripts. Long actions
return HTTP 202 with a job ID, and the interface polls progress. No SEC or model
requests are made merely by starting either server.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Backend readiness |
| `GET /status` | Current job and local artifact inventory |
| `POST /prepare` | Download, graph, and paced vector workflow |
| `POST /query` | Ask a question using saved context |
| `GET /jobs/current` | Most recent job |
| `GET /jobs/{id}` | Job progress, output, and completion status |
| `POST /jobs/{id}/cancel` | Cancel a query or preparation; deletion is not cancellable |
| `GET /filings` | List downloaded fiscal quarters and indexes |
| `POST /filings/delete` | Delete explicitly selected ticker/accession pairs |
| `GET /companies/{ticker}/label` | Filing registrant name |
| `GET /usage` | Token usage totals |

Example preparation request:

```bash
curl -X POST http://127.0.0.1:8000/prepare \
  -H 'Content-Type: application/json' \
  -d '{"tickers":"AAPL","batch_size":5,"batch_delay":65}'
```

Use the returned `id` with `GET /jobs/{id}`. A successful 202 response means the
job was accepted; check its final status to confirm completion.

Keep both services on localhost. The backend has no authentication, supports
one active job at a time, and retains bounded job history in memory. Use a
single backend process/worker per data directory. A persistent task queue and
restart recovery are outside this local implementation. The existing CLI
scripts remain runnable independently, but do not run index-writing CLI tasks
concurrently with the API.

Tests (mocked providers and temporary data):

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

Source packages: `corporate_atlas.api` and `corporate_atlas.services` live in
`src/python`; `corporate_atlas_ui` lives in `src/ui`. Install the project with
`python -m pip install -e .` so imports resolve. See the project structure in
[README.md](README.md) for the full layout.
