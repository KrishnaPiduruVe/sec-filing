"""Verify canonical company availability and public snapshots without providers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from corporate_atlas.services import company_store, research


class CompanyStoreTests(unittest.TestCase):
    def test_metadata_is_the_only_availability_source(self):
        store = MagicMock()
        store.get.return_value = {'metadatas':[{'ticker':'IBM'}, {'ticker':'IBM','name':'IBM'}, {'ticker':'AAPL'}, None]}
        with patch.object(company_store, 'collection', return_value=store):
            self.assertEqual(set(company_store.indexed_companies()), {'IBM','AAPL'})
        with patch.object(company_store, 'collection', return_value=None):
            self.assertEqual(company_store.indexed_companies(), {})

    def test_public_snapshot_is_embedded_and_read_back_from_chroma(self):
        company = {'ticker':'IBM','name':'IBM','profile':{'summary':'IBM makes technology.','source_url':'https://en.wikipedia.org/wiki/IBM'}, 'history':[]}
        store = MagicMock()
        store.get.return_value = {'ids':[]}
        with patch('corporate_atlas.core.vector_store.open_vector_store',return_value=store), patch('corporate_atlas.core.vector_store.embedding_settings',return_value=('test','model','key')), patch('corporate_atlas.core.token_usage.record_embedding_usage'):
            self.assertEqual(company_store.index_snapshot(company),1)
        args = store.add_texts.call_args.kwargs
        self.assertEqual(args['ids'], ['IBM:public:0'])
        self.assertEqual(args['metadatas'][0]['ticker'],'IBM')
        store.get.return_value = {'metadatas':args['metadatas']}
        with patch.object(company_store,'collection',return_value=store):
            self.assertEqual(company_store.snapshot('IBM'),company)

    def test_cached_snapshot_migration_does_not_add_or_embed_documents(self):
        store = MagicMock()
        store.get.return_value = {'ids':['IBM:accession:0'],'metadatas':[{'ticker':'IBM'}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(research,'CACHE_ROOT',Path(folder)), patch.object(company_store,'collection',return_value=store):
            (Path(folder)/'IBM.json').write_text(json.dumps({'ticker':'IBM','name':'IBM','profile':{'summary':'Saved profile'}}))
            self.assertEqual(company_store.migrate_cached_snapshots(),1)
        store.update.assert_called_once()
        store.add.assert_not_called()

    def test_wikimedia_fallback_rejects_similar_company_name_with_wrong_symbol(self):
        search = MagicMock()
        search.json.return_value = {'query':{'search':[{'title':'Apple Inc.'}]}}
        page = MagicMock()
        page.json.return_value = {'parse':{'wikitext':{'*':'| traded_as = {{NASDAQ|AAPL}}\n| industry = Technology'}}}
        with patch.object(research.requests,'get',side_effect=[search,page]):
            with self.assertRaises(LookupError): research.wikimedia_ticker_company('APPL')
        with patch.object(research.requests,'get',side_effect=[search,page]):
            self.assertEqual(research.wikimedia_ticker_company('AAPL')['wiki'],'Apple Inc.')
