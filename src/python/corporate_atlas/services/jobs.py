"""Background task runner for the local Corporate Atlas application."""
from __future__ import annotations

import atexit
import json
import math
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT


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
        mode = data.get('mode', 'vector')
        try:
            top_k = int(data.get('top_k', 12))
        except (ValueError, TypeError):
            raise ValueError('Context count must be an integer.') from None
        question = str(data.get('question', '')).strip()
        if mode != 'vector' or not 1 <= top_k <= 50:
            raise ValueError('Choose a valid retrieval mode and context count (1–50).')
        if not question or len(question) > 5000:
            raise ValueError('Enter a question of 1–5,000 characters.')
        if data.get('public_context'):
            from corporate_atlas.services.research import valid_ticker
            selected = data.get('company_tickers', [])
            if not isinstance(selected, list) or not 1 <= len(selected) <= 4:
                raise ValueError('Select between one and four companies.')
            selected = [valid_ticker(str(ticker)) for ticker in selected]
            return [sys.executable, '-u', '-m', 'corporate_atlas.services.research_query', '--tickers', *selected,
                    '--mode', mode, '--top-k', str(top_k), '--', question]
        return [sys.executable, '-u', '-m', 'corporate_atlas.services.query', '--mode', mode, '--top-k', str(top_k), '--', question]
    tickers = list(dict.fromkeys(re.split(r'[\s,]+', str(data.get('tickers', '')).strip().upper())))
    if not tickers or len(tickers) > 20 or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', t) for t in tickers):
        raise ValueError('Enter 1–20 valid tickers, separated by commas or spaces.')
    scripts = {'fetch': 'corporate_atlas.core.sec_quarterly_filings',
               'vector': 'corporate_atlas.core.build_vector_store_paced', 'prepare': 'corporate_atlas.services.prepare', 'delete': 'corporate_atlas.services.delete_company'}
    if action not in scripts:
        raise ValueError('Unknown action.')
    args = [sys.executable, '-u', '-m', scripts[action]]
    if action == 'fetch':
        return args + tickers
    if action in {'vector', 'prepare', 'delete'}:
        args += ['--tickers', *tickers]
    if action in {'vector', 'prepare'}:
        try:
            batch = int(data.get('batch_size', 5))
            delay = float(data.get('batch_delay', 65))
        except (ValueError, TypeError):
            raise ValueError('Batch size and delay must be numbers.') from None
        if not 1 <= batch <= 100 or not math.isfinite(delay) or not 0 <= delay <= 600:
            raise ValueError('Batch size must be 1–100; delay must be 0–600 seconds.')
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
                            question=data.get('question',''), company_tickers=data.get('company_tickers',[]),
                            tickers=re.split(r'[\s,]+', str(data.get('tickers', '')).strip().upper()) if data.get('tickers') else [],
                            steps={name: {'status': 'pending', 'message': ''} for name in ('download', 'profile', 'vector')})
            self.process = None
            threading.Thread(target=self._run, args=(args,), daemon=True).start()
            return dict(self.job)

    def _run(self, args):
        code = None
        try:
            process = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1)
            with self.lock:
                self.process = process
                if self.job['status'] == 'stopping':
                    process.terminate()
            with process.stdout:
                for line in process.stdout:
                    with self.lock:
                        if line.startswith('SOURCE_UNAVAILABLE '):
                            self.job['source_error'] = json.loads(line[len('SOURCE_UNAVAILABLE '):])
                        elif line.startswith('WORKFLOW '):
                            event = json.loads(line[len('WORKFLOW '):])
                            self.job['steps'][event['stage']] = {'status': event['status'], 'message': event['message']}
                        else:
                            self.job['output'] = (self.job['output'] + line)[-200_000:]
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
                if self.job['action'] == 'query' and self.job['status'] == 'completed':
                    try:
                        from corporate_atlas.services.chat_history import record
                        record(self.job)
                    except Exception:
                        self.job['history_error'] = 'The answer is available, but its history could not be saved.'
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
                            process.wait(timeout=30 if self.job and self.job['action'] == 'prepare' else 5)
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
    from corporate_atlas.services.company_store import indexed_companies
    tickers = sorted(indexed_companies())
    return {'tickers': tickers,
            'html_files': sum(1 for p in (ROOT / 'sec_filings').glob('*/*/*') if p.suffix.lower() in {'.htm', '.html'}),
            'vector_exists': (ROOT / 'chroma_db').is_dir(),
            'env_exists': (ROOT / '.env').is_file()}
