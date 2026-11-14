"""Query every available local index, filtering only when the question names a ticker."""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


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
    parser.add_argument('--mode', choices=['hybrid', 'graph', 'vector'], default='hybrid')
    parser.add_argument('--top-k', type=int, default=12)
    parser.add_argument('question')
    args = parser.parse_args()
    from query_graph import load_graph, answer_question
    from vector_store import open_vector_store
    graph_paths = list((ROOT / 'knowledge_graphs').glob('*.graphml'))
    graph = load_graph(ROOT / 'knowledge_graphs') if graph_paths and args.mode != 'vector' else None
    store = None
    vector_tickers = set()
    if args.mode != 'graph' and (ROOT / 'chroma_db').is_dir():
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
    graph_tickers = {p.stem for p in graph_paths if p.stem != 'combined'}
    aliases = {'AAPL': ['Apple'], 'WFC': ['Wells Fargo'], 'MSFT': ['Microsoft'],
               'RIVN': ['Rivian'], 'GOOGL': ['Alphabet'], 'AMZN': ['Amazon'], 'TSLA': ['Tesla']}
    if graph is not None:
        graph_tickers.update(str(d['ticker']) for _, d in graph.nodes(data=True) if d.get('ticker'))
    from bs4 import BeautifulSoup
    for ticker in graph_tickers | vector_tickers:
        for path in (ROOT / 'sec_filings' / ticker).glob('*/*'):
            if path.suffix.lower() not in {'.htm', '.html'}:
                continue
            soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'html.parser')
            registrant = soup.find(attrs={'name': re.compile(r'^dei:EntityRegistrantName$', re.I)})
            if registrant:
                name = registrant.get_text(' ', strip=True)
                if len(name) > 3:
                    aliases.setdefault(ticker, []).append(name)
    tickers = mentioned_tickers(args.question, graph_tickers | vector_tickers, aliases)
    if tickers and graph is not None:
        # Subgraph also handles tickers whose data exists only in the vector store.
        graph = graph.subgraph([n for n, d in graph.nodes(data=True) if d.get('ticker') in tickers]).copy()
    mode = args.mode
    if mode == 'hybrid':
        mode = 'hybrid' if graph is not None and store is not None else 'graph' if graph is not None else 'vector'
    if mode == 'graph' and graph is None or mode == 'vector' and store is None:
        raise ValueError('No index is available for this retrieval mode. Download a ticker to prepare it first.')
    print(answer_question(args.question, graph, top_k=args.top_k, mode=mode, vector_store=store, tickers=tickers))


if __name__ == '__main__':
    main()
