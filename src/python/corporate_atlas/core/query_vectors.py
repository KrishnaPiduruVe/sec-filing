"""Answer questions using retrieved SEC filing excerpts from Chroma."""
from langchain_core.messages import HumanMessage, SystemMessage
from corporate_atlas.core.llm_config import get_chat_model, get_model_identifier
from corporate_atlas.core.token_usage import record_chat_usage, record_embedding_usage
from corporate_atlas.core.vector_store import embedding_settings


def answer_question(question, llm=None, top_k=12, *, vector_store, tickers=None):
    if top_k <= 0:
        raise ValueError('top_k must be greater than zero.')
    where = None
    if tickers:
        normalized = [ticker.upper() for ticker in tickers]
        where = {'ticker': normalized[0]} if len(normalized) == 1 else {'ticker': {'$in': normalized}}
    documents = vector_store.similarity_search(question, k=top_k, filter=where)
    provider, model_name, _ = embedding_settings()
    record_embedding_usage([question], f'{provider}:{model_name}', operation='query_embedding')
    excerpts = []
    for document in documents:
        citation = '/'.join(str(document.metadata.get(key, '')) for key in ('ticker', 'filing', 'chunk_index'))
        excerpts.append(f"[{citation}] Source: {document.metadata.get('source','')}\n{document.page_content}")
    context = '\n'.join(excerpts) or '(No relevant excerpts found.)'
    messages = [SystemMessage(content=(
        'Answer using only the supplied company-source context as factual grounding. '
        'Cite ticker/filing identifiers when present. If the context does not contain '
        'the answer, say the available filing facts are insufficient. Do not add outside facts.')),
        HumanMessage(content=f'Relevant filing excerpts:\n{context}\n\nQuestion: {question}')]
    response = (llm if llm is not None else get_chat_model()).invoke(messages)
    record_chat_usage('answer', get_model_identifier(), messages, response)
    return str(response.content)
