"""Add a cited English Wikipedia company introduction to the research index."""
import re

import requests

from corporate_atlas.core.sec_quarterly_filings import sec_user_agent
from corporate_atlas.core.token_usage import record_embedding_usage
from corporate_atlas.core.vector_store import embedding_settings, open_vector_store
from corporate_atlas.services.inventory import company_label
from corporate_atlas.settings import SETTINGS

WIKIPEDIA_API = 'https://en.wikipedia.org/w/api.php'
LEGAL_SUFFIXES = {'inc', 'incorporated', 'corp', 'corporation', 'ltd', 'limited', 'plc', 'llc'}


def normalized_name(name, *, strip_suffixes=True):
    words = re.findall(r'[^\W_]+', name.casefold())
    while strip_suffixes and words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return ' '.join(words)


def fetch_profile(name):
    """Accept a unique name match and skip disambiguation pages."""
    expected = normalized_name(name)
    if not expected:
        return None
    response = requests.get(
        WIKIPEDIA_API,
        params={
            'action': 'query',
            'format': 'json',
            'formatversion': 2,
            'generator': 'search',
            'gsrsearch': f'intitle:"{expected}"',
            'gsrlimit': 5,
            'prop': 'extracts|info|pageprops',
            'exintro': 1,
            'explaintext': 1,
            'exsentences': 8,
            'exlimit': 5,
            'inprop': 'url',
            'ppprop': 'disambiguation',
        },
        headers={'User-Agent': f'CorporateAtlas/0.1 ({sec_user_agent()})'},
        timeout=SETTINGS.http.default_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if 'error' in payload:
        raise ValueError('Wikipedia returned an API error.')
    matches = [
        page for page in payload.get('query', {}).get('pages', [])
        if normalized_name(page.get('title', '')) == expected
        and 'disambiguation' not in page.get('pageprops', {})
        and page.get('extract', '').strip()
        and page.get('fullurl', '').startswith('https://en.wikipedia.org/wiki/')
    ]
    legal_name = normalized_name(name, strip_suffixes=False)
    exact_matches = [
        page for page in matches
        if normalized_name(page['title'], strip_suffixes=False) == legal_name
    ]
    if exact_matches:
        matches = exact_matches
    else:
        matches = [
            page for page in matches
            if re.search(r"\b(?:company|corporation|conglomerate|manufacturer|bank)\b",
                         page['extract'].split('\n', 1)[0], re.I)
        ]
    return matches[0] if len(matches) == 1 else None


def index_company_profile(ticker, filing_root, vector_root):
    label = company_label(ticker, filing_root=filing_root)
    if label == ticker:
        print(f'Wikipedia overview skipped for {ticker}: filing registrant name unavailable.', flush=True)
        return

    document_id = f'wikimedia:{ticker}'
    store = open_vector_store(vector_root, create=False)
    if store.get(ids=[document_id], include=[]).get('ids'):
        print(f'Reused saved Wikipedia overview for {ticker}.', flush=True)
        return

    name = label.removesuffix(f' ({ticker})')
    profile = fetch_profile(name)
    if profile is None:
        print(f'Wikipedia overview skipped for {ticker}: no unambiguous article match.', flush=True)
        return

    title, url = profile['title'], profile['fullurl']
    document = f"{title} ({ticker}) — Wikipedia company overview\n\n{profile['extract'].strip()}"
    store.add_texts(
        texts=[document],
        metadatas=[{'ticker': ticker, 'source_type': 'wikimedia', 'title': title, 'source': url}],
        ids=[document_id],
    )
    provider, model, _ = embedding_settings()
    record_embedding_usage([document], f'{provider}:{model}', operation='wikimedia_embedding')
    print(f'Indexed Wikipedia overview for {ticker}: {url}', flush=True)
