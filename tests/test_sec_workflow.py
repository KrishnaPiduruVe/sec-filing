import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sec_prepare_workflow as workflow
from sec_query_web import mentioned_tickers


class WorkflowTests(unittest.TestCase):
    def test_cached_artifacts_make_no_provider_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html = root / 'sec_filings/AAPL/accession/main.htm'
            html.parent.mkdir(parents=True)
            html.write_text('<p>Saved filing</p>')
            graph = root / 'knowledge_graphs/AAPL.graphml'
            graph.parent.mkdir()
            graph.write_text('saved graph')
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'vector_complete', return_value=True), patch.object(workflow, 'run_script') as run:
                workflow.prepare(['AAPL'])
                run.assert_not_called()

    def test_missing_artifacts_run_in_order(self):
        with patch.object(workflow, 'html_files', return_value=[]), patch.object(workflow, 'vector_complete', return_value=False), patch.object(workflow, 'ROOT', Path('/nonexistent/workflow-test')), patch.object(workflow, 'run_script') as run:
            workflow.prepare(['AAPL'])
            self.assertEqual([c.args[0] for c in run.call_args_list], ['sec_quarterly_filings.py', 'build_knowledge_graph.py', 'build_vector_store_paced.py'])

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
