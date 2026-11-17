"""Source/financial integrity checks for the company dashboard; no provider calls."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient
from corporate_atlas.api.app import create_app, JobService
from corporate_atlas.services import research
from corporate_atlas.services.jobs import command_for


def fact(start, end, val, filed='2026-01-01', form='10-K'):
    return {'start':start,'end':end,'val':val,'filed':filed,'form':form,'accn':'test'}


class FinancialHistoryTests(unittest.TestCase):
    def test_annual_facts_exclude_ytd_quarters_and_keep_latest_restated_value(self):
        rows=[fact('2023-01-01','2023-12-31',100),fact('2024-01-01','2024-12-31',110,'2025-02-01'),
              fact('2024-01-01','2024-12-31',120,'2026-02-01'),fact('2024-01-01','2024-03-31',30),
              fact('2024-01-01','2024-09-30',90,form='10-Q')]
        history=research.financial_history({'facts':{'us-gaap':{'Revenues':{'units':{'USD':rows}},
            'NetIncomeLoss':{'units':{'USD':[fact('2024-01-01','2024-12-31',24)]}}}}})
        self.assertEqual(len(history),2)
        self.assertEqual(history[-1]['revenue'],120)
        self.assertEqual(history[-1]['net_margin'],20)
        self.assertAlmostEqual(research.derive_metrics(history)['revenue_growth'],20)

    def test_mismatched_income_interval_is_not_divided_by_revenue(self):
        history=research.financial_history({'facts':{'us-gaap':{'Revenues':{'units':{'USD':[fact('2024-01-01','2024-12-31',100)]}},
            'NetIncomeLoss':{'units':{'USD':[fact('2023-12-28','2024-12-31',10)]}}}}})
        self.assertIsNone(history[0]['net_income'])
        self.assertIsNone(history[0]['net_margin'])

    def test_missing_annual_period_does_not_become_year_over_year_growth(self):
        result=research.derive_metrics([{'end':'2022-12-31','revenue':100},{'end':'2024-12-31','revenue':200}])
        self.assertIsNone(result['revenue_growth'])

    def test_real_bundled_snapshots_have_traceable_sources_and_consistent_metrics(self):
        snapshots=research.seeds()
        self.assertTrue({'AAPL','MSFT','NVDA','TSLA'} <= snapshots.keys())
        for company in snapshots.values():
            self.assertTrue(company['profile']['api_url'].startswith('https://en.wikipedia.org/'))
            self.assertTrue(company['financial_source'].startswith('https://data.sec.gov/'))
            self.assertTrue(company['fetched_at'])
            for row in company['history']:
                self.assertGreaterEqual((date.fromisoformat(row['end'])-date.fromisoformat(row['start'])).days,330)
                if row['net_income'] is not None:
                    self.assertAlmostEqual(row['net_margin'],row['net_income']/row['revenue']*100)


class ResearchAPITests(unittest.TestCase):
    def setUp(self):
        self.snapshot_patch = patch('corporate_atlas.services.company_store.snapshot', return_value=research.seeds()['AAPL'])
        self.snapshot_patch.start()
        self.addCleanup(self.snapshot_patch.stop)

    def test_overview_available_without_model_calls(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(research,'CACHE_ROOT',Path(folder)), patch.object(research,'WATCHLIST',Path(folder)/'watch.json'):
            with TestClient(create_app(JobService()),base_url='http://127.0.0.1:8501') as client:
                self.assertEqual(client.get('/research/catalog').status_code,200)
                result=client.get('/research/companies/AAPL')
                self.assertEqual(result.status_code,200)
                self.assertTrue(result.json()['snapshot'])
                self.assertTrue(result.json()['history'])
                self.assertEqual(client.get('/research/companies/../bad').status_code,404)
                self.assertEqual(client.post('/research/companies',json={'ticker':'../bad'}).status_code,422)

    def test_failed_refresh_preserves_snapshot_and_reports_staleness(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(research,'CACHE_ROOT',Path(folder)), patch.object(research,'fetch_profile',side_effect=requests.ConnectionError), patch('corporate_atlas.core.sec_quarterly_filings.SecClient.get',side_effect=requests.ConnectionError):
            result=research.research_company('AAPL',refresh=True)
            self.assertEqual(len(result['warnings']),2)
            self.assertTrue(result['history'])
            self.assertEqual(result['financial_fetched_at'],research.seeds()['AAPL']['financial_fetched_at'])

    def test_new_query_worker_receives_explicit_company_scope(self):
        command=command_for({'action':'query','public_context':True,'company_tickers':['AAPL','MSFT'],'question':'Compare revenue'})
        self.assertIn('corporate_atlas.services.research_query',command)
        self.assertIn('AAPL',command)
        self.assertIn('MSFT',command)
        self.assertEqual(command[-1],'Compare revenue')
        with self.assertRaises(ValueError):
            command_for({'action':'query','public_context':True,'company_tickers':['../bad'],'question':'Risk?'})


if __name__=='__main__':
    unittest.main()


class PublicContextTests(unittest.TestCase):
    def test_public_research_can_answer_before_filing_index_exists(self):
        from corporate_atlas.services import research_query
        with tempfile.TemporaryDirectory() as folder, patch.object(research_query,'DATA_ROOT',Path(folder)), patch.object(research_query,'research_company',return_value={'ticker':'AAPL','profile':{'summary':'A business description','source_url':'https://en.wikipedia.org/wiki/Apple_Inc.'},'history':[]}):
            context=research_query.research_context(['AAPL'],'Explain the business')
        self.assertIn('A business description',context)
        self.assertIn('https://en.wikipedia.org/wiki/Apple_Inc.',context)
        self.assertNotIn('Locally indexed filing',context)


class RevenueDefinitionTests(unittest.TestCase):
    def test_bank_revenue_basis_is_explicit(self):
        history=research.financial_history({'facts':{'us-gaap':{'RevenuesNetOfInterestExpense':{'units':{'USD':[fact('2024-01-01','2024-12-31',100)]}}}}})
        self.assertEqual(research.derive_metrics(history)['revenue_basis'],'Net of interest expense')


class ChromaCatalogTests(unittest.TestCase):
    def test_only_chroma_companies_are_listed_not_starters_or_watchlist(self):
        with patch('corporate_atlas.services.company_store.indexed_companies', return_value={'IBM': {}}):
            companies = research.company_catalog()
        self.assertEqual([c['ticker'] for c in companies], ['IBM'])
        with patch('corporate_atlas.services.company_store.indexed_companies', return_value={}):
            self.assertEqual(research.company_catalog(), [])

    def test_bundled_examples_are_not_used_as_downloaded_content(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(research, 'CACHE_ROOT', Path(folder)), patch('corporate_atlas.services.company_store.snapshot', return_value=None):
            company = research.research_company('AAPL')
        self.assertIsNone(company['profile'])
        self.assertFalse(company['history'])
