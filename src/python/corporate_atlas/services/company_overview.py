"""Assemble a company profile and comparable annual SEC financial facts."""
from datetime import date
from functools import lru_cache
import logging
import math
import re
import time

import requests

from corporate_atlas.core.sec_quarterly_filings import SEC_DATA, SEC_WWW, SecClient, get_json, ticker_cik_map
from corporate_atlas.services.inventory import VECTOR_ROOT
from corporate_atlas.settings import SETTINGS

LOGGER = logging.getLogger(__name__)
ANNUAL_FORMS = {'10-K', '10-K/A', '20-F', '20-F/A', '40-F', '40-F/A'}
REVENUE_TAGS = {
    'us-gaap': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'),
    'ifrs-full': ('Revenue',),
}
INCOME_TAGS = {
    'us-gaap': ('NetIncomeLoss', 'ProfitLoss'),
    'ifrs-full': ('ProfitLossAttributableToOwnersOfParent', 'ProfitLoss'),
}


def annual_series(concept):
    """Return annual facts by currency and exact fiscal period, preferring revisions."""
    currencies = {}
    for unit, rows in concept.get('units', {}).items():
        if not re.fullmatch(r'[A-Z]{3}', unit):
            continue
        periods = {}
        for row in rows:
            if row.get('form') not in ANNUAL_FORMS:
                continue
            try:
                start = date.fromisoformat(row['start'])
                end = date.fromisoformat(row['end'])
                filed = date.fromisoformat(row['filed'])
                value = row['val']
                if not 335 <= (end - start).days <= 395 or not math.isfinite(value):
                    continue
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            key = (start, end)
            accession = row.get('accn', '')
            ranking = (filed, accession)
            if key not in periods or ranking > periods[key][0]:
                periods[key] = (ranking, value)
        if periods:
            currencies[unit] = periods
    return currencies


def annual_financials(payload):
    """Select a single annual revenue series and align income to those periods."""
    facts = payload.get('facts', {})
    candidates = []
    for taxonomy, tags in REVENUE_TAGS.items():
        for tag in tags:
            for unit, periods in annual_series(facts.get(taxonomy, {}).get(tag, {})).items():
                candidates.append((taxonomy, unit, periods))
    if not candidates:
        return []
    taxonomy, unit, revenue = max(candidates, key=lambda item: max(period[1] for period in item[2]))
    concepts = facts[taxonomy]
    income = next(
        (series for tag in INCOME_TAGS[taxonomy]
         if (series := annual_series(concepts.get(tag, {})).get(unit))),
        {},
    )

    # Fiscal calendar changes can produce multiple annual spans with the same end.
    # Use the most recently reported span and its matching income fact.
    by_end = {}
    for period, (version, amount) in sorted(revenue.items(), key=lambda item: item[1][0]):
        by_end[period[1]] = (period, amount, version[1])
    result = []
    for end in sorted(by_end)[-6:]:
        period, amount, accession = by_end[end]
        net_income = income[period][1] if period in income else None
        result.append({
            'period_end': end.isoformat(),
            'currency': unit,
            'revenue': amount,
            'net_income': net_income,
            'net_margin': net_income / amount * 100 if net_income is not None and amount > 0 else None,
            'accession': accession,
        })
    return result


@lru_cache(maxsize=4)
def _ticker_directory(hour):
    with requests.Session() as session:
        return ticker_cik_map(get_json(SecClient(session), f'{SEC_WWW}{SETTINGS.sec.company_tickers_path}'))


@lru_cache(maxsize=64)
def _sec_overview(ticker, hour):
    cik = _ticker_directory(hour).get(ticker)
    if not cik:
        return None
    source = f'{SEC_DATA}/api/xbrl/companyfacts/CIK{cik}.json'
    with requests.Session() as session:
        payload = get_json(SecClient(session), source)
    periods = annual_financials(payload)
    growth = None
    if len(periods) >= 2:
        prior, latest = periods[-2:]
        gap = (date.fromisoformat(latest['period_end']) - date.fromisoformat(prior['period_end'])).days
        if 335 <= gap <= 395 and prior['revenue'] > 0:
            growth = (latest['revenue'] / prior['revenue'] - 1) * 100

    return {'periods': periods, 'revenue_growth': growth, 'source': source}


def _saved_profile(ticker):
    if not VECTOR_ROOT.is_dir():
        return None
    import chromadb

    client = chromadb.PersistentClient(path=str(VECTOR_ROOT))
    try:
        index = client.get_collection(SETTINGS.paths.vector_collection)
    except chromadb.errors.NotFoundError:
        return None
    result = index.get(ids=[f'wikimedia:{ticker}'], include=['documents', 'metadatas'])
    if not result['ids']:
        return None
    document = result['documents'][0] or ''
    metadata = result['metadatas'][0] or {}
    text = document.partition('\n\n')[2].strip()
    source = metadata.get('source', '')
    if text and source.startswith('https://en.wikipedia.org/wiki/'):
        return {'text': text, 'source': source}
    return None


def company_overview(ticker):
    """Read the saved profile and fetch annual metrics independently."""
    hour = int(time.time() // 3600)
    financials = None
    try:
        financials = _sec_overview(ticker, hour)
    except (requests.RequestException, ValueError):
        LOGGER.warning('SEC company facts unavailable for %s', ticker)
    return {'financials': financials, 'profile': _saved_profile(ticker)}
