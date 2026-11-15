"""Corporate Atlas API. Run: python -m uvicorn corporate_atlas.api.app:app --host 127.0.0.1 --port 8000

Use one worker: jobs and history are local to this process, and indexes share disk.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import re
import threading
import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from corporate_atlas.services.jobs import JobManager, inventory
from corporate_atlas.services.inventory import filing_information, company_label
from corporate_atlas.core.token_usage import usage_summary


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PrepareRequest(InputModel):
    tickers: str = Field(min_length=1, max_length=400)
    batch_size: int = Field(default=5, ge=1, le=100)
    batch_delay: float = Field(default=65, ge=0, le=600, allow_inf_nan=False)


class QueryRequest(InputModel):
    question: str = Field(min_length=1, max_length=5000)
    mode: Literal['hybrid', 'graph', 'vector'] = 'hybrid'
    top_k: int = Field(default=12, ge=1, le=50)

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


class FilingSelection(InputModel):
    ticker: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9.-]{0,14}$')
    accession: str = Field(pattern=r'^\d{10}-\d{2}-\d{6}$')


class DeleteRequest(InputModel):
    selections: list[FilingSelection] = Field(min_length=1, max_length=100)


class JobService:
    """Serialize mutations and keep the most recent 100 completed job snapshots."""
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
                while len(self.history) > 100:
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
        if job and job['status'] in {'running', 'stopping'} and job['action'] in {'prepare', 'delete_filings'}:
            raise HTTPException(409, 'Company information is being updated. Try again when the task finishes.')

    def shutdown(self):
        job = self.manager.snapshot()
        if job and job['status'] in {'running', 'stopping'}:
            if job['action'] != 'delete_filings':
                self.manager.stop()
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if self.manager.snapshot()['status'] not in {'running', 'stopping'}:
                    break
                time.sleep(.05)


def create_app(service=None):
    jobs = service or JobService()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(jobs.shutdown)

    application = FastAPI(title='Corporate Atlas API', version='1.0.0', lifespan=lifespan,
                          description='Local filing preparation, retrieval, and index management.')
    application.state.jobs = jobs
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])

    @application.middleware('http')
    async def local_browser_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin:
            parsed = urlparse(origin)
            allowed_origins = {'127.0.0.1:8000', 'localhost:8000', '127.0.0.1:8501', 'localhost:8501', request.headers.get('host', '')}
            if parsed.scheme != 'http' or parsed.netloc not in allowed_origins:
                return JSONResponse({'detail': 'Only the local application may call this API.'}, status_code=403)
        return await call_next(request)

    @application.get('/health', tags=['Status'])
    def health():
        return {'status': 'ok', 'application': 'Corporate Atlas'}

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
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,14}', ticker):
            raise HTTPException(422, 'Invalid ticker.')
        return {'label': company_label(ticker.upper())}

    @application.get('/usage', tags=['Data'])
    def usage():
        columns = ['operation', 'input_tokens', 'output_tokens', 'events', 'estimated_events']
        return {'rows': [dict(zip(columns, row)) for row in usage_summary()]}

    return application


app = create_app()
