"""Persist the ten most recent completed question-and-answer pairs locally."""
import json
import sqlite3
from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.services.answer_display import readable_answer

HISTORY_DB = DATA_ROOT / 'chat_history.sqlite3'
LIMIT = 10


def connect():
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(HISTORY_DB, timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS chat_history (id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, tickers TEXT NOT NULL, completed REAL NOT NULL)')
    return connection


def record(job):
    if job.get('action') != 'query' or job.get('status') != 'completed' or not job.get('question'):
        return
    answer = readable_answer(job.get('output',''))
    if not answer.strip():
        return
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO chat_history VALUES (?, ?, ?, ?, ?)',
                   (job['id'],job['question'],answer,json.dumps(job.get('company_tickers',[])),job['finished_at']))
        db.execute('DELETE FROM chat_history WHERE id NOT IN (SELECT id FROM chat_history ORDER BY completed DESC, rowid DESC LIMIT ?)',(LIMIT,))


def entries(tickers=None):
    with connect() as db:
        rows = db.execute('SELECT id, question, answer, tickers, completed FROM chat_history ORDER BY completed DESC, rowid DESC LIMIT ?', (LIMIT,)).fetchall()
    result = [{'id':r[0],'question':r[1],'answer':r[2],'tickers':json.loads(r[3]),'completed_at':r[4]} for r in rows]
    return result if tickers is None else [entry for entry in result if set(entry['tickers']) == set(tickers)]
