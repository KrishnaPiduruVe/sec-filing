"""Inspect per-company artifacts without embedding or model calls."""
from pathlib import Path
import re
from functools import lru_cache

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT


@lru_cache(maxsize=256)
def filing_period(path, modified_ns, size):
    """Read fiscal quarter/year from XBRL; dates alone do not establish a fiscal quarter.

    Modification time and size invalidate cached metadata when a filing changes.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(Path(path).read_text(encoding='utf-8', errors='replace'), 'html.parser')

    def fact(name):
        node = soup.find(attrs={'name': re.compile(r'^dei:' + name + r'$', re.I)})
        return ' '.join(node.get_text(' ', strip=True).split()) if node else ''

    year = fact('DocumentFiscalYearFocus')
    quarter = fact('DocumentFiscalPeriodFocus')
    period_end = fact('DocumentPeriodEndDate')
    label = f"FY{year} {quarter}" if year and quarter else quarter or 'Fiscal quarter unavailable'
    return f"{label} (ended {period_end})" if period_end else label


def company_information():
    filings = {}
    periods = {}
    for path in (ROOT / 'sec_filings').glob('*/*/*'):
        if path.is_file() and path.suffix.lower() in {'.htm', '.html'}:
            filings[path.parent.parent.name] = filings.get(path.parent.parent.name, 0) + 1
            ticker = path.parent.parent.name
            info = path.stat()
            periods.setdefault(ticker, set()).add(filing_period(str(path), info.st_mtime_ns, info.st_size))
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
             'Downloaded fiscal quarters': '; '.join(sorted(periods.get(ticker, []))) or 'No downloaded filing',
             'Vector chunks': vectors.get(ticker, 0)}
            for ticker in sorted(set(filings) | set(vectors))]


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


def filing_information():
    """Return one selectable row per ticker/accession (one downloaded filing)."""
    rows = {}
    for path in (ROOT / 'sec_filings').glob('*/*/*'):
        if path.is_file() and path.suffix.lower() in {'.htm', '.html'}:
            ticker, accession = path.parent.parent.name, path.parent.name
            stat = path.stat()
            row = rows.setdefault((ticker, accession), {'Ticker': ticker, 'Fiscal quarter': '',
                                  'Accession': accession, 'Downloaded files': 0,
                                  'Vector chunks': 0})
            row['Downloaded files'] += 1
            row['Fiscal quarter'] = filing_period(str(path), stat.st_mtime_ns, stat.st_size)
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            for metadata in collection.get(include=['metadatas']).get('metadatas') or []:
                key = (metadata.get('ticker'), str(metadata.get('filing', ''))) if metadata else None
                if key in rows:
                    rows[key]['Vector chunks'] += 1
    return [rows[key] for key in sorted(rows)]
