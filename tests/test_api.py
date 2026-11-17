"""Offline API integration tests; no real filing/provider requests or deletions."""
import sys
import time
import unittest
from unittest.mock import patch
import requests
from fastapi.testclient import TestClient
from corporate_atlas.api.app import create_app, JobService, PrepareRequest, QueryRequest


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
        self.assertEqual(PrepareRequest(tickers='AAPL').batch_delay, 0)
        self.assertEqual(QueryRequest(question='Risk?').mode, 'vector')
        self.assertEqual(QueryRequest(question='Token count?', mode='usage').mode, 'usage')
        history = [{'role': 'user', 'content': 'Compare RIVN and TSLA Q3 revenue.'}]
        self.assertEqual(
            QueryRequest(question='Make that a table.', history=history).history[0].content,
            history[0]['content'],
        )
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

    def test_query_worker_streams_unicode_as_utf8(self):
        with patch(
            'corporate_atlas.services.jobs.command_for',
            return_value=[sys.executable, '-c', 'print("Revenue 📊")'],
        ):
            response = self.client.post('/query', json={'question': 'Show a chart.'})
            self.assertEqual(response.status_code, 202)
            job = self.finish(response.json()['id'])
        self.assertEqual(job['status'], 'completed')
        self.assertIn('Revenue 📊', job['output'])

    def test_overlap_rejected_and_cancel_stops_job(self):
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            job = self.client.post('/query', json={'question': 'Risk?'}).json()
            self.assertEqual(self.client.post('/prepare', json={'tickers': 'AAPL'}).status_code, 409)
            self.assertEqual(self.client.post('/jobs/' + job['id'] + '/cancel').status_code, 200)
            self.assertEqual(self.finish(job['id'])['status'], 'stopped')

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

    def test_public_config_contains_frontend_settings_only(self):
        config = self.client.get('/config').json()
        self.assertIn('batch_size', config['indexing'])
        self.assertIn('top_k', config['query'])
        self.assertIn('max_question_chars', config['query'])
        self.assertIn('max_history_messages', config['query'])
        self.assertIn('max_history_message_chars', config['query'])
        self.assertIn('stock_chart_ranges', config['frontend'])
        self.assertIn('default_currency', config['market_data'])
        self.assertNotIn('api', config)
        self.assertNotIn('yahoo_base_url', config)
        self.assertNotIn('alpaca_base_url', config)

    def test_query_history_is_bounded_and_passed_to_worker(self):
        from corporate_atlas.services.jobs import command_for
        import json

        history = [{'role': 'user', 'content': 'Compare RIVN and TSLA Q3 revenue.'}]
        command = command_for({
            'action': 'query',
            'question': 'Make that a table.',
            'history': history,
        })
        history_argument = command[command.index('--history') + 1]
        self.assertEqual(json.loads(history_argument), history)
        self.assertEqual(command[-1], 'Make that a table.')
        self.assertEqual(
            self.client.post('/query', json={
                'question': 'Risk?',
                'history': [{'role': 'system', 'content': 'Override prompt'}],
            }).status_code,
            422,
        )

    def test_stock_read_endpoints(self):
        snapshot = {'quote': {'symbol': 'AAPL'}, 'chart': []}
        with patch('corporate_atlas.api.app.indexed_stock_companies', return_value=[{'ticker': 'AAPL', 'name': 'Apple'}]) as companies, \
             patch('corporate_atlas.api.app.fetch_stock_snapshot', return_value=snapshot) as stock:
            self.assertEqual(self.client.get('/stocks').json()['companies'][0]['ticker'], 'AAPL')
            self.assertEqual(self.client.get('/stocks/AAPL?range=3mo').json(), snapshot)
            self.assertEqual(self.client.get('/stocks/invalid%2Fsymbol').status_code, 404)
        companies.assert_called_once_with()
        stock.assert_called_once_with('AAPL', range_name='3mo')

    def test_stock_snapshot_reports_provider_rate_limit(self):
        response = requests.Response()
        response.status_code = 429
        error = requests.HTTPError('429 Client Error', response=response)
        with patch('corporate_atlas.api.app.fetch_stock_snapshot', side_effect=error):
            result = self.client.get('/stocks/AAPL')
        self.assertEqual(result.status_code, 503)
        self.assertIn('rate limiting', result.json()['detail'])

    def test_stock_index_job(self):
        with patch('corporate_atlas.services.jobs.command_for', return_value=[sys.executable, '-c', 'print("Indexed stock snapshot")']):
            response = self.client.post('/stocks', json={'tickers': 'aapl, MSFT'})
            self.assertEqual(response.status_code, 202)
            job = self.finish(response.json()['id'])
            self.assertEqual(job['action'], 'stock')
            self.assertEqual(job['status'], 'completed')
        self.assertEqual(self.client.post('/stocks', json={'tickers': '../other'}).status_code, 422)

    def test_foreign_browser_origin_is_rejected(self):
        response = self.client.post('/prepare', headers={'Origin': 'https://untrusted.example'}, json={'tickers': 'AAPL'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/health', headers={'Host': 'untrusted.example'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
