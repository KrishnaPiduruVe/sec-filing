"""Inspect per-company artifacts without embedding or model calls."""
from pathlib import Path
import re
from functools import lru_cache

from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = DATA_ROOT
FILINGS_ROOT = ROOT / SETTINGS.paths.filings_dir
GRAPHS_ROOT = ROOT / SETTINGS.paths.graph_dir
VECTOR_ROOT = ROOT / SETTINGS.paths.vector_dir


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
    for path in FILINGS_ROOT.glob('*/*/*'):
        if path.is_file() and path.suffix.lower() in {'.htm', '.html'}:
            filings[path.parent.parent.name] = filings.get(path.parent.parent.name, 0) + 1
            ticker = path.parent.parent.name
            info = path.stat()
            periods.setdefault(ticker, set()).add(filing_period(str(path), info.st_mtime_ns, info.st_size))
    graphs = {p.stem for p in GRAPHS_ROOT.glob('*.graphml') if p.stem != 'combined'}
    vectors = {}
    if VECTOR_ROOT.is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(VECTOR_ROOT))
        try:
            collection = client.get_collection(SETTINGS.paths.vector_collection)
            for metadata in collection.get(include=['metadatas']).get('metadatas') or []:
                if metadata and metadata.get('ticker'):
                    ticker = metadata['ticker']
                    vectors[ticker] = vectors.get(ticker, 0) + 1
        except chromadb.errors.NotFoundError:
            pass
    return [{'Ticker': ticker, 'Downloaded filings': filings.get(ticker, 0),
             'Downloaded fiscal quarters': '; '.join(sorted(periods.get(ticker, []))) or 'No downloaded filing',
             'Knowledge graph': 'Available' if ticker in graphs else 'Not built',
             'Vector chunks': vectors.get(ticker, 0)}
            for ticker in sorted(set(filings) | graphs | set(vectors))]


def company_label(ticker, *, filing_root=None):
    """Use the filing's registrant name when available, falling back to its ticker."""
    import re
    from bs4 import BeautifulSoup
    root = FILINGS_ROOT if filing_root is None else filing_root
    for path in sorted((root / ticker).glob('*/*'), reverse=True):
        if path.suffix.lower() in {'.htm', '.html'}:
            soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'html.parser')
            name = soup.find(attrs={'name': re.compile(r'^dei:EntityRegistrantName$', re.I)})
            if name and name.get_text(strip=True):
                return f"{name.get_text(' ', strip=True)} ({ticker})"
    return ticker


def filing_information():
    """Return one selectable row per ticker/accession (one downloaded filing)."""
    import networkx as nx
    rows = {}
    for path in FILINGS_ROOT.glob('*/*/*'):
        if path.is_file() and path.suffix.lower() in {'.htm', '.html'}:
            ticker, accession = path.parent.parent.name, path.parent.name
            stat = path.stat()
            row = rows.setdefault((ticker, accession), {'Ticker': ticker, 'Fiscal quarter': '',
                                  'Accession': accession, 'Downloaded files': 0,
                                  'Knowledge graph': 'Not indexed', 'Vector chunks': 0})
            row['Downloaded files'] += 1
            row['Fiscal quarter'] = filing_period(str(path), stat.st_mtime_ns, stat.st_size)
    for graph_path in GRAPHS_ROOT.glob('*.graphml'):
        if graph_path.stem == 'combined':
            continue
        graph = nx.read_graphml(graph_path, force_multigraph=True)
        for _, _, data in graph.edges(data=True):
            key = (graph_path.stem, str(data.get('filing', '')))
            if key in rows:
                rows[key]['Knowledge graph'] = 'Available'
    if VECTOR_ROOT.is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(VECTOR_ROOT))
        try:
            collection = client.get_collection(SETTINGS.paths.vector_collection)
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            for metadata in collection.get(include=['metadatas']).get('metadatas') or []:
                key = (metadata.get('ticker'), str(metadata.get('filing', ''))) if metadata else None
                if key in rows:
                    rows[key]['Vector chunks'] += 1
    return [rows[key] for key in sorted(rows)]
