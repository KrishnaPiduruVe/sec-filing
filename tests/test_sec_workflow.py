import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import corporate_atlas.services.prepare as workflow
from corporate_atlas.services.query import mentioned_tickers


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.sources = patch.object(workflow, 'prepare_public_sources', return_value={}).start()
        self.addCleanup(patch.stopall)

    def test_cached_artifacts_make_no_provider_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html = root / 'sec_filings/AAPL/accession/main.htm'
            html.parent.mkdir(parents=True)
            html.write_text('<p>Saved filing</p>')
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'vector_complete', return_value=True), patch.object(workflow, 'run_script') as run:
                workflow.prepare(['AAPL'])
                run.assert_not_called()
                self.sources.assert_called_once_with(["AAPL"])

    def test_missing_artifacts_run_in_order(self):
        with patch.object(workflow, 'html_files', side_effect=[[], [Path('filing.htm')]]), patch.object(workflow, 'vector_complete', return_value=False), patch.object(workflow, 'ROOT', Path('/nonexistent/workflow-test')), patch.object(workflow, 'run_script') as run:
            workflow.prepare(['AAPL'])
            self.assertEqual([c.args[0] for c in run.call_args_list], ['corporate_atlas.core.sec_quarterly_filings', 'corporate_atlas.core.build_vector_store_paced'])

    def test_failure_stops_following_stages(self):
        with patch.object(workflow, 'html_files', return_value=[]), patch.object(workflow, 'run_script', side_effect=RuntimeError('download failed')) as run:
            with self.assertRaises(RuntimeError):
                workflow.prepare(['AAPL'])
            self.assertEqual(run.call_count, 1)

    def test_question_scope(self):
        available = {'AAPL', 'WFC'}
        self.assertIsNone(mentioned_tickers('Compare reported risks', available))
        self.assertEqual(mentioned_tickers('Risks for aapl?', available), ['AAPL'])
        self.assertEqual(mentioned_tickers('Compare AAPL and WFC', available), ['AAPL', 'WFC'])
        self.assertEqual(mentioned_tickers('Apple revenue?', available, {'AAPL': ['Apple']}), ['AAPL'])
        with self.assertRaises(ValueError):
            mentioned_tickers('Risk at $TSLA?', available)


if __name__ == '__main__':
    unittest.main()


class VectorOnlyTests(unittest.TestCase):
    def test_removed_retrieval_modes_and_actions_are_rejected(self):
        from corporate_atlas.services.jobs import command_for
        from corporate_atlas.api.app import create_app, JobService
        from fastapi.testclient import TestClient
        for mode in ('graph', 'hybrid'):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    command_for({'action': 'query', 'question': 'Risk?', 'mode': mode})
        with self.assertRaises(ValueError):
            command_for({'action': 'graph', 'tickers': 'AAPL'})
        with TestClient(create_app(JobService()), base_url='http://127.0.0.1') as client:
            self.assertEqual(client.post('/query', json={'question': 'Risk?', 'mode': 'graph'}).status_code, 422)
            self.assertEqual(client.post('/research/query', json={'question': 'Risk?', 'mode': 'hybrid', 'company_tickers': ['AAPL']}).status_code, 422)

    def test_inventory_ignores_legacy_data(self):
        from corporate_atlas.services import inventory
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'knowledge_graphs' / 'legacy.graphml'
            legacy.parent.mkdir()
            legacy.write_text('not a readable graph')
            with patch.object(inventory, 'ROOT', root):
                self.assertEqual(inventory.company_information(), [])
                self.assertEqual(inventory.filing_information(), [])
            self.assertEqual(legacy.read_text(), 'not a readable graph')


class PublicSourcePreparationTests(unittest.TestCase):
    def test_preparation_fetches_profiles_even_when_filings_are_cached(self):
        with patch('corporate_atlas.services.research.add_company', return_value={'profile': {'summary': 'Company description'}, 'warnings': []}) as refresh:
            workflow.prepare_public_sources(['AAPL', 'MSFT'])
        self.assertEqual([call.args[0] for call in refresh.call_args_list], ['AAPL', 'MSFT'])

    def test_public_source_outage_does_not_abort_filing_preparation(self):
        import requests
        with patch('corporate_atlas.services.research.add_company', side_effect=requests.ConnectionError('offline')) as refresh:
            workflow.prepare_public_sources(['AAPL'])
        refresh.assert_called_once_with('AAPL')


class SourceFallbackTests(unittest.TestCase):
    def test_wikimedia_content_is_indexed_when_sec_filings_are_unavailable(self):
        profile = {'ticker':'AAPL', 'profile':{'summary':'A real company description'}}
        with patch.object(workflow, 'html_files', return_value=[]), patch.object(workflow, 'vector_complete', return_value=False), patch.object(workflow, 'run_script', side_effect=LookupError('No 10-Q')), patch.object(workflow, 'prepare_public_sources', return_value={'AAPL':profile}), patch('corporate_atlas.services.company_store.index_snapshot') as index:
            workflow._prepare(['AAPL'], batch_delay=0)
        index.assert_called_once_with(profile)

    def test_neither_source_produces_a_structured_ticker_error_without_embedding(self):
        with patch.object(workflow, 'html_files', return_value=[]), patch.object(workflow, 'vector_complete', return_value=False), patch.object(workflow, 'run_script', side_effect=LookupError('Invalid ticker')), patch.object(workflow, 'prepare_public_sources', return_value={}), patch('corporate_atlas.services.company_store.index_snapshot') as index:
            with self.assertRaises(workflow.SourceUnavailableError) as error:
                workflow._prepare(['APPL'], batch_delay=0)
        self.assertEqual(error.exception.details['sources'], ['SEC EDGAR', 'Wikimedia'])
        index.assert_not_called()
