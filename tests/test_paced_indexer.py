"""Offline checks: python -m unittest discover -s tests -p test_paced_indexer.py."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import corporate_atlas.core.build_vector_store_paced as indexer
class PacedIndexerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        filing = self.root / 'AAPL' / 'accession' / 'filing.htm'
        filing.parent.mkdir(parents=True)
        filing.write_text('<p>' + 'sample text ' * 50 + '</p>')
        self.store = MagicMock()
        self.store.get.return_value = {'ids': ['stale', 'stock:AAPL', 'wikimedia:AAPL']}
        for name, replacement in (
            ('embedding_settings', MagicMock(return_value=('google_genai', 'test', ''))),
            ('open_vector_store', MagicMock(return_value=self.store)),
            ('record_embedding_usage', MagicMock()),
        ):
            patcher = patch.object(indexer, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(indexer.time, 'sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def run_indexer(self, **kwargs):
        return indexer.build_vector_store(
            ['AAPL'], self.root, self.root / 'vectors',
            chunk_size=200, overlap=0, batch_size=2, **kwargs,
        )

    def test_quota_retry_preserves_batch_and_cleans_up_after_success(self):
        self.store.add_texts.side_effect = [RuntimeError('429 RESOURCE_EXHAUSTED'), None, None]
        self.assertEqual(self.run_indexer(), 3)
        calls = self.store.add_texts.call_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(calls[2].kwargs['ids']), 1)
        self.sleep.assert_called_once_with(65.0)
        self.assertEqual(indexer.record_embedding_usage.call_count, 2)
        self.store.delete.assert_called_once_with(ids=['stale'])

    def test_retry_exhaustion_preserves_stale_chunks(self):
        self.store.add_texts.side_effect = RuntimeError('429 RESOURCE_EXHAUSTED')
        with self.assertRaises(RuntimeError):
            self.run_indexer(max_retries=1)
        self.assertEqual(self.store.add_texts.call_count, 2)
        self.store.delete.assert_not_called()
        indexer.record_embedding_usage.assert_not_called()

    def test_authentication_error_is_not_retried(self):
        self.store.add_texts.side_effect = RuntimeError('invalid API key')
        with self.assertRaises(RuntimeError):
            self.run_indexer()
        self.sleep.assert_not_called()
        self.store.delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
