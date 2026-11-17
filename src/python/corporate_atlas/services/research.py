"""Source-backed company research: Wikimedia profiles + SEC annual XBRL facts."""
from copy import deepcopy
from datetime import date, datetime, timezone
from importlib.resources import files
import json
from pathlib import Path
import re
import threading
from urllib.parse import quote

import requests
from corporate_atlas.paths import DATA_ROOT

CACHE_ROOT = DATA_ROOT / 'research_cache'
WATCHLIST = DATA_ROOT / 'research_watchlist.json'
LOCK = threading.RLock()
CATALOG = [
    dict(ticker='AAPL', name='Apple', sector='Technology', cik='0000320193', wiki='Apple_Inc.', color='#a8b7cf'),
    dict(ticker='MSFT', name='Microsoft', sector='Technology', cik='0000789019', wiki='Microsoft', color='#65a9ff'),
    dict(ticker='NVDA', name='NVIDIA', sector='Semiconductors', cik='0001045810', wiki='Nvidia', color='#91d579'),
    dict(ticker='TSLA', name='Tesla', sector='Automotive', cik='0001318605', wiki='Tesla,_Inc.', color='#e89193'),
    dict(ticker='AMZN', name='Amazon', sector='Consumer & cloud', cik='0001018724', wiki='Amazon_(company)', color='#f5bd68'),
    dict(ticker='GOOGL', name='Alphabet', sector='Technology', cik='0001652044', wiki='Alphabet_Inc.', color='#8eb1e8'),
    dict(ticker='META', name='Meta Platforms', sector='Technology', cik='0001326801', wiki='Meta_Platforms', color='#929efa'),
    dict(ticker='JPM', name='JPMorgan Chase', sector='Financial services', cik='0000019617', wiki='JPMorgan_Chase', color='#aa9bf0'),
    dict(ticker='WFC', name='Wells Fargo', sector='Financial services', cik='0000072971', wiki='Wells_Fargo', color='#e5b57c'),
    dict(ticker='IBM', name='IBM', sector='Technology', cik='0000051143', wiki='IBM', color='#6cacf5'),
    dict(ticker='LLY', name='Eli Lilly', sector='Healthcare', cik='0000059478', wiki='Eli_Lilly_and_Company', color='#c49cdb'),
    dict(ticker='NFLX', name='Netflix', sector='Entertainment', cik='0001065280', wiki='Netflix', color='#e58f96'),
]
DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'NVDA', 'TSLA']
REVENUE_TAGS = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'RevenuesNetOfInterestExpense']


def valid_ticker(ticker):
    ticker = ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker):
        raise ValueError('Enter a valid company ticker.')
    return ticker


def seeds():
    path = files('corporate_atlas') / 'data/company_snapshots.json'
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def saved_watchlist():
    if WATCHLIST.is_file():
        return json.loads(WATCHLIST.read_text())
    return {'tickers': DEFAULT_WATCHLIST[:], 'custom': []}


def company_directory():
    return CATALOG + saved_watchlist().get('custom', [])


def company_catalog():
    from corporate_atlas.services.company_store import indexed_companies
    available = indexed_companies()
    directory = {c['ticker']: c for c in company_directory()}
    return [{**directory.get(ticker, {'ticker':ticker,'name':ticker,'sector':'Public company'}),
             **metadata, 'tracked':True} for ticker, metadata in sorted(available.items())]


def annual_values(facts, tags):
    """Only full-year USD facts: exclude YTD/quarter frames and pick latest restatements."""
    values = {}
    for priority, tag in enumerate(tags):
        for row in facts.get(tag, {}).get('units', {}).get('USD', []):
            if row.get('form') != '10-K' or not row.get('start') or not row.get('end'):
                continue
            try:
                span = (date.fromisoformat(row['end']) - date.fromisoformat(row['start'])).days
            except ValueError:
                continue
            if not 330 <= span <= 380 or not isinstance(row.get('val'), (int, float)):
                continue
            candidate = {**row, 'concept': tag, 'priority': priority}
            existing = values.get(row['end'])
            if existing is None or priority < existing['priority'] or (priority == existing['priority'] and row.get('filed', '') > existing.get('filed', '')):
                values[row['end']] = candidate
    return values


def financial_history(payload):
    facts = payload.get('facts', {}).get('us-gaap', {})
    revenues = annual_values(facts, REVENUE_TAGS)
    incomes = annual_values(facts, ['NetIncomeLoss', 'ProfitLoss'])
    result = []
    for end in sorted(revenues)[-6:]:
        revenue = revenues[end]
        income = incomes.get(end)
        # Align numerator/denominator to the same annual reporting interval.
        net = income['val'] if income and income['start'] == revenue['start'] else None
        result.append({'year': end[:4], 'start': revenue['start'], 'end': end,
                       'revenue': revenue['val'], 'net_income': net,
                       'net_margin': net / revenue['val'] * 100 if net is not None and revenue['val'] else None,
                       'filed': revenue.get('filed'), 'accession': revenue.get('accn'), 'concept': revenue['concept']})
    return result


def derive_metrics(history):
    latest = history[-1] if history else {}
    previous = history[-2] if len(history) >= 2 else {}
    growth = None
    if latest and previous and previous.get('revenue'):
        gap = (date.fromisoformat(latest['end']) - date.fromisoformat(previous['end'])).days
        if 330 <= gap <= 380:
            growth = (latest['revenue'] / previous['revenue'] - 1) * 100
    return {'revenue': latest.get('revenue'), 'net_income': latest.get('net_income'),
            'net_margin': latest.get('net_margin'), 'revenue_growth': growth,
            'period_end': latest.get('end'),
            'revenue_basis': 'Net of interest expense' if latest.get('concept') == 'RevenuesNetOfInterestExpense' else 'Reported revenue'}


def fetch_profile(company):
    title = company.get('wiki')
    matched_by_search = not bool(title)
    headers = {'User-Agent': 'CorporateAtlas/1.0 (company research; https://github.com/manishsinghal5185/sec-filing)'}
    if not title:
        search = requests.get('https://en.wikipedia.org/w/api.php', params={'action':'query','list':'search','srsearch':company['name'],'srlimit':1,'format':'json'}, headers=headers, timeout=15)
        search.raise_for_status()
        matches = search.json().get('query', {}).get('search', [])
        if not matches:
            raise LookupError('No Wikimedia company profile was found.')
        title = matches[0]['title']
    url = 'https://en.wikipedia.org/api/rest_v1/page/summary/' + quote(title, safe='')
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get('type') == 'disambiguation':
        raise LookupError('Wikimedia returned an ambiguous company page.')
    return {'title': data.get('title', company['name']), 'description': data.get('description', ''),
            'summary': data.get('extract', ''), 'source_url': data.get('content_urls', {}).get('desktop', {}).get('page', url),
            'api_url': url, 'matched_by_search': matched_by_search, 'license': 'Wikipedia text: CC BY-SA; see linked article history and license.'}


def research_company(ticker, refresh=False):
    ticker = valid_ticker(ticker)
    company = next((c for c in company_directory() if c['ticker'] == ticker), None)
    if company is None:
        from corporate_atlas.services.company_store import indexed_companies
        metadata = indexed_companies().get(ticker)
        if metadata is None:
            raise LookupError('No indexed company content. Download this ticker first.')
        company = {'ticker':ticker, 'name':ticker, 'sector':'Public company', 'cik':None, **metadata}
    cache = CACHE_ROOT / f'{ticker}.json'
    from corporate_atlas.services.company_store import snapshot
    previous = snapshot(ticker)
    if refresh and previous is None and cache.is_file():
        previous = json.loads(cache.read_text())
    if previous and not refresh:
        return {**deepcopy(previous), 'snapshot': True}
    result = {**company, 'profile': None, 'history': [], 'metrics': derive_metrics([]), 'warnings': [],
              'fetched_at': datetime.now(timezone.utc).isoformat(), 'snapshot': False}
    if not refresh:
        result['warnings'] = ['No saved snapshot yet. Refresh company data to retrieve public sources.']
        return result
    try:
        result['profile'] = fetch_profile(company)
        if result['profile'].get('matched_by_search'):
            result['warnings'].append('The overview was matched using Wikimedia search. Verify the linked article for this company.')
    except (requests.RequestException, ValueError, LookupError):
        result['profile'] = previous.get('profile') if previous else None
        result['warnings'].append('Wikimedia overview could not be refreshed. Any displayed overview is from the saved snapshot.')
    source = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json" if company.get('cik') else ''
    result['financial_source'] = source
    try:
        if not source:
            raise ValueError('No SEC company identifier available.')
        from corporate_atlas.core.sec_quarterly_filings import SecClient
        response = SecClient().get(source)
        try:
            result['history'] = financial_history(response.json())
        finally:
            response.close()
        result['financial_fetched_at'] = result['fetched_at']
    except (requests.RequestException, ValueError):
        result['history'] = previous.get('history', []) if previous else []
        result['financial_fetched_at'] = previous.get('financial_fetched_at', previous.get('fetched_at')) if previous else None
        result['warnings'].append('Financial data could not be refreshed. Any displayed values are from the saved snapshot.')
    result['metrics'] = derive_metrics(result['history'])
    if not result['history']:
        result['warnings'].append('No compatible full-year USD revenue facts are available from this SEC dataset. The general company profile may still be available.')
    if result['metrics'].get('revenue_basis') == 'Net of interest expense':
        result['warnings'].append('This financial institution reports revenue net of interest expense. Use care when comparing it with non-financial companies.')
    result['profile_fetched_at'] = result['fetched_at'] if result['profile'] and not any('could not be refreshed' in w and 'Wikimedia' in w for w in result['warnings']) else (previous.get('profile_fetched_at', previous.get('fetched_at')) if previous else None)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK:
        temporary = cache.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2))
        temporary.replace(cache)
    return result


def wikimedia_ticker_company(ticker):
    """Only accept a fallback article whose traded_as field lists the exact ticker."""
    endpoint = 'https://en.wikipedia.org/w/api.php'
    headers = {'User-Agent':'CorporateAtlas/1.0 (public company research)'}
    response = requests.get(endpoint, params={'action':'query','list':'search','srsearch':f'"{ticker}" company','srlimit':3,'format':'json'}, headers=headers, timeout=15)
    response.raise_for_status()
    for item in response.json().get('query',{}).get('search',[]):
        page = requests.get(endpoint, params={'action':'parse','page':item['title'],'prop':'wikitext','format':'json'}, headers=headers, timeout=15)
        page.raise_for_status()
        markup = page.json().get('parse',{}).get('wikitext',{}).get('*','')
        field = re.search(r'(?ims)^\s*\|\s*traded_as\s*=\s*(.*?)(?=^\s*\|\s*\w+\s*=|^}}|\Z)', markup)
        if field and re.search(r'(?<![A-Z0-9])'+re.escape(ticker)+r'(?![A-Z0-9])', field.group(1), re.I):
            return {'ticker':ticker,'name':item['title'],'sector':'Public company','cik':None,'wiki':item['title'],'color':'#8498e8'}
    raise LookupError('No verified Wikimedia company article lists this ticker.')


def add_company(ticker):
    ticker = valid_ticker(ticker)
    with LOCK:
        saved = saved_watchlist()
        catalog = CATALOG + saved.get('custom', [])
        if ticker not in {c['ticker'] for c in catalog}:
            from corporate_atlas.core.sec_quarterly_filings import SecClient
            found = None
            try:
                response = SecClient().get('https://www.sec.gov/files/company_tickers.json')
                try:
                    found = next((item for item in response.json().values() if item.get('ticker', '').upper() == ticker), None)
                finally:
                    response.close()
            except requests.RequestException:
                pass
            company = ({'ticker':ticker, 'name':found['title'], 'sector':'Public company',
                        'cik':str(found['cik_str']).zfill(10), 'wiki':None, 'color':'#8498e8'}
                       if found else wikimedia_ticker_company(ticker))
            saved.setdefault('custom', []).append(company)
        if ticker not in saved['tickers']:
            saved['tickers'].append(ticker)
        WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
        temp = WATCHLIST.with_suffix('.tmp')
        temp.write_text(json.dumps(saved, indent=2))
        temp.replace(WATCHLIST)
    return research_company(ticker, refresh=True)

