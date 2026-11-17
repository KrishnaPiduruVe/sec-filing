"""Corporate Atlas API. Use one worker because jobs and indexes are local."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import re
import threading
import time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
import requests
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from importlib.resources import files

from corporate_atlas.services.jobs import JobManager, inventory
from corporate_atlas.services.inventory import filing_information, company_label
from corporate_atlas.services.company_overview import company_overview
from corporate_atlas.core.llm_config import get_model_identifier
from corporate_atlas.core.token_usage import model_usage, usage_summary
from corporate_atlas.core.stock_market import (
    StockDataUnavailable,
    fetch_stock_snapshot,
    indexed_stock_companies,
)
from corporate_atlas.settings import SETTINGS

TICKER_PATTERN = (
    rf"^[A-Za-z][A-Za-z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}}$"
)

class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ChatUsageRequest(InputModel):
    job_ids: list[Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')]]


class PrepareRequest(InputModel):
    tickers: str = Field(min_length=1, max_length=SETTINGS.limits.ticker_input_chars)
    batch_size: int = Field(
        default=SETTINGS.indexing.batch_size,
        ge=1,
        le=SETTINGS.indexing.max_batch_size,
    )
    batch_delay: float = Field(
        default=SETTINGS.indexing.batch_delay_seconds,
        ge=0,
        le=SETTINGS.indexing.max_batch_delay_seconds,
        allow_inf_nan=False,
    )


class ChatHistoryMessage(InputModel):
    role: Literal['user', 'assistant']
    content: str = Field(
        min_length=1,
        max_length=SETTINGS.query.max_history_message_chars,
    )

    @field_validator('content')
    @classmethod
    def nonblank_content(cls, value):
        if not value.strip():
            raise ValueError('Chat history messages cannot be blank.')
        return value.strip()


class QueryRequest(InputModel):
    question: str = Field(min_length=1, max_length=SETTINGS.query.max_question_chars)
    mode: Literal['hybrid', 'graph', 'vector', 'usage'] = SETTINGS.query.default_mode
    top_k: int = Field(
        default=SETTINGS.query.default_top_k,
        ge=1,
        le=SETTINGS.query.max_top_k,
    )
    history: list[ChatHistoryMessage] = Field(
        default_factory=list,
        max_length=SETTINGS.query.max_history_messages,
    )

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


class StockRequest(InputModel):
    tickers: str = Field(min_length=1, max_length=SETTINGS.limits.ticker_input_chars)

    @field_validator("tickers")
    @classmethod
    def valid_tickers(cls, value):
        tickers = re.split(r"[\s,]+", value.strip().upper())
        if not tickers or any(
            not re.fullmatch(
                rf"[A-Z][A-Z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}}",
                ticker,
            )
            for ticker in tickers
        ):
            raise ValueError("Enter valid ticker symbols separated by commas or spaces.")
        unique_tickers = list(dict.fromkeys(tickers))
        if len(unique_tickers) > SETTINGS.limits.tickers_per_job:
            raise ValueError(
                f"Enter no more than {SETTINGS.limits.tickers_per_job} ticker symbols."
            )
        return " ".join(unique_tickers)


class FilingSelection(InputModel):
    ticker: str = Field(pattern=TICKER_PATTERN)
    accession: str = Field(pattern=r'^\d{10}-\d{2}-\d{6}$')


class DeleteRequest(InputModel):
    selections: list[FilingSelection] = Field(
        min_length=1,
        max_length=SETTINGS.limits.filing_delete_selections,
    )


class JobService:
    """Serialize mutations and retain a bounded history of completed jobs."""
    def __init__(self, manager=None):
        self.manager = manager or JobManager()
        self.lock = threading.RLock()
        self.history = OrderedDict()

    def start(self, action, data):
        with self.lock, self.manager.lock:
            previous = self.manager.snapshot()
            try:
                job = self.manager.start({'action': action, **data})
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(409, str(exc)) from exc
            if previous:
                self.history[previous['id']] = previous
                while len(self.history) > SETTINGS.limits.job_history_entries:
                    self.history.popitem(last=False)
            return job

    def get(self, job_id):
        with self.lock:
            current = self.manager.snapshot()
            if current and current['id'] == job_id:
                return current
            if job_id in self.history:
                return self.history[job_id]
        raise HTTPException(404, 'Job not found. Job history is cleared when the API restarts.')

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['status'] not in {'running', 'stopping'}:
                return job
            if job['action'] == 'delete_filings':
                raise HTTPException(409, 'Deletion cannot be interrupted once started.')
            self.manager.stop()
            return self.manager.snapshot()

    def check_readable(self):
        job = self.manager.snapshot()
        if job and job['status'] in {'running', 'stopping'} and job['action'] in {'prepare', 'stock', 'delete_filings'}:
            raise HTTPException(409, 'Company information is being updated. Try again when the task finishes.')

    def shutdown(self):
        job = self.manager.snapshot()
        if job and job['status'] in {'running', 'stopping'}:
            if job['action'] != 'delete_filings':
                self.manager.stop()
            deadline = (
                time.monotonic() + SETTINGS.jobs.shutdown_timeout_seconds
            )
            while time.monotonic() < deadline:
                if self.manager.snapshot()['status'] not in {'running', 'stopping'}:
                    break
                time.sleep(SETTINGS.jobs.shutdown_poll_interval_seconds)


def create_app(service=None):
    jobs = service or JobService()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(jobs.shutdown)

    application = FastAPI(title='Corporate Atlas API', version='1.0.0', lifespan=lifespan,
                          description='Local filing preparation, retrieval, and index management.')
    application.state.jobs = jobs
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=SETTINGS.api.trusted_hosts,
    )

    @application.middleware('http')
    async def local_browser_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin:
            parsed = urlparse(origin)
            allowed_origins = {
                f"http://{host}:{port}"
                for host in SETTINGS.api.allowed_origin_hosts
                for port in SETTINGS.api.allowed_origin_ports
            }
            allowed_origins.add(f"http://{request.headers.get('host', '')}")
            if parsed.scheme != 'http' or origin not in allowed_origins:
                return JSONResponse({'detail': 'Only the local application may call this API.'}, status_code=403)
        return await call_next(request)

    @application.get('/health', tags=['Status'])
    def health():
        return {'status': 'ok', 'application': 'Corporate Atlas'}

    @application.get('/config', tags=['Status'])
    def public_config():
        return {
            "indexing": {
                "batch_size": SETTINGS.indexing.batch_size,
                "batch_delay_seconds": SETTINGS.indexing.batch_delay_seconds,
            },
            "query": {
                "top_k": SETTINGS.query.default_top_k,
                "max_question_chars": SETTINGS.query.max_question_chars,
                "max_history_messages": SETTINGS.query.max_history_messages,
                "max_history_message_chars": SETTINGS.query.max_history_message_chars,
            },
            "frontend": {
                "job_poll_interval_ms": SETTINGS.frontend.job_poll_interval_ms,
                "stock_chart_ranges": SETTINGS.frontend.stock_chart_ranges,
            },
            "market_data": {
                "default_currency": SETTINGS.market_data.default_currency,
            },
        }

    @application.get('/status', tags=['Status'])
    def status():
        return {'job': jobs.manager.snapshot(), 'inventory': inventory()}

    @application.get('/jobs/current', tags=['Jobs'])
    def current_job():
        return {'job': jobs.manager.snapshot()}

    @application.get('/jobs/{job_id}', tags=['Jobs'])
    def get_job(job_id: str):
        return jobs.get(job_id)

    @application.post('/jobs/{job_id}/cancel', tags=['Jobs'])
    def cancel_job(job_id: str):
        return jobs.cancel(job_id)

    @application.post('/prepare', status_code=202, tags=['Jobs'])
    def prepare(data: PrepareRequest):
        return jobs.start('prepare', data.model_dump())

    @application.post('/stocks', status_code=202, tags=['Jobs'])
    def prepare_stocks(data: StockRequest):
        return jobs.start('stock', data.model_dump())

    @application.post('/query', status_code=202, tags=['Jobs'])
    def query(data: QueryRequest):
        return jobs.start('query', data.model_dump())

    @application.post('/filings/delete', status_code=202, tags=['Jobs'])
    def delete(data: DeleteRequest):
        return jobs.start('delete_filings', data.model_dump())

    @application.get('/filings', tags=['Data'])
    def filings():
        with jobs.lock:
            jobs.check_readable()
            return {'filings': filing_information()}

    @application.get('/companies/{ticker}/label', tags=['Data'])
    def label(ticker: str):
        if not re.fullmatch(TICKER_PATTERN, ticker):
            raise HTTPException(422, 'Invalid ticker.')
        return {'label': company_label(ticker.upper())}

    @application.get('/companies/{ticker}/overview', tags=['Data'])
    def overview(ticker: str):
        if not re.fullmatch(TICKER_PATTERN, ticker):
            raise HTTPException(422, 'Invalid ticker.')
        return company_overview(ticker.upper())

    @application.get('/stocks', tags=['Data'])
    def stocks():
        with jobs.lock:
            jobs.check_readable()
            companies = indexed_stock_companies()
            for company in companies:
                ticker = company['ticker']
                if company['name'] == ticker:
                    label = company_label(ticker)
                    if label != ticker:
                        company['name'] = label.removesuffix(f' ({ticker})')
            return {'companies': companies}

    @application.get('/stocks/{ticker}', tags=['Data'])
    def stock_snapshot(ticker: str, range: str = SETTINGS.market_data.default_range):
        if not re.fullmatch(TICKER_PATTERN, ticker):
            raise HTTPException(422, 'Invalid ticker.')
        if range not in SETTINGS.market_data.supported_ranges:
            raise HTTPException(422, 'Unsupported chart range.')
        try:
            return fetch_stock_snapshot(ticker.upper(), range_name=range)
        except StockDataUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise HTTPException(
                    503,
                    'Stock market-data providers are rate limiting requests. Wait before refreshing the quote.',
                ) from exc
            raise HTTPException(502, f'Unable to fetch current market data for {ticker.upper()}.') from exc
        except requests.RequestException as exc:
            raise HTTPException(502, f'Unable to fetch current market data for {ticker.upper()}.') from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @application.post('/usage/chat', tags=['Data'])
    def chat_usage(data: ChatUsageRequest):
        return {'models': model_usage(job_ids=data.job_ids)}

    @application.get('/usage', tags=['Data'])
    def usage(job_id: str | None = None):
        if job_id is not None:
            return {'models': model_usage(job_id)}
        try:
            chat_model = get_model_identifier()
        except ValueError:
            chat_model = None
        columns = ['operation', 'input_tokens', 'output_tokens', 'events', 'estimated_events']
        return {
            'rows': [dict(zip(columns, row)) for row in usage_summary()],
            'models': model_usage(),
            'chat_model': chat_model,
        }

    frontend = Path(
        str(files('corporate_atlas_ui') / SETTINGS.paths.frontend_static_dir)
    )
    if (frontend / 'index.html').is_file():
        application.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')

    return application


app = create_app()
