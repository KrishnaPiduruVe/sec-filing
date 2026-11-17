"""Delete one company's local filings and indexes without affecting other tickers."""
import argparse
from pathlib import Path
import re
import shutil

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT


def delete_company(ticker):
    ticker = ticker.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker):
        raise ValueError('Invalid ticker.')
    folder = ROOT / 'sec_filings' / ticker
    if folder.is_symlink():
        raise ValueError('Refusing to delete a linked company folder.')
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            collection.delete(where={'ticker': ticker})
    if folder.exists():
        shutil.rmtree(folder)
    print(f'{ticker} company information deleted. Other companies and token usage records are preserved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    args = parser.parse_args()
    for ticker in args.tickers:
        delete_company(ticker)
