from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import networkx as nx
import pytest

import corporate_atlas.core.llm_config as llm_config
from corporate_atlas.core.build_vector_store import build_vector_store
from corporate_atlas.core.build_knowledge_graph import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    _add_extraction,
    build_graphs,
    chunk_text,
    html_to_text,
)
from corporate_atlas.core.query_graph import answer_question, load_graph, rank_triples
from corporate_atlas.core.sec_quarterly_filings import SecClient, latest_10q, ticker_cik_map
from corporate_atlas.core.token_usage import count_tokens, record_chat_usage, usage_summary


def test_ticker_map_pads_cik_and_normalizes_ticker() -> None:
    assert ticker_cik_map({"0": {"ticker": "aapl", "cik_str": 320193}}) == {
        "AAPL": "0000320193"
    }


def test_latest_10q_ignores_amendments_and_selects_latest_filed() -> None:
    filings = {
        "form": ["10-Q", "10-Q/A", "10-Q"],
        "accessionNumber": [
            "0000320193-25-000010",
            "0000320193-25-000020",
            "0000320193-25-000030",
        ],
        "primaryDocument": ["older.htm", "amended.htm", "latest.htm"],
        "filingDate": ["2025-02-01", "2025-03-01", "2025-05-01"],
    }
    assert latest_10q(filings)["primaryDocument"] == "latest.htm"


def test_chunk_text_has_expected_overlap_and_rejects_invalid_sizes() -> None:
    assert chunk_text("abcdefghij", chunk_size=6, overlap=2) == [
        "abcdef",
        "efghij",
    ]
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=5, overlap=5)


def test_html_to_text_removes_non_visible_script_content() -> None:
    assert html_to_text("<p>Revenue was 10.</p><script>hidden()</script>") == (
        "Revenue was 10."
    )


def test_graph_extraction_creates_typed_relationship_and_query_ranks_it() -> None:
    graph = nx.MultiDiGraph()
    result = ExtractionResult(
        entities=[
            ExtractedEntity(
                name="Apple Inc.",
                entity_type="Company",
                evidence="Apple reported revenue.",
            ),
            ExtractedEntity(
                name="Revenue",
                entity_type="Metric",
                evidence="Revenue was $100 million.",
            ),
        ],
        relationships=[
            ExtractedRelationship(
                subject="Apple Inc.",
                subject_type="Company",
                predicate="reported",
                object="Revenue",
                object_type="Metric",
                evidence="Apple reported revenue of $100 million.",
            )
        ],
    )
    _add_extraction(graph, result, "AAPL", "0000320193-25-000001", 0)
    triples = rank_triples("What revenue did Apple report?", graph)
    assert len(triples) == 1
    assert "Apple Inc. [Company] -[reported]-> Revenue [Metric]" in triples[0]
    assert "100 million" in triples[0]


def test_build_graphs_persists_graphml_and_can_be_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TOKEN_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("PRIMARY_MODEL", "TEST")
    monkeypatch.setenv("TEST_MODEL_NAME", "test-model")

    class FakeModel:
        def with_structured_output(self, schema):
            assert schema is ExtractionResult
            return self

        def invoke(self, messages):
            return ExtractionResult(
                entities=[
                    ExtractedEntity(
                        name="Apple Inc.",
                        entity_type="Company",
                        evidence="Apple reported revenue.",
                    ),
                    ExtractedEntity(
                        name="Revenue",
                        entity_type="Metric",
                        evidence="Revenue was reported.",
                    ),
                ],
                relationships=[
                    ExtractedRelationship(
                        subject="Apple Inc.",
                        subject_type="Company",
                        predicate="reported",
                        object="Revenue",
                        object_type="Metric",
                        evidence="Apple reported revenue.",
                    )
                ],
            )

    filing = tmp_path / "filings" / "AAPL" / "accession" / "primary.htm"
    filing.parent.mkdir(parents=True)
    filing.write_text("<p>Apple reported revenue.</p>", encoding="utf-8")
    outputs = build_graphs(
        ["AAPL"],
        filing_root=tmp_path / "filings",
        graph_root=tmp_path / "graphs",
        llm=FakeModel(),
    )
    assert outputs["AAPL"].is_file()
    assert outputs["combined"].is_file()
    graph = load_graph(tmp_path / "graphs")
    assert graph.number_of_edges() == 1
    assert len(rank_triples("Apple revenue", graph)) == 1


def test_load_graph_combines_all_ticker_graphs_or_selected_tickers(
    tmp_path: Path,
) -> None:
    for ticker, company, metric in (
        ("AAPL", "Apple", "revenue"),
        ("WFC", "Wells Fargo", "credit losses"),
    ):
        graph = nx.MultiDiGraph()
        subject = f"{ticker}|Company|{company.casefold()}"
        target = f"{ticker}|Metric|{metric}"
        graph.add_node(subject, ticker=ticker, entity_type="Company", label=company)
        graph.add_node(target, ticker=ticker, entity_type="Metric", label=metric)
        graph.add_edge(subject, target, relation="reported", evidence=f"{company} reported {metric}.")
        nx.write_graphml(graph, tmp_path / f"{ticker}.graphml")

    combined = nx.MultiDiGraph()
    combined.add_edge("stale", "stale", relation="stale")
    nx.write_graphml(combined, tmp_path / "combined.graphml")

    all_graphs = load_graph(tmp_path)
    selected_graphs = load_graph(tmp_path, ["AAPL", "WFC"])
    assert all_graphs.number_of_edges() == 2
    assert selected_graphs.number_of_edges() == 2
    assert len(rank_triples("revenue credit losses", all_graphs)) == 2


def test_sec_client_sends_configured_user_agent_on_each_request(monkeypatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Filing Researcher filings@company.org")

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeSession:
        def __init__(self) -> None:
            self.headers = []

        def get(self, url, **kwargs):
            self.headers.append(kwargs["headers"])
            return FakeResponse()

    session = FakeSession()
    client = SecClient(session=session)
    client.get("https://www.sec.gov/test")
    client.get("https://data.sec.gov/test")
    assert len(session.headers) == 2
    assert all(
        header["User-Agent"] == "Filing Researcher filings@company.org"
        for header in session.headers
    )


def test_chat_usage_records_provider_counts(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("TOKEN_USAGE_DB", str(database))

    class FakeResponse:
        content = "A grounded response."
        usage_metadata = {"input_tokens": 17, "output_tokens": 6}

    record_chat_usage("answer", "test-model", "Question and context", FakeResponse())
    assert usage_summary(database) == [("answer", 17, 6, 1, 0)]


def test_embedding_model_uses_provider_model_and_options_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "cohere")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-v4.0")
    monkeypatch.setenv("EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_OPTIONS", '{"output_dimension": 512}')
    captured = {}
    expected_model = object()

    def fake_init_embeddings(model, *, provider, **kwargs):
        captured.update(model=model, provider=provider, **kwargs)
        return expected_model

    monkeypatch.setattr(llm_config, "init_embeddings", fake_init_embeddings)

    assert llm_config.get_embedding_model() is expected_model
    assert captured == {
        "model": "embed-v4.0",
        "provider": "cohere",
        "api_key": "embedding-key",
        "output_dimension": 512,
    }


def test_google_embedding_adapter_uses_configured_chat_key_and_model(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PRIMARY_MODEL", "GOOGLE")
    monkeypatch.setenv("GOOGLE_MODEL_PROVIDER", "google_genai")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "google_genai")
    monkeypatch.setenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_OPTIONS", '{"task_type": "RETRIEVAL_DOCUMENT"}')
    captured = {}
    module = ModuleType("langchain_google_genai")

    class FakeGoogleEmbeddings:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    module.GoogleGenerativeAIEmbeddings = FakeGoogleEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_google_genai", module)

    model = llm_config.get_embedding_model()

    assert isinstance(model, FakeGoogleEmbeddings)
    assert captured == {
        "model": "models/gemini-embedding-001",
        "task_type": "RETRIEVAL_DOCUMENT",
        "api_key": "google-key",
    }


def test_embedding_settings_use_selected_provider_api_key(monkeypatch) -> None:
    monkeypatch.setenv("PRIMARY_MODEL", "GOOGLE")
    monkeypatch.setenv("GOOGLE_MODEL_PROVIDER", "google_genai")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-chat-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-embedding-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    assert llm_config.get_embedding_settings() == (
        "openai",
        "text-embedding-3-small",
        "openai-embedding-key",
    )


def test_build_vector_store_indexes_text_and_removes_only_stale_ticker_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("TOKEN_USAGE_DB", str(database))
    filing = tmp_path / "filings" / "AAPL" / "accession" / "primary.htm"
    filing.parent.mkdir(parents=True)
    filing.write_text(
        "<p>Apple quarterly revenue increased.</p><script>hidden</script>",
        encoding="utf-8",
    )

    class FakeVectorStore:
        added = []
        deleted = []

        def get(self, *, where):
            assert where == {"ticker": {"$in": ["AAPL"]}}
            return {"ids": ["AAPL:accession:0", "AAPL:stale:2"]}

        def add_texts(self, *, texts, metadatas, ids):
            self.added.extend(zip(texts, metadatas, ids))

        def delete(self, *, ids):
            self.deleted.extend(ids)

    store = FakeVectorStore()
    monkeypatch.setattr(
        "corporate_atlas.core.build_vector_store.embedding_settings",
        lambda: ("openai", "text-embedding-3-small", "test-key"),
    )
    monkeypatch.setattr(
        "corporate_atlas.core.build_vector_store.open_vector_store",
        lambda path, *, create: store,
    )

    count = build_vector_store(
        ["AAPL"],
        filing_root=tmp_path / "filings",
        vector_root=tmp_path / "vectors",
        chunk_size=18,
        overlap=4,
    )

    assert count == len(store.added) > 1
    assert all("hidden" not in text for text, _, _ in store.added)
    assert store.added[0][1]["ticker"] == "AAPL"
    assert store.deleted == ["AAPL:stale:2"]
    assert usage_summary(database)[0][0] == "embedding"


def test_hybrid_answer_retrieves_vector_context_and_records_both_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("TOKEN_USAGE_DB", str(database))
    monkeypatch.setenv("PRIMARY_MODEL", "OPENAI")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")

    graph = nx.MultiDiGraph()
    graph.add_node("company", label="Apple", entity_type="Company")
    graph.add_node("metric", label="Revenue", entity_type="Metric")
    graph.add_edge("company", "metric", relation="reported", evidence="Revenue rose.")

    class FakeDocument:
        page_content = "Revenue increased during the quarter."
        metadata = {"ticker": "AAPL", "filing": "accession", "chunk_index": 0}

    class FakeVectorStore:
        filter = None

        def similarity_search(self, question, *, k, filter):
            assert question == "What was Apple's revenue?"
            assert k == 4
            self.filter = filter
            return [FakeDocument()]

    class FakeModel:
        def invoke(self, messages):
            assert "Relevant graph triples" in messages[1].content
            assert "Relevant filing excerpts" in messages[1].content
            return type(
                "Response",
                (),
                {
                    "content": "Revenue increased.",
                    "usage_metadata": {"input_tokens": 23, "output_tokens": 5},
                },
            )()

    vector_store = FakeVectorStore()
    response = answer_question(
        "What was Apple's revenue?",
        graph,
        FakeModel(),
        top_k=4,
        mode="hybrid",
        vector_store=vector_store,
        tickers=["AAPL"],
    )
    assert response == "Revenue increased."
    assert vector_store.filter == {"ticker": "AAPL"}
    assert usage_summary(database) == [
        ("answer", 23, 5, 1, 0),
        (
            "query_embedding",
            count_tokens(
                "What was Apple's revenue?",
                "text-embedding-3-small",
            ),
            0,
            1,
            1,
        ),
    ]
