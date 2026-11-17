"""Query every available local index, filtering only when the question names a ticker."""
import argparse
import re
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT


def mentioned_tickers(question, available, aliases=None):
    selected = {t for t in available if re.search(r'(?<![\w.-])\$?' + re.escape(t) + r'(?![\w.-])', question, re.I)}
    for ticker, names in (aliases or {}).items():
        if ticker in available and any(re.search(r'\b' + re.escape(name) + r'\b', question, re.I) for name in names if len(name) > 3):
            selected.add(ticker)
    explicit = set(re.findall(r'\$([A-Za-z][A-Za-z0-9.-]{0,14})\b', question))
    unknown = {t.upper() for t in explicit} - set(available)
    if unknown:
        raise ValueError('No saved information for ticker(s): ' + ', '.join(sorted(unknown)))
    return sorted(selected) or None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['vector'], default='vector')
    parser.add_argument('--top-k', type=int, default=12)
    parser.add_argument('question')
    args = parser.parse_args()
    from corporate_atlas.core.query_vectors import answer_question
    from corporate_atlas.core.vector_store import open_vector_store
    store = None
    vector_tickers = set()
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
            metadata = collection.get(include=['metadatas']).get('metadatas') or []
            vector_tickers = {m['ticker'] for m in metadata if m and m.get('ticker')}
        except chromadb.errors.NotFoundError:
            pass
        if vector_tickers:
            store = open_vector_store(ROOT / 'chroma_db')
    aliases = {'AAPL': ['Apple'], 'WFC': ['Wells Fargo'], 'MSFT': ['Microsoft'],
               'RIVN': ['Rivian'], 'GOOGL': ['Alphabet'], 'AMZN': ['Amazon'], 'TSLA': ['Tesla']}
    from bs4 import BeautifulSoup
    for ticker in vector_tickers:
        for path in (ROOT / 'sec_filings' / ticker).glob('*/*'):
            if path.suffix.lower() not in {'.htm', '.html'}:
                continue
            soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'html.parser')
            registrant = soup.find(attrs={'name': re.compile(r'^dei:EntityRegistrantName$', re.I)})
            if registrant:
                name = registrant.get_text(' ', strip=True)
                if len(name) > 3:
                    aliases.setdefault(ticker, []).append(name)
    tickers = mentioned_tickers(args.question, vector_tickers, aliases)
    if store is None:
        raise ValueError('No index is available for this retrieval mode. Download a ticker to prepare it first.')
    print(answer_question(args.question, top_k=args.top_k, vector_store=store, tickers=tickers))


if __name__ == '__main__':
    main()
