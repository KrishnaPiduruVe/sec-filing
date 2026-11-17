"""Corporate Atlas API. Run: python -m uvicorn corporate_atlas.api.app:app --host 127.0.0.1 --port 8000

Use one worker: jobs and history are local to this process, and indexes share disk.
"""
from __future__ import annotations

import asyncio
import os
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
from corporate_atlas.services.answer_display import readable_answer
from corporate_atlas.api.frontend import mount_frontend
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
    mode: Literal['vector'] = 'vector'
    top_k: int = Field(default=12, ge=1, le=50)

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


class ResearchQueryRequest(QueryRequest):
    company_tickers: list[str] = Field(min_length=1, max_length=4)


class AddCompanyRequest(InputModel):
    ticker: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9.-]{0,14}$')


class FilingSelection(InputModel):
    ticker: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9.-]{0,14}$')
    accession: str = Field(pattern=r'^\d{10}-\d{2}-\d{6}$')


class DeleteRequest(InputModel):
    selections: list[FilingSelection] = Field(min_length=1, max_length=100)


class JobService:
    """Serialize mutations and keep the most recent 100 completed job snapshots."""
    def __init__(self, manager=None):
        self.manager = manager or JobManager()
        self.query_manager = JobManager()
        self.lock = threading.RLock()
        self.history = OrderedDict()
        self.preparation_proxy = os.getenv('ATLAS_PREPARATION_PROXY_URL', '').rstrip('/')
        if self.preparation_proxy:
            parsed = urlparse(self.preparation_proxy)
            if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','localhost'}:
                raise ValueError('The preparation proxy must be a local HTTP server.')
        self.external_last = None

    def external_preparation(self):
        if not self.preparation_proxy:
            return None
        import requests
        try:
            response = requests.get(self.preparation_proxy + '/jobs/current', timeout=2)
            response.raise_for_status()
            job = response.json().get('job')
            if job and job['action'] == 'prepare':
                self.external_last = job
        except requests.RequestException:
            if not self.external_last or self.external_last['status'] in {'running','stopping'}:
                raise HTTPException(503, 'The existing download server is temporarily unreachable.')
        return self.external_last

    def primary_snapshot(self):
        external = self.external_preparation()
        local = self.manager.snapshot()
        return external if external and external['status'] in {'running','stopping'} else local or external

    def start(self, action, data):
        with self.lock:
            if action in {'prepare','delete_filings'}:
                external = self.external_preparation()
                if external and external['status'] in {'running','stopping'}:
                    raise HTTPException(409, 'A download is already running. Wait for it to finish.')
            manager = self.query_manager if action == 'query' else self.manager
            current_write = self.manager.snapshot()
            current_query = self.query_manager.snapshot()
            if action == 'query' and current_write and current_write['action'] == 'delete_filings' and current_write['status'] in {'running','stopping'}:
                raise HTTPException(409, 'Wait for deletion to finish before asking a question.')
            if action == 'delete_filings' and current_query and current_query['status'] in {'running','stopping'}:
                raise HTTPException(409, 'Wait for the current question to finish before deleting data.')
            previous = manager.snapshot()
            try:
                job = manager.start({'action': action, **data})
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
            for manager in (self.manager, self.query_manager):
                current = manager.snapshot()
                if current and current['id'] == job_id:
                    return current
            if job_id in self.history:
                return self.history[job_id]
            external = self.external_preparation()
            if external and external['id'] == job_id:
                return external
        raise HTTPException(404, 'Job not found. Job history is cleared when the API restarts.')

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['status'] not in {'running', 'stopping'}:
                return job
            if job['action'] == 'delete_filings':
                raise HTTPException(409, 'Deletion cannot be interrupted once started.')
            for manager in (self.manager, self.query_manager):
                current = manager.snapshot()
                if current and current['id'] == job_id:
                    manager.stop()
                    return manager.snapshot()

    def check_readable(self):
        job = self.manager.snapshot()
        if job and job['status'] in {'running', 'stopping'} and job['action'] == 'delete_filings':
            raise HTTPException(409, 'Company information is being updated. Try again when the task finishes.')

    def shutdown(self):
        for manager in (self.query_manager, self.manager):
            job = manager.snapshot()
            if job and job['status'] in {'running', 'stopping'}:
                if job['action'] != 'delete_filings':
                    manager.stop()
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if manager.snapshot()['status'] not in {'running', 'stopping'}:
                        break
                    time.sleep(.05)


def job_response(job):
    if job and job.get('action') == 'query' and job.get('status') == 'completed':
        return {**job, 'answer': readable_answer(job.get('output', ''))}
    return job


def create_app(service=None, ui_dir=None):
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
        return {'job': job_response(jobs.manager.snapshot()), 'inventory': inventory()}

    @application.get('/jobs/current', tags=['Jobs'])
    def current_job():
        return {'job': job_response(jobs.primary_snapshot() or jobs.query_manager.snapshot()),
                'query_job': job_response(jobs.query_manager.snapshot())}

    @application.get('/jobs/{job_id}', tags=['Jobs'])
    def get_job(job_id: str):
        return job_response(jobs.get(job_id))

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

    @application.get('/chat/history', tags=['Company research'])
    def chat_history():
        from corporate_atlas.services.chat_history import entries
        return {'entries':entries()}

    @application.get('/usage', tags=['Data'])
    def usage():
        columns = ['operation', 'input_tokens', 'output_tokens', 'events', 'estimated_events']
        return {'rows': [dict(zip(columns, row)) for row in usage_summary()]}

    from corporate_atlas.services.research import company_catalog, research_company

    @application.get('/research/catalog', tags=['Company research'])
    def research_catalog():
        return {'companies': company_catalog()}

    @application.get('/research/companies/{ticker}', tags=['Company research'])
    def company_research(ticker: str, refresh: bool = False):
        try:
            if refresh:
                jobs.check_readable()
            company = research_company(ticker, refresh)
            if refresh:
                from corporate_atlas.services.company_store import index_snapshot
                index_snapshot(company)
            return company
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @application.post('/research/companies', status_code=202, tags=['Company research'])
    def integrate_company(data: AddCompanyRequest):
        return jobs.start('prepare', {'tickers':data.ticker, 'batch_size':5, 'batch_delay':65})

    @application.post('/research/query', status_code=202, tags=['Company research'])
    def research_query(data: ResearchQueryRequest):
        return jobs.start('query', {**data.model_dump(), 'public_context': True})

    mount_frontend(application, ui_dir)
    return application


app = create_app()
