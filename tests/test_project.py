from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from build_knowledge_graph import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    _add_extraction,
    build_graphs,
    chunk_text,
    html_to_text,
)
from query_graph import load_graph, rank_triples
from sec_quarterly_filings import SecClient, latest_10q, ticker_cik_map


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


def test_build_graphs_persists_graphml_and_can_be_loaded(tmp_path: Path) -> None:
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
