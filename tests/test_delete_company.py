import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import networkx as nx
import corporate_atlas.services.delete_company as deletion
from corporate_atlas.services.jobs import command_for


class DeleteCompanyTests(unittest.TestCase):
    def test_delete_preserves_other_company_and_rebuilds_combined(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graphs = root / 'knowledge_graphs'
            graphs.mkdir()
            all_graphs = nx.MultiDiGraph()
            for ticker in ['AAPL', 'IBM']:
                filing = root / 'sec_filings' / ticker / 'accession' / 'filing.htm'
                filing.parent.mkdir(parents=True)
                filing.write_text('<p>filing</p>')
                graph = nx.MultiDiGraph()
                graph.add_node(ticker, ticker=ticker)
                nx.write_graphml(graph, graphs / f'{ticker}.graphml')
                all_graphs = nx.compose(all_graphs, graph)
            nx.write_graphml(all_graphs, graphs / 'combined.graphml')
            (root / 'chroma_db').mkdir()
            chroma = MagicMock()
            with patch.object(deletion, 'ROOT', root), patch.dict('sys.modules', {'chromadb': chroma}):
                deletion.delete_company('AAPL')
            chroma.PersistentClient.return_value.get_collection.return_value.delete.assert_called_once_with(where={'ticker': 'AAPL'})
            self.assertFalse((root / 'sec_filings' / 'AAPL').exists())
            self.assertTrue((root / 'sec_filings' / 'IBM').exists())
            self.assertFalse((graphs / 'AAPL.graphml').exists())
            self.assertEqual(set(nx.read_graphml(graphs / 'combined.graphml')), {'IBM'})

    def test_rejects_unsafe_ticker(self):
        with self.assertRaises(ValueError):
            deletion.delete_company('../other')

    def test_delete_command(self):
        command = command_for({'action': 'delete', 'tickers': 'AAPL'})
        self.assertTrue(command[3].endswith('corporate_atlas.services.delete_company'))
        self.assertEqual(command[-2:], ['--tickers', 'AAPL'])


if __name__ == '__main__':
    unittest.main()
