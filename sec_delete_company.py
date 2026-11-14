"""Delete one company's local filings and indexes without affecting other tickers."""
import argparse
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent


def delete_company(ticker):
    ticker = ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker):
        raise ValueError('Invalid ticker.')
    folder = ROOT / 'sec_filings' / ticker
    graph_path = ROOT / 'knowledge_graphs' / f'{ticker}.graphml'
    if folder.is_symlink() or graph_path.is_symlink():
        raise ValueError('Refusing to delete a linked company folder or graph.')
    # Prepare the remaining combined graph before changing any stored data.
    import networkx as nx
    combined = nx.MultiDiGraph()
    for path in sorted((ROOT / 'knowledge_graphs').glob('*.graphml')):
        if path.name not in {f'{ticker}.graphml', 'combined.graphml'}:
            combined = nx.compose(combined, nx.read_graphml(path, force_multigraph=True))
    # A combined-only legacy graph can still contain facts for this company.
    combined_path = ROOT / 'knowledge_graphs' / 'combined.graphml'
    individual = [p for p in (ROOT / 'knowledge_graphs').glob('*.graphml') if p.name != 'combined.graphml']
    if not individual and combined_path.is_file():
        combined = nx.read_graphml(combined_path, force_multigraph=True)
        combined.remove_nodes_from([n for n, d in combined.nodes(data=True) if str(d.get('ticker', '')).upper() == ticker])
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            collection.delete(where={'ticker': ticker})
    if combined_path.exists() or graph_path.exists():
        temporary = combined_path.with_suffix('.graphml.tmp')
        nx.write_graphml(combined, temporary)
        temporary.replace(combined_path)
    if graph_path.exists():
        graph_path.unlink()
    if folder.exists():
        shutil.rmtree(folder)
    print(f'{ticker} company information deleted. Other companies and token usage records are preserved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    args = parser.parse_args()
    for ticker in args.tickers:
        delete_company(ticker)
