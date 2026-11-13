"""Answer questions using relevant triples from saved filing knowledge graphs."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

import networkx as nx
from langchain_core.messages import HumanMessage, SystemMessage

from llm_config import get_chat_model, get_model_identifier
from token_usage import record_chat_usage, record_embedding_usage
from vector_store import DEFAULT_VECTOR_ROOT, embedding_settings, open_vector_store

GRAPH_ROOT = Path("knowledge_graphs")
STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "their",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


def _keywords(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.casefold())
        if len(word) > 1 and word not in STOP_WORDS
    }


def rank_triples(
    question: str,
    graph: nx.MultiDiGraph,
    top_k: int = 12,
) -> list[str]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")
    query_words = _keywords(question)
    if not query_words:
        return []

    scored: list[tuple[int, str]] = []
    for subject_id, object_id, _, data in graph.edges(keys=True, data=True):
        subject = graph.nodes[subject_id]
        target = graph.nodes[object_id]
        relation = str(data.get("relation", "related to"))
        evidence = str(data.get("evidence", ""))
        searchable = " ".join(
            (
                str(subject.get("label", subject_id)),
                relation,
                str(target.get("label", object_id)),
                evidence,
            )
        )
        overlap = len(query_words & _keywords(searchable))
        if overlap == 0:
            continue
        triple = (
            f"({subject.get('label', subject_id)} [{subject.get('entity_type', 'Unknown')}] "
            f"-[{relation}]-> {target.get('label', object_id)} "
            f"[{target.get('entity_type', 'Unknown')}])"
        )
        details = []
        if evidence:
            details.append(f"Evidence: {evidence}")
        if data.get("filing"):
            details.append(f"Filing: {data['filing']}")
        scored.append((overlap, " ".join((triple, *details))))

    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [triple for _, triple in scored[:top_k]]


def answer_question(
    question: str,
    graph: nx.MultiDiGraph | None = None,
    llm=None,
    top_k: int = 12,
    *,
    mode: str = "graph",
    vector_store=None,
    tickers: Sequence[str] | None = None,
) -> str:
    if mode not in {"graph", "vector", "hybrid"}:
        raise ValueError("mode must be 'graph', 'vector', or 'hybrid'.")
    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")
    if mode in {"graph", "hybrid"} and graph is None:
        raise ValueError("A knowledge graph is required for graph or hybrid mode.")
    if mode in {"vector", "hybrid"} and vector_store is None:
        raise ValueError("A vector store is required for vector or hybrid mode.")

    triples = (
        rank_triples(question, graph, top_k=top_k)
        if mode in {"graph", "hybrid"} and graph is not None
        else []
    )
    documents = []
    if mode in {"vector", "hybrid"}:
        where = None
        if tickers:
            normalized_tickers = [ticker.upper() for ticker in tickers]
            where = (
                {"ticker": normalized_tickers[0]}
                if len(normalized_tickers) == 1
                else {"ticker": {"$in": normalized_tickers}}
            )
        documents = vector_store.similarity_search(
            question,
            k=top_k,
            filter=where,
        )
        provider, embedding_model, _ = embedding_settings()
        record_embedding_usage(
            [question],
            f"{provider}:{embedding_model}",
            operation="query_embedding",
        )

    model = llm if llm is not None else get_chat_model()
    context_sections = []
    if mode in {"graph", "hybrid"}:
        graph_context = "\n".join(f"- {triple}" for triple in triples)
        context_sections.append(f"Relevant graph triples:\n{graph_context or '(None found.)'}")
    if mode in {"vector", "hybrid"}:
        excerpts = []
        for document in documents:
            metadata = document.metadata
            citation = "/".join(
                str(metadata.get(key, ""))
                for key in ("ticker", "filing", "chunk_index")
            )
            excerpts.append(f"- [{citation}] {document.page_content}")
        context_sections.append(
            "Relevant filing excerpts:\n" + ("\n".join(excerpts) or "(None found.)")
        )
    context = "\n\n".join(context_sections)
    messages = [
        SystemMessage(
            content=(
                "Answer the question using only the supplied SEC filing context "
                "as factual grounding. Cite ticker/filing identifiers when present. "
                "If the context does not contain the answer, say that the available "
                "filing facts are insufficient. Do not add outside facts."
            )
        ),
        HumanMessage(
            content=f"{context}\n\nQuestion: {question}"
        ),
    ]
    response = model.invoke(messages)
    record_chat_usage("answer", get_model_identifier(), messages, response)
    return str(response.content)


def load_graph(
    graph_dir: Path = GRAPH_ROOT,
    ticker: str | Sequence[str] | None = None,
) -> nx.MultiDiGraph:
    if ticker is None:
        graph_paths = sorted(
            path
            for path in graph_dir.glob("*.graphml")
            if path.name.casefold() != "combined.graphml"
        )
        if not graph_paths:
            combined_path = graph_dir / "combined.graphml"
            if not combined_path.is_file():
                raise FileNotFoundError(
                    f"No ticker or combined knowledge graphs found in {graph_dir}."
                )
            graph_paths = [combined_path]
    else:
        tickers = [ticker] if isinstance(ticker, str) else list(ticker)
        if not tickers:
            raise ValueError("Provide at least one ticker, or omit the ticker filter.")
        graph_paths = [graph_dir / f"{symbol.upper()}.graphml" for symbol in tickers]

    graph = nx.MultiDiGraph()
    for graph_path in graph_paths:
        if not graph_path.is_file():
            raise FileNotFoundError(f"Knowledge graph not found: {graph_path}")
        ticker_graph = nx.read_graphml(
            graph_path,
            node_type=str,
            force_multigraph=True,
        )
        if not isinstance(ticker_graph, nx.MultiDiGraph):
            raise TypeError(f"Expected a directed multigraph in {graph_path}.")
        graph = nx.compose(graph, ticker_graph)
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="Question to answer; omit for interactive mode")
    parser.add_argument(
        "--ticker",
        "--tickers",
        action="append",
        dest="tickers",
        help=(
            "Limit the query to ticker graphs; repeat the option or use a "
            "comma-separated list (default: all available graphs)"
        ),
    )
    parser.add_argument("--graph-dir", type=Path, default=GRAPH_ROOT)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_ROOT)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument(
        "--mode",
        choices=("graph", "vector", "hybrid"),
        default="hybrid",
        help="Retrieval source (default: hybrid graph and filing-vector search)",
    )
    args = parser.parse_args()
    tickers = (
        [
            ticker.strip()
            for selection in args.tickers
            for ticker in selection.split(",")
            if ticker.strip()
        ]
        if args.tickers
        else None
    )
    graph = (
        load_graph(args.graph_dir, tickers)
        if args.mode in {"graph", "hybrid"}
        else None
    )
    vector_store = (
        open_vector_store(args.vector_dir)
        if args.mode in {"vector", "hybrid"}
        else None
    )
    model = get_chat_model()

    if args.question:
        print(
            answer_question(
                " ".join(args.question),
                graph,
                model,
                args.top_k,
                mode=args.mode,
                vector_store=vector_store,
                tickers=tickers,
            )
        )
        return
    while True:
        try:
            question = input("Question (or 'exit'): ").strip()
        except EOFError:
            break
        if question.casefold() in {"exit", "quit"}:
            break
        if question:
            print(
                answer_question(
                    question,
                    graph,
                    model,
                    args.top_k,
                    mode=args.mode,
                    vector_store=vector_store,
                    tickers=tickers,
                )
            )


if __name__ == "__main__":
    main()
