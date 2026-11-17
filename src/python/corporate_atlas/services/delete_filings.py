"""Delete selected ticker/accession downloads and their vector evidence."""
import argparse
import json
from pathlib import Path
import re
import shutil

from corporate_atlas.paths import DATA_ROOT

ROOT = DATA_ROOT


def validate_selections(selections):
    if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
        raise ValueError('Select 1–100 downloaded filings.')
    result = []
    for item in selections:
        if not isinstance(item, dict):
            raise ValueError('Invalid filing selection.')
        ticker = str(item.get('ticker', '')).upper()
        accession = str(item.get('accession', ''))
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
            raise ValueError('Invalid ticker or accession in selection.')
        selection = {'ticker': ticker, 'accession': accession}
        if selection not in result:
            result.append(selection)
    return result


def delete_filings(selections):
    selections = validate_selections(selections)
    targets = {(item['ticker'], item['accession']) for item in selections}
    for ticker, accession in targets:
        for path in (ROOT / 'sec_filings' / ticker, ROOT / 'sec_filings' / ticker / accession):
            if path.is_symlink():
                raise ValueError('Refusing to delete linked company data.')
    if (ROOT / 'chroma_db').is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(ROOT / 'chroma_db'))
        try:
            collection = client.get_collection('sec_filings')
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            for ticker, accession in targets:
                collection.delete(where={'$and': [{'ticker': ticker}, {'filing': accession}]})
    for ticker, accession in sorted(targets):
        folder = ROOT / 'sec_filings' / ticker / accession
        if folder.exists():
            shutil.rmtree(folder)
        parent = folder.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    for ticker, accession in sorted(targets):
        print(f'Deleted {ticker} filing {accession} and its indexed data.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selections', required=True)
    args = parser.parse_args()
    delete_filings(json.loads(args.selections))
