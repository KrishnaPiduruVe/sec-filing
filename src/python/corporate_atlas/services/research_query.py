"""Answer from selected public company profiles, annual facts, and optional local RAG context."""
import argparse
import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.services.research import research_company
from corporate_atlas.core.llm_config import get_chat_model, get_model_identifier
from corporate_atlas.core.token_usage import record_chat_usage, record_embedding_usage


def research_context(tickers, question, mode='vector', top_k=12):
    if mode != 'vector':
        raise ValueError('Only vector retrieval is supported.')
    profiles = [research_company(ticker) for ticker in tickers]
    if not any(profile.get('profile') or profile.get('history') for profile in profiles):
        from corporate_atlas.services.company_store import indexed_companies
        if not any(ticker in indexed_companies() for ticker in tickers):
            raise ValueError('Download and index company content before asking a question.')
    context = ['Public company snapshots (not live prices):\n' + json.dumps(profiles, ensure_ascii=False)]
    vector_root = DATA_ROOT / 'chroma_db'
    if vector_root.is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(vector_root))
        try:
            collection = client.get_collection('sec_filings')
        except chromadb.errors.NotFoundError:
            collection = None
        where = {'ticker': {'$in': tickers}}
        if collection is not None and collection.get(where=where, limit=1, include=[])['ids']:
            from corporate_atlas.core.vector_store import open_vector_store, embedding_settings
            store = open_vector_store(vector_root)
            documents = store.similarity_search(question, k=top_k, filter=where)
            provider, model, _ = embedding_settings()
            record_embedding_usage([question], f'{provider}:{model}', operation='query_embedding')
            context.append('Locally indexed filing excerpts:\n' + '\n'.join(
                f"[{d.metadata.get('ticker')}/{d.metadata.get('filing')}/{d.metadata.get('chunk_index')}] Source: {d.metadata.get('source', '')} {d.page_content}" for d in documents))
    return '\n\n'.join(context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--mode', choices=['vector'], default='vector')
    parser.add_argument('--top-k', type=int, default=12)
    parser.add_argument('question')
    args = parser.parse_args()
    context = research_context(args.tickers, args.question, args.mode, args.top_k)
    messages = [SystemMessage(content=(
        'Answer only from the supplied public-company data and filing context. '
        'Cite source URLs using Markdown links and reporting-period dates for financial comparisons. '
        'Distinguish general Wikimedia descriptions from SEC facts and retrieved filing excerpts. '
        'Fiscal year ends can differ across companies; do not imply identical periods. '
        'State when a fact is unavailable. Do not infer current stock prices, make buy/sell recommendations, '
        'or predict prices from these historical snapshots.')),
        HumanMessage(content=f'{context}\n\nQuestion: {args.question}')]
    response = get_chat_model().invoke(messages)
    record_chat_usage('answer', get_model_identifier(), messages, response)
    print(str(response.content))


if __name__ == '__main__':
    main()
