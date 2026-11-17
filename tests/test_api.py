"""Offline API integration tests; no real filing/provider requests or deletions."""
import sys
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from corporate_atlas.api.app import create_app, JobService


class APITests(unittest.TestCase):
    def setUp(self):
        self.service = JobService()
        self.client = TestClient(create_app(self.service), base_url='http://127.0.0.1:8000')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def finish(self, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = self.client.get('/jobs/' + job_id)
            self.assertEqual(response.status_code, 200)
            job = response.json()
            if job['status'] not in {'running', 'stopping'}:
                return job
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_health_docs_and_validation(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/docs').status_code, 200)
        for body in [{'tickers': '../other'}, {'tickers': 'AAPL', 'batch_size': 0}]:
            self.assertEqual(self.client.post('/prepare', json=body).status_code, 422)
        self.assertEqual(self.client.post('/query', json={'question': '  '}).status_code, 422)
        self.assertEqual(self.client.post('/query', json={'question': 'Risk?', 'command': 'whoami'}).status_code, 422)
        self.assertEqual(self.client.post('/filings/delete', json={'selections': [{'ticker': 'AAPL', 'accession': '../other'}]}).status_code, 422)
        self.assertEqual(self.client.get('/jobs/missing').status_code, 404)

    def test_query_job_returns_output_and_retains_history(self):
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'print("A grounded answer")']):
            first = self.client.post('/query', json={'question': 'What are the risks?'})
            self.assertEqual(first.status_code, 202)
            job = self.finish(first.json()['id'])
            self.assertEqual(job['status'], 'completed')
            self.assertIn('A grounded answer', job['output'])
            second = self.client.post('/prepare', json={'tickers': 'AAPL'})
            self.assertEqual(second.status_code, 202)
            self.finish(second.json()['id'])
            self.assertEqual(self.client.get('/jobs/' + job['id']).json()['output'], job['output'])

    def test_overlap_rejected_and_cancel_stops_job(self):
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            job = self.client.post('/query', json={'question': 'Risk?'}).json()
            self.assertEqual(self.client.post('/query', json={'question': 'Another risk?'}).status_code, 409)
            self.assertEqual(self.client.post('/jobs/' + job['id'] + '/cancel').status_code, 200)
            self.assertEqual(self.finish(job['id'])['status'], 'stopped')

    def test_query_runs_during_download_and_cancel_does_not_stop_download(self):
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            download = self.client.post('/prepare', json={'tickers':'AAPL'})
            self.assertEqual(download.status_code,202)
            query = self.client.post('/query',json={'question':'Explain available company data'})
            self.assertEqual(query.status_code,202)
            self.assertEqual(self.client.post('/prepare',json={'tickers':'IBM'}).status_code,409)
            state=self.client.get('/jobs/current').json()
            self.assertEqual(state['job']['id'],download.json()['id'])
            self.assertEqual(state['query_job']['id'],query.json()['id'])
            with patch('corporate_atlas.api.app.filing_information',return_value=[]):
                self.assertEqual(self.client.get('/filings').status_code,200)
            self.client.post('/jobs/'+query.json()['id']+'/cancel')
            self.assertEqual(self.finish(query.json()['id'])['status'],'stopped')
            self.assertEqual(self.client.get('/jobs/'+download.json()['id']).json()['status'],'running')
            self.client.post('/jobs/'+download.json()['id']+'/cancel')
            self.assertEqual(self.finish(download.json()['id'])['status'],'stopped')

    def test_selected_filings_reach_worker_exactly(self):
        selected = [{'ticker': 'AAPL', 'accession': '0000320193-26-000020'}]
        from corporate_atlas.services.jobs import command_for
        commands = []
        def safe_command(data):
            commands.append(command_for(data))
            return [sys.executable, '-c', 'print("Temporary delete test")']
        with patch('corporate_atlas.services.jobs.command_for', side_effect=safe_command):
            response = self.client.post('/filings/delete', json={'selections': selected})
            self.assertEqual(response.status_code, 202)
            self.finish(response.json()['id'])
        import json
        self.assertTrue(commands[0][3].endswith('corporate_atlas.services.delete_filings'))
        self.assertEqual(json.loads(commands[0][-1]), selected)

    def test_read_endpoints(self):
        with patch('corporate_atlas.api.app.filing_information', return_value=[{'Ticker': 'AAPL', 'Fiscal quarter': 'FY2026 Q3'}]), patch('corporate_atlas.api.app.usage_summary', return_value=[('answer', 10, 5, 1, 0)]), patch('corporate_atlas.api.app.company_label', return_value='Apple Inc. (AAPL)'):
            self.assertEqual(self.client.get('/filings').json()['filings'][0]['Ticker'], 'AAPL')
            self.assertEqual(self.client.get('/usage').json()['rows'][0]['input_tokens'], 10)
            self.assertEqual(self.client.get('/companies/AAPL/label').json()['label'], 'Apple Inc. (AAPL)')

    def test_foreign_browser_origin_is_rejected(self):
        response = self.client.post('/prepare', headers={'Origin': 'https://untrusted.example'}, json={'tickers': 'AAPL'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/health', headers={'Host': 'untrusted.example'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
