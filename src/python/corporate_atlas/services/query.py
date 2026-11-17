"""Query every available local index, filtering only when the question names a ticker."""
import argparse
import json
import re
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = DATA_ROOT
FILINGS_ROOT = ROOT / SETTINGS.paths.filings_dir
GRAPHS_ROOT = ROOT / SETTINGS.paths.graph_dir
VECTOR_ROOT = ROOT / SETTINGS.paths.vector_dir


def mentioned_tickers(question, available, aliases=None):
    selected = {t for t in available if re.search(r'(?<![\w.-])\$?' + re.escape(t) + r'(?![\w.-])', question, re.I)}
    for ticker, names in (aliases or {}).items():
        if ticker in available and any(re.search(r'\b' + re.escape(name) + r'\b', question, re.I) for name in names if len(name) > 3):
            selected.add(ticker)
    ticker_pattern = (
        rf"\$([A-Za-z][A-Za-z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}})\b"
    )
    explicit = set(re.findall(ticker_pattern, question))
    unknown = {t.upper() for t in explicit} - set(available)
    if unknown:
        raise ValueError('No saved information for ticker(s): ' + ', '.join(sorted(unknown)))
    return sorted(selected) or None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--mode',
        choices=['hybrid', 'graph', 'vector', 'usage'],
        default=SETTINGS.query.default_mode,
    )
    parser.add_argument('--top-k', type=int, default=SETTINGS.query.default_top_k)
    parser.add_argument('--history', default='[]', help=argparse.SUPPRESS)
    parser.add_argument('question')
    args = parser.parse_args()
    try:
        history = json.loads(args.history)
    except json.JSONDecodeError as exc:
        raise ValueError('Chat history is not valid JSON.') from exc
    if not isinstance(history, list) or len(history) > SETTINGS.query.max_history_messages:
        raise ValueError('Chat history exceeds the configured limit.')
    for message in history:
        if (
            not isinstance(message, dict)
            or message.get('role') not in {'user', 'assistant'}
            or not isinstance(message.get('content'), str)
            or not message['content'].strip()
            or len(message['content']) > SETTINGS.query.max_history_message_chars
        ):
            raise ValueError('Chat history contains an invalid message.')
    if args.mode == 'usage':
        from corporate_atlas.services.usage_query import answer_usage_question
        print(answer_usage_question(args.question, history=history))
        return
    from corporate_atlas.core.query_graph import load_graph, answer_question
    from corporate_atlas.core.vector_store import open_vector_store
    graph_paths = list(GRAPHS_ROOT.glob('*.graphml'))
    graph = load_graph(GRAPHS_ROOT) if graph_paths and args.mode != 'vector' else None
    store = None
    vector_tickers = set()
    if args.mode != 'graph' and VECTOR_ROOT.is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(VECTOR_ROOT))
        try:
            collection = client.get_collection(SETTINGS.paths.vector_collection)
            metadata = collection.get(include=['metadatas']).get('metadatas') or []
            vector_tickers = {m['ticker'] for m in metadata if m and m.get('ticker')}
        except chromadb.errors.NotFoundError:
            pass
        if vector_tickers:
            store = open_vector_store(VECTOR_ROOT)
    graph_tickers = {p.stem for p in graph_paths if p.stem != 'combined'} if args.mode != 'vector' else set()
    aliases = {'AAPL': ['Apple'], 'WFC': ['Wells Fargo'], 'MSFT': ['Microsoft'],
               'RIVN': ['Rivian'], 'GOOGL': ['Alphabet'], 'AMZN': ['Amazon'], 'TSLA': ['Tesla']}
    if graph is not None:
        graph_tickers.update(str(d['ticker']) for _, d in graph.nodes(data=True) if d.get('ticker'))
    from bs4 import BeautifulSoup
    for ticker in graph_tickers | vector_tickers:
        for path in (FILINGS_ROOT / ticker).glob('*/*'):
            if path.suffix.lower() not in {'.htm', '.html'}:
                continue
            soup = BeautifulSoup(path.read_text(encoding='utf-8', errors='replace'), 'html.parser')
            registrant = soup.find(attrs={'name': re.compile(r'^dei:EntityRegistrantName$', re.I)})
            if registrant:
                name = registrant.get_text(' ', strip=True)
                if len(name) > 3:
                    aliases.setdefault(ticker, []).append(name)
    history_query = "\n".join(
        message['content'] for message in history if message['role'] == 'user'
    )
    retrieval_query = "\n".join(
        part
        for part in (
            args.question,
            f"Earlier user questions: {history_query}" if history_query else "",
        )
        if part
    )
    tickers = mentioned_tickers(retrieval_query, graph_tickers | vector_tickers, aliases)
    if tickers and graph is not None:
        # Subgraph also handles tickers whose data exists only in the vector store.
        graph = graph.subgraph([n for n, d in graph.nodes(data=True) if d.get('ticker') in tickers]).copy()
    mode = args.mode
    if mode == 'hybrid':
        mode = 'hybrid' if graph is not None and store is not None else 'graph' if graph is not None else 'vector'
    if mode == 'graph' and graph is None or mode == 'vector' and store is None:
        raise ValueError('No index is available for this retrieval mode. Download a ticker to prepare it first.')
    print(answer_question(
        args.question,
        graph,
        top_k=args.top_k,
        mode=mode,
        vector_store=store,
        tickers=tickers,
        history=history,
        retrieval_query=retrieval_query,
    ))


if __name__ == '__main__':
    main()
