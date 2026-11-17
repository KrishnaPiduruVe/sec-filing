"""Background task runner for the local Streamlit SEC filing application."""
from __future__ import annotations

import atexit
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = DATA_ROOT
FILINGS_ROOT = ROOT / SETTINGS.paths.filings_dir
GRAPHS_ROOT = ROOT / SETTINGS.paths.graph_dir
VECTOR_ROOT = ROOT / SETTINGS.paths.vector_dir
TICKER_PATTERN = (
    rf"[A-Z][A-Z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}}"
)


def command_for(data: dict) -> list[str]:
    """Build only allowlisted commands; user input is never passed to a shell."""
    action = data.get('action')
    if action == 'usage':
        return [sys.executable, '-u', '-m', 'corporate_atlas.core.token_usage']
    if action == 'delete_filings':
        from corporate_atlas.services.delete_filings import validate_selections
        selections = validate_selections(data.get('selections'))
        return [sys.executable, '-u', '-m', 'corporate_atlas.services.delete_filings', '--selections', json.dumps(selections)]
    if action == 'query':
        mode = data.get('mode', SETTINGS.query.default_mode)
        try:
            top_k = int(data.get('top_k', SETTINGS.query.default_top_k))
        except (ValueError, TypeError):
            raise ValueError('Context count must be an integer.') from None
        question = str(data.get('question', '')).strip()
        if (
            mode not in {'graph', 'vector', 'hybrid', 'usage'}
            or not 1 <= top_k <= SETTINGS.query.max_top_k
        ):
            raise ValueError(
                f"Choose a valid retrieval mode and context count "
                f"(1–{SETTINGS.query.max_top_k})."
            )
        if not question or len(question) > SETTINGS.query.max_question_chars:
            raise ValueError(
                f"Enter a question of 1–{SETTINGS.query.max_question_chars} characters."
            )
        history = data.get('history', [])
        if (
            not isinstance(history, list)
            or len(history) > SETTINGS.query.max_history_messages
            or any(
                not isinstance(message, dict)
                or message.get('role') not in {'user', 'assistant'}
                or not isinstance(message.get('content'), str)
                or not message['content'].strip()
                or len(message['content']) > SETTINGS.query.max_history_message_chars
                for message in history
            )
        ):
            raise ValueError('Chat history is invalid or exceeds the configured limit.')
        history_json = json.dumps(history, ensure_ascii=False)
        return [
            sys.executable,
            '-u',
            '-m',
            'corporate_atlas.services.query',
            '--mode',
            mode,
            '--top-k',
            str(top_k),
            '--history',
            history_json,
            '--',
            question,
        ]
    tickers = list(dict.fromkeys(re.split(r'[\s,]+', str(data.get('tickers', '')).strip().upper())))
    if (
        not tickers
        or len(tickers) > SETTINGS.limits.tickers_per_job
        or any(not re.fullmatch(TICKER_PATTERN, ticker) for ticker in tickers)
    ):
        raise ValueError(
            f"Enter 1–{SETTINGS.limits.tickers_per_job} valid tickers, "
            "separated by commas or spaces."
        )
    scripts = {'fetch': 'corporate_atlas.core.sec_quarterly_filings', 'graph': 'corporate_atlas.core.build_knowledge_graph',
               'vector': 'corporate_atlas.core.build_vector_store_paced', 'prepare': 'corporate_atlas.services.prepare',
               'delete': 'corporate_atlas.services.delete_company', 'stock': 'corporate_atlas.services.stock'}
    if action not in scripts:
        raise ValueError('Unknown action.')
    args = [sys.executable, '-u', '-m', scripts[action]]
    if action == 'fetch':
        return args + tickers
    if action in {'graph', 'vector', 'prepare', 'delete', 'stock'}:
        args += ['--tickers', *tickers]
    if action in {'vector', 'prepare'}:
        try:
            batch = int(data.get('batch_size', SETTINGS.indexing.batch_size))
            delay = float(
                data.get(
                    'batch_delay',
                    SETTINGS.indexing.batch_delay_seconds,
                )
            )
        except (ValueError, TypeError):
            raise ValueError('Batch size and delay must be numbers.') from None
        if (
            not 1 <= batch <= SETTINGS.indexing.max_batch_size
            or not math.isfinite(delay)
            or not 0 <= delay <= SETTINGS.indexing.max_batch_delay_seconds
        ):
            raise ValueError(
                f"Batch size must be 1–{SETTINGS.indexing.max_batch_size}; "
                f"delay must be 0–{SETTINGS.indexing.max_batch_delay_seconds:g} seconds."
            )
        args += ['--batch-size', str(batch), '--batch-delay', str(delay)]
    return args


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.job = None
        self.process = None
        atexit.register(self.stop)

    def start(self, data):
        args = command_for(data)
        with self.lock:
            if self.job and self.job['status'] in {'running', 'stopping'}:
                raise RuntimeError('A task is already running. Wait for it or click Stop.')
            self.job = dict(id=secrets.token_hex(8), action=data['action'], status='running',
                            output='', started=time.time(), elapsed=0, exit_code=None,
                            tickers=re.split(r'[\s,]+', str(data.get('tickers', '')).strip().upper()) if data.get('tickers') else [],
                            steps={name: {'status': 'pending', 'message': ''} for name in ('download', 'vector')})
            self.process = None
            threading.Thread(target=self._run, args=(args,), daemon=True).start()
            return dict(self.job)

    def _run(self, args):
        code = None
        try:
            worker_environment = os.environ.copy()
            worker_environment["PYTHONIOENCODING"] = "utf-8"
            worker_environment["ATLAS_USAGE_JOB_ID"] = self.job["id"]
            process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", env=worker_environment,
                                       bufsize=1)
            with self.lock:
                self.process = process
                if self.job['status'] == 'stopping':
                    process.terminate()
            with process.stdout:
                for line in process.stdout:
                    with self.lock:
                        if line.startswith('WORKFLOW '):
                            event = json.loads(line[len('WORKFLOW '):])
                            self.job['steps'][event['stage']] = {'status': event['status'], 'message': event['message']}
                        else:
                            self.job['output'] = (
                                self.job['output'] + line
                            )[-SETTINGS.limits.job_output_chars:]
            code = process.wait()
        except Exception as exc:
            with self.lock:
                self.job['output'] += f'Unable to run task: {exc}\n'
        finally:
            with self.lock:
                self.job['exit_code'] = code
                self.job['status'] = ('stopped' if self.job['status'] == 'stopping'
                                      else 'completed' if code == 0 else 'failed')
                for step in self.job['steps'].values():
                    if step['status'] == 'running':
                        step['status'] = 'stopped' if self.job['status'] == 'stopped' else 'failed'
                self.job['finished_at'] = time.time()
                self.job['elapsed'] = round(self.job['finished_at'] - self.job['started'])
                self.process = None

    def stop(self):
        with self.lock:
            if self.job and self.job['status'] in {'running', 'stopping'}:
                self.job['status'] = 'stopping'
                if self.process:
                    process = self.process
                    process.terminate()
                    # Bound shutdown even if a provider library ignores termination.
                    def force_stop():
                        try:
                            process.wait(
                                timeout=(
                                    SETTINGS.jobs.prepare_stop_wait_seconds
                                    if self.job and self.job['action'] == 'prepare'
                                    else SETTINGS.jobs.default_stop_wait_seconds
                                )
                            )
                        except subprocess.TimeoutExpired:
                            process.kill()
                    threading.Thread(target=force_stop, daemon=True).start()

    def snapshot(self):
        with self.lock:
            job = {**self.job, 'steps': {k: dict(v) for k, v in self.job['steps'].items()}} if self.job else None
            if job and job['status'] in {'running', 'stopping'}:
                job['elapsed'] = round(time.time() - job['started'])
            return job


def inventory():
    tickers = sorted({p.name for p in FILINGS_ROOT.glob('*') if p.is_dir()})
    return {'tickers': tickers,
            'html_files': sum(1 for p in FILINGS_ROOT.glob('*/*/*') if p.suffix.lower() in {'.htm', '.html'}),
            'graphs': len([p for p in GRAPHS_ROOT.glob('*.graphml') if p.name != 'combined.graphml']),
            'vector_exists': VECTOR_ROOT.is_dir(),
            'env_exists': (ROOT / '.env').is_file()}
