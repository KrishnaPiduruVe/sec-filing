"""Inspect per-company artifacts without embedding or model calls."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def company_information():
    filings = {}
    for path in (ROOT / 'sec_filings').glob('*/*/*'):
        if path.is_file() and path.suffix.lower() in {'.htm', '.html'}:
            filings[path.parent.parent.name] = filings.get(path.parent.parent.name, 0) + 1
    graphs = {p.stem for p in (ROOT / 'knowledge_graphs').glob('*.graphml') if p.stem != 'combined'}
    vectors = {}
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
            for metadata in collection.get(include=['metadatas']).get('metadatas') or []:
                if metadata and metadata.get('ticker'):
                    ticker = metadata['ticker']
                    vectors[ticker] = vectors.get(ticker, 0) + 1
        except chromadb.errors.NotFoundError:
            pass
    return [{'Ticker': ticker, 'Downloaded filings': filings.get(ticker, 0),
             'Knowledge graph': 'Available' if ticker in graphs else 'Not built',
             'Vector chunks': vectors.get(ticker, 0)}
            for ticker in sorted(set(filings) | graphs | set(vectors))]


def company_label(ticker):
    """Use the filing's registrant name when available, falling back to its ticker."""
    import re
    from bs4 import BeautifulSoup
    for path in sorted((ROOT / 'sec_filings' / ticker).glob('*/*'), reverse=True):
        if path.suffix.lower() in {'.htm', '.html'}:
            soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'html.parser')
            name = soup.find(attrs={'name': re.compile(r'^dei:EntityRegistrantName$', re.I)})
            if name and name.get_text(strip=True):
                return f"{name.get_text(' ', strip=True)} ({ticker})"
    return ticker
