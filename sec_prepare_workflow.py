"""Download and prepare selected tickers, reusing existing local artifacts."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES = ('download', 'graph', 'vector')


def event(stage, status, message):
    print('WORKFLOW ' + json.dumps(dict(stage=stage, status=status, message=message)), flush=True)


def html_files(ticker):
    return sorted(p for p in (ROOT / 'sec_filings' / ticker).glob('*/*')
                  if p.is_file() and p.suffix.lower() in {'.htm', '.html'} and p.stat().st_size)


def vector_complete(ticker):
    """Check actual stored chunk IDs, rather than assuming a directory is ready."""
    if not (ROOT / 'chroma_db').is_dir():
        return False
    from build_knowledge_graph import html_to_text, chunk_text
    import chromadb
    client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
    try:
        collection = client.get_collection('sec_filings')
    except chromadb.errors.NotFoundError:
        return False
    expected = set()
    for path in html_files(ticker):
        text = html_to_text(path.read_text(encoding='utf-8', errors='replace'))
        for i, _ in enumerate(chunk_text(text, chunk_size=4000, overlap=400)):
            expected.add(f'{ticker}:{path.parent.name}:{i}')
    existing = set(collection.get(where={'ticker': ticker}, include=[])['ids'])
    return bool(expected) and expected == existing


def run_script(script, *args):
    # Execute in this process so cancellation also stops the active pipeline stage.
    # runpy retains the existing scripts and their __main__ entry points unchanged.
    import runpy
    sys.argv = [str(ROOT / script), *args]
    runpy.run_path(str(ROOT / script), run_name='__main__')


def prepare(tickers, batch_size=5, batch_delay=65):
    missing = [ticker for ticker in tickers if not html_files(ticker)]
    cached = [ticker for ticker in tickers if ticker not in missing]
    if cached:
        print(f"We already have downloaded information for {', '.join(cached)}. Reusing it and checking the indexes.", flush=True)
    event('download', 'running', 'Downloading missing filings' if missing else 'Checking saved filings')
    if missing:
        run_script('sec_quarterly_filings.py', *missing)
    event('download', 'completed', 'Filings downloaded' if missing else 'Already downloaded — reused saved filings')

    missing_graphs = [t for t in tickers if not (ROOT / 'knowledge_graphs' / f'{t}.graphml').is_file() or not (ROOT / 'knowledge_graphs' / f'{t}.graphml').stat().st_size]
    event('graph', 'running', 'Extracting filing facts' if missing_graphs else 'Checking saved graphs')
    if missing_graphs:
        run_script('build_knowledge_graph.py', '--tickers', *missing_graphs)
    event('graph', 'completed', 'Knowledge graphs ready' if missing_graphs else 'Knowledge graphs already available')

    event('vector', 'running', 'Checking saved vectors')
    missing_vectors = [t for t in tickers if not vector_complete(t)]
    if missing_vectors:
        event('vector', 'running', 'Embedding filing chunks in paced batches')
        run_script('build_vector_store_paced.py', '--tickers', *missing_vectors,
                   '--batch-size', str(batch_size), '--batch-delay', str(batch_delay))
    event('vector', 'completed', 'Vector store ready' if missing_vectors else 'Vectors already available')
    print('Your information is ready. Ask a question below.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--batch-size', type=int, default=5)
    parser.add_argument('--batch-delay', type=float, default=65)
    args = parser.parse_args()
    prepare(args.tickers, args.batch_size, args.batch_delay)
