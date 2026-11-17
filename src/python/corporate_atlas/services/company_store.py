"""Chroma is the authority for available companies and saved public snapshots."""
import json
from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.core.vector_store import COLLECTION_NAME


def collection():
    root = DATA_ROOT / 'chroma_db'
    if not root.is_dir():
        return None
    import chromadb
    try:
        return chromadb.PersistentClient(path=str(root)).get_collection(COLLECTION_NAME)
    except chromadb.errors.NotFoundError:
        return None


def indexed_companies():
    store = collection()
    if store is None:
        return {}
    result = {}
    for meta in store.get(include=['metadatas']).get('metadatas') or []:
        if meta and meta.get('ticker'):
            result.setdefault(meta['ticker'], {}).update({k: meta[k] for k in ('name','sector') if meta.get(k)})
            result.setdefault(meta['ticker'], {})
    return result


def snapshot(ticker):
    store = collection()
    if store is None:
        return None
    rows = store.get(where={'ticker': ticker}, include=['metadatas'])
    for meta in rows.get('metadatas') or []:
        if meta and meta.get('snapshot_json'):
            return json.loads(meta['snapshot_json'])
    return None


def index_snapshot(company):
    from corporate_atlas.core.filing_text import chunk_text
    from corporate_atlas.core.vector_store import open_vector_store, embedding_settings
    from corporate_atlas.core.token_usage import record_embedding_usage
    profile = company.get('profile') or {}
    if not profile.get('summary') and not company.get('history'):
        return 0
    ticker = company['ticker']
    text = f"General company profile [{profile.get('source_url','')}]:\n{profile.get('summary','')}\nAnnual financial facts [{company.get('financial_source','')}]:\n" + json.dumps(company.get('history', []))
    texts = chunk_text(text)
    ids = [f'{ticker}:public:{i}' for i in range(len(texts))]
    source = profile.get('source_url') or company.get('financial_source', '')
    metadata = [{'ticker':ticker, 'name':company.get('name',ticker), 'sector':company.get('sector',''),
                 'filing':'public-profile', 'source':source, 'source_type':'public', 'chunk_index':i,
                 **({'snapshot_json':json.dumps(company)} if i == 0 else {})} for i in range(len(texts))]
    store = open_vector_store(create=True)
    old = [item for item in store.get(where={'ticker':ticker}).get('ids',[]) if item.startswith(f'{ticker}:public:')]
    for attempt in range(4):
        try:
            store.add_texts(texts=texts, metadatas=metadata, ids=ids)
            break
        except Exception as exc:
            if attempt == 3 or not any(code in str(exc).lower() for code in ('429','resource_exhausted','rate_limit_exceeded')):
                raise
            import time
            time.sleep(65)

    stale = list(set(old)-set(ids))
    if stale: store.delete(ids=stale)
    provider, model, _ = embedding_settings()
    record_embedding_usage(texts, f'{provider}:{model}')
    return len(texts)


def migrate_cached_snapshots():
    """Move previously downloaded snapshots into existing Chroma metadata; no embeddings."""
    from corporate_atlas.services.research import CACHE_ROOT
    store = collection()
    if store is None:
        return 0
    data = store.get(include=['metadatas'])
    has_snapshot = {m['ticker'] for m in data.get('metadatas',[]) if m and m.get('snapshot_json') and m.get('ticker')}
    count = 0
    for identifier, meta in zip(data['ids'], data.get('metadatas',[])):
        ticker = (meta or {}).get('ticker')
        if not ticker or ticker in has_snapshot:
            continue
        path = CACHE_ROOT / f'{ticker}.json'
        if not path.is_file():
            continue
        company = json.loads(path.read_text())
        if company.get('ticker') != ticker or not (company.get('profile') or company.get('history')):
            continue
        store.update(ids=[identifier], metadatas=[{**meta, 'snapshot_json':json.dumps(company), 'name':company.get('name',ticker), 'sector':company.get('sector','')}])
        has_snapshot.add(ticker)
        count += 1
    return count
