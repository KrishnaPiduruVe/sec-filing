"""Download and prepare selected tickers, reusing existing local artifacts."""
import argparse
import json
import signal
import sys
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = DATA_ROOT
STAGES = ('download', 'vector')


def event(stage, status, message):
    print('WORKFLOW ' + json.dumps(dict(stage=stage, status=status, message=message)), flush=True)


def html_files(ticker):
    filing_root = ROOT / SETTINGS.paths.filings_dir
    return sorted(p for p in (filing_root / ticker).glob('*/*')
                  if p.is_file() and p.suffix.lower() in {'.htm', '.html'} and p.stat().st_size)


def vector_complete(ticker):
    """Check actual stored chunk IDs, rather than assuming a directory is ready."""
    vector_root = ROOT / SETTINGS.paths.vector_dir
    if not vector_root.is_dir():
        return False
    from corporate_atlas.core.build_knowledge_graph import html_to_text, chunk_text
    import chromadb
    client = chromadb.PersistentClient(path=str(vector_root))
    try:
        collection = client.get_collection(SETTINGS.paths.vector_collection)
    except chromadb.errors.NotFoundError:
        return False
    expected = set()
    for path in html_files(ticker):
        text = html_to_text(path.read_text(encoding='utf-8', errors='replace'))
        for i, _ in enumerate(
            chunk_text(
                text,
                chunk_size=SETTINGS.indexing.chunk_size,
                overlap=SETTINGS.indexing.overlap,
            )
        ):
            expected.add(f'{ticker}:{path.parent.name}:{i}')
    existing = set(collection.get(where={'ticker': ticker}, include=[])['ids'])
    return bool(expected) and expected == existing


def run_script(script, *args):
    # Execute in this process so cancellation also stops the active pipeline stage.
    # Keep the real module identity: Pydantic resolves deferred annotations
    # through it when the provider generates structured-output schemas.
    from importlib import import_module
    previous_argv = sys.argv
    try:
        sys.argv = [script, *args]
        import_module(script).main()
    finally:
        sys.argv = previous_argv


def _prepare(
    tickers,
    batch_size=SETTINGS.indexing.batch_size,
    batch_delay=SETTINGS.indexing.batch_delay_seconds,
):
    missing = [ticker for ticker in tickers if not html_files(ticker)]
    cached = [ticker for ticker in tickers if ticker not in missing]
    if cached:
        print(f"We already have downloaded information for {', '.join(cached)}. Reusing it and checking the indexes.", flush=True)
    event('download', 'running', 'Downloading missing filings' if missing else 'Checking saved filings')
    if missing:
        run_script('corporate_atlas.core.sec_quarterly_filings', *missing)
    event('download', 'completed', 'Filings downloaded' if missing else 'Already downloaded — reused saved filings')

    event('vector', 'running', 'Checking saved vectors')
    missing_vectors = [t for t in tickers if not vector_complete(t)]
    if missing_vectors:
        event('vector', 'running', 'Embedding filing chunks in paced batches')
        run_script('corporate_atlas.core.build_vector_store_paced', '--tickers', *missing_vectors,
                   '--batch-size', str(batch_size), '--batch-delay', str(batch_delay))
    event('vector', 'completed', 'Vector store ready' if missing_vectors else 'Vectors already available')
    print('Your information is ready. Ask a question below.', flush=True)


def prepare(
    tickers,
    batch_size=SETTINGS.indexing.batch_size,
    batch_delay=SETTINGS.indexing.batch_delay_seconds,
):
    """Remove new downloads and their indexes if this preparation cannot finish."""
    filing_root = ROOT / SETTINGS.paths.filings_dir
    before = {ticker: {p.name for p in (filing_root / ticker).glob('*') if p.is_dir()}
              for ticker in tickers}
    existing_tickers = {ticker for ticker in tickers if (filing_root / ticker).exists()}
    try:
        _prepare(tickers, batch_size, batch_delay)
    except BaseException:
        print('Preparation did not complete. Cleaning up new downloads and indexed data…', flush=True)
        for ticker in tickers:
            new_accessions = {p.name for p in (filing_root / ticker).glob('*') if p.is_dir()} - before[ticker]
            if not new_accessions:
                continue
            try:
                if ticker not in existing_tickers:
                    import corporate_atlas.services.delete_company as sec_delete_company
                    sec_delete_company.ROOT = ROOT
                    sec_delete_company.delete_company(ticker)
                else:
                    import corporate_atlas.services.delete_filings as sec_delete_filings
                    sec_delete_filings.ROOT = ROOT
                    sec_delete_filings.delete_filings([{'ticker': ticker, 'accession': a} for a in new_accessions])
            except Exception as cleanup_error:
                print(f'Cleanup failed for {ticker}: {cleanup_error}. Delete the affected download from Available company information.', flush=True)
        raise


def interrupted(signum, frame):
    # Allow cleanup to finish if the terminal sends a second interrupt.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise InterruptedError('Preparation interrupted; cleaning up new downloads.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--batch-size', type=int, default=SETTINGS.indexing.batch_size)
    parser.add_argument(
        '--batch-delay',
        type=float,
        default=SETTINGS.indexing.batch_delay_seconds,
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    prepare(args.tickers, args.batch_size, args.batch_delay)
