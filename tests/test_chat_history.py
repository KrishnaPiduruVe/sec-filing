import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from corporate_atlas.services import chat_history
from corporate_atlas.api.app import create_app, JobService
from fastapi.testclient import TestClient


class ChatHistoryTests(unittest.TestCase):
    def test_keeps_latest_ten_complete_pairs_and_company_scope(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(chat_history,'HISTORY_DB',Path(folder)/'history.sqlite3'):
            for i in range(12):
                chat_history.record({'id':str(i),'action':'query','status':'completed','question':f'Question {i}?','output':f'Answer {i}.','company_tickers':['AAPL'] if i%2 else ['MSFT'],'finished_at':i})
            entries=chat_history.entries()
            self.assertEqual([entry['id'] for entry in entries],list(map(str,range(11,1,-1))))
            self.assertEqual(len(chat_history.entries(['AAPL'])),5)
            chat_history.record({'id':'failed','action':'query','status':'failed','question':'Failed?','output':'Error','finished_at':99})
            self.assertEqual(len(chat_history.entries()),10)
            with TestClient(create_app(JobService()),base_url='http://127.0.0.1') as client:
                self.assertEqual(client.get('/chat/history').json()['entries'], entries)

    def test_duplicate_completion_is_not_added_twice_and_metadata_is_cleaned(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(chat_history,'HISTORY_DB',Path(folder)/'history.sqlite3'):
            job={'id':'same','action':'query','status':'completed','question':'Revenue?','output':"[{'type':'text','text':'Revenue increased.','extras':{'signature':'hidden'}}]",'finished_at':1}
            chat_history.record(job)
            chat_history.record(job)
            saved=chat_history.entries()
            self.assertEqual(len(saved),1)
            self.assertEqual(saved[0]['answer'],'Revenue increased.')
