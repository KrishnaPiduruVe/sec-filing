import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import networkx as nx
import corporate_atlas.services.delete_filings as deletion
import corporate_atlas.services.prepare as workflow
from corporate_atlas.services.jobs import command_for


class FilingDeleteTests(unittest.TestCase):
    def test_deletes_only_selected_quarter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            graph_root = root / 'knowledge_graphs'
            graph_root.mkdir()
            graph = nx.MultiDiGraph()
            old, keep = '0000320193-26-000001', '0000320193-26-000020'
            for accession in (old, keep):
                path = root / 'sec_filings' / 'AAPL' / accession / 'filing.htm'
                path.parent.mkdir(parents=True)
                path.write_text('<p>filing</p>')
                graph.add_node('company', ticker='AAPL', evidence='old and new evidence')
                graph.add_node(accession, ticker='AAPL')
                graph.add_edge('company', accession, filing=accession, ticker='AAPL', evidence=accession)
            nx.write_graphml(graph, graph_root / 'AAPL.graphml')
            nx.write_graphml(graph, graph_root / 'combined.graphml')
            (root / 'chroma_db').mkdir()
            chroma = MagicMock()
            with patch.object(deletion, 'ROOT', root), patch.dict('sys.modules', {'chromadb': chroma}):
                deletion.delete_filings([{'ticker': 'AAPL', 'accession': old}])
            self.assertFalse((root / 'sec_filings' / 'AAPL' / old).exists())
            self.assertTrue((root / 'sec_filings' / 'AAPL' / keep).exists())
            remaining = nx.read_graphml(graph_root / 'AAPL.graphml', force_multigraph=True)
            self.assertEqual(remaining.number_of_edges(), 1)
            self.assertNotIn(old, remaining.nodes['company']['evidence'])
            self.assertIn(keep, remaining.nodes['company']['evidence'])
            chroma.PersistentClient.return_value.get_collection.return_value.delete.assert_called_once_with(
                where={'$and': [{'ticker': 'AAPL'}, {'filing': old}]})
            self.assertEqual(nx.read_graphml(graph_root / 'combined.graphml').number_of_edges(), 1)

    def test_rejects_invalid_selection(self):
        with self.assertRaises(ValueError):
            command_for({'action': 'delete_filings', 'selections': [{'ticker': 'AAPL', 'accession': '../other'}]})

    def test_interruption_cleans_new_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def interrupt(*args):
                path = root / 'sec_filings/AAPL/0000320193-26-000020/filing.htm'
                path.parent.mkdir(parents=True)
                path.write_text('partial download')
                raise InterruptedError('interrupted')
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, '_prepare', side_effect=interrupt):
                with self.assertRaises(InterruptedError):
                    workflow.prepare(['AAPL'])
            self.assertFalse((root / 'sec_filings/AAPL').exists())


if __name__ == '__main__':
    unittest.main()
