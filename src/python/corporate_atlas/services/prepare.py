"""Download and prepare selected tickers, reusing existing local artifacts."""
import argparse
import json
import signal
import sys
from pathlib import Path

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT
STAGES = ('download', 'profile', 'vector')


def event(stage, status, message):
    print('WORKFLOW ' + json.dumps(dict(stage=stage, status=status, message=message)), flush=True)


def html_files(ticker):
    return sorted(p for p in (ROOT / 'sec_filings' / ticker).glob('*/*')
                  if p.is_file() and p.suffix.lower() in {'.htm', '.html'} and p.stat().st_size)


def vector_complete(ticker):
    """Check actual stored chunk IDs, rather than assuming a directory is ready."""
    if not (ROOT / 'chroma_db').is_dir():
        return False
    from corporate_atlas.core.filing_text import html_to_text, chunk_text
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
    existing = {item for item in collection.get(where={'ticker': ticker}, include=[])['ids'] if ':public:' not in item}
    return bool(expected) and expected == existing


def run_script(script, *args):
    # Execute in this process so cancellation also stops the active pipeline stage.
    from importlib import import_module
    previous_argv = sys.argv
    try:
        sys.argv = [script, *args]
        import_module(script).main()
    finally:
        sys.argv = previous_argv


def prepare_public_sources(tickers):
    """Cache company descriptions and annual facts for the downloaded tickers."""
    import requests
    from corporate_atlas.services.research import add_company
    results = {}
    for ticker in tickers:
        try:
            company = add_company(ticker)
        except (requests.RequestException, LookupError, ValueError) as exc:
            print(f'Public company data for {ticker} could not be refreshed: {exc}. SEC filing preparation will continue.', flush=True)
            continue
        results[ticker] = company
        if company.get('profile'):
            print(f'Wikimedia company profile available for {ticker}.', flush=True)
        for warning in company.get('warnings', []):
            print(f'{ticker}: {warning}', flush=True)

    return results


class SourceUnavailableError(ValueError):
    def __init__(self, ticker):
        self.details = {'tickers':[ticker], 'sources':['SEC EDGAR', 'Wikimedia'],
                        'message':f'Check the ticker {ticker}. No usable content was found in SEC EDGAR or Wikimedia. The sources may also be temporarily unavailable.'}
        super().__init__(self.details['message'])


def _prepare(tickers, batch_size=5, batch_delay=65):
    import requests
    from corporate_atlas.services.company_store import index_snapshot
    for ticker in tickers:
        event('download', 'running', f'Checking SEC filings for {ticker}')
        if not html_files(ticker):
            try:
                run_script('corporate_atlas.core.sec_quarterly_filings', ticker)
            except (LookupError, requests.RequestException) as exc:
                print(f'{ticker}: SEC filings unavailable: {exc}', flush=True)
        else:
            print(f'We already have downloaded information for {ticker}. Reusing saved filings.', flush=True)
        event('download', 'completed', 'SEC source checked')
        event('profile', 'running', f'Checking Wikimedia and annual facts for {ticker}')
        profiles = prepare_public_sources([ticker]) or {}
        company = profiles.get(ticker)
        event('profile', 'completed', 'Public company sources checked')
        has_public = bool(company and ((company.get('profile') or {}).get('summary') or company.get('history')))
        has_filings = bool(html_files(ticker))
        ready = vector_complete(ticker)
        if not (has_public or has_filings or ready):
            raise SourceUnavailableError(ticker)
        event('vector', 'running', f'Indexing available content for {ticker}')
        if has_filings and not ready:
            run_script('corporate_atlas.core.build_vector_store_paced', '--tickers', ticker,
                       '--batch-size', str(batch_size), '--batch-delay', str(batch_delay))
        if has_public:
            if has_filings and not ready and batch_delay:
                import time
                time.sleep(batch_delay)
            index_snapshot(company)
        event('vector', 'completed', f'{ticker} content available in Chroma')
    print('Your information is ready. Ask a question below.', flush=True)


def prepare(tickers, batch_size=5, batch_delay=65):
    """Remove new downloads and their indexes if this preparation cannot finish."""
    before = {ticker: {p.name for p in (ROOT / 'sec_filings' / ticker).glob('*') if p.is_dir()}
              for ticker in tickers}
    existing_tickers = {ticker for ticker in tickers if (ROOT / 'sec_filings' / ticker).exists()}
    try:
        _prepare(tickers, batch_size, batch_delay)
    except BaseException:
        print('Preparation did not complete. Cleaning up new downloads and indexed data…', flush=True)
        for ticker in tickers:
            new_accessions = {p.name for p in (ROOT / 'sec_filings' / ticker).glob('*') if p.is_dir()} - before[ticker]
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
    parser.add_argument('--batch-size', type=int, default=5)
    parser.add_argument('--batch-delay', type=float, default=65)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        prepare(args.tickers, args.batch_size, args.batch_delay)
    except SourceUnavailableError as exc:
        print('SOURCE_UNAVAILABLE ' + json.dumps(exc.details), flush=True)
        sys.exit(1)
