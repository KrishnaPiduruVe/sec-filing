"""Extract filing facts into per-ticker and combined NetworkX knowledge graphs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from corporate_atlas.paths import DATA_ROOT
from typing import Literal

import networkx as nx
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from corporate_atlas.core.llm_config import get_chat_model, get_model_identifier
from corporate_atlas.core.token_usage import record_chat_usage
from corporate_atlas.settings import SETTINGS

EntityType = Literal[
    "Company",
    "Person",
    "Metric",
    "Segment",
    "Product",
    "Risk",
    "Date",
    "Amount",
]
FILING_ROOT = DATA_ROOT / SETTINGS.paths.filings_dir
GRAPH_ROOT = DATA_ROOT / SETTINGS.paths.graph_dir


class ExtractedEntity(BaseModel):
    name: str = Field(description="The exact entity name or value mentioned in the filing.")
    entity_type: EntityType
    evidence: str = Field(description="A short supporting quote or faithful excerpt.")


class ExtractedRelationship(BaseModel):
    subject: str = Field(description="Name of the source entity.")
    subject_type: EntityType
    predicate: str = Field(description="A concise relationship label.")
    object: str = Field(description="Name of the target entity or value.")
    object_type: EntityType
    evidence: str = Field(description="A short supporting quote or faithful excerpt.")


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    if not text:
        raise ValueError("The filing HTML contained no readable text.")
    return text


def chunk_text(
    text: str,
    chunk_size: int = SETTINGS.graph.chunk_size,
    overlap: int = SETTINGS.graph.overlap,
) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0.")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _node_id(ticker: str, entity_type: str, name: str) -> str:
    normalized_name = re.sub(r"\s+", " ", name).strip().casefold()
    return f"{ticker.upper()}|{entity_type}|{normalized_name}"


def _add_entity(
    graph: nx.MultiDiGraph,
    ticker: str,
    entity_type: str,
    name: str,
    evidence: str,
) -> str:
    label = re.sub(r"\s+", " ", name).strip()
    if not label:
        raise ValueError("LLM extraction returned an entity with an empty name.")
    node_id = _node_id(ticker, entity_type, label)
    if graph.has_node(node_id):
        existing = graph.nodes[node_id].get("evidence", "")
        evidence_parts = [part for part in existing.split(" | ") if part]
        if evidence and evidence not in evidence_parts:
            evidence_parts.append(evidence)
        graph.nodes[node_id]["evidence"] = " | ".join(evidence_parts)[
            :SETTINGS.graph.max_evidence_chars
        ]
    else:
        graph.add_node(
            node_id,
            ticker=ticker.upper(),
            entity_type=entity_type,
            label=label,
            evidence=evidence[:SETTINGS.graph.max_evidence_chars],
        )
    return node_id


def _add_extraction(
    graph: nx.MultiDiGraph,
    result: ExtractionResult,
    ticker: str,
    filing: str,
    chunk_number: int,
) -> None:
    for entity in result.entities:
        _add_entity(graph, ticker, entity.entity_type, entity.name, entity.evidence)

    for relationship_number, relationship in enumerate(result.relationships):
        subject = _add_entity(
            graph,
            ticker,
            relationship.subject_type,
            relationship.subject,
            relationship.evidence,
        )
        target = _add_entity(
            graph,
            ticker,
            relationship.object_type,
            relationship.object,
            relationship.evidence,
        )
        graph.add_edge(
            subject,
            target,
            key=(
                f"{ticker.upper()}|{filing}|{chunk_number}|"
                f"{relationship_number}|{relationship.predicate}"
            ),
            relation=relationship.predicate,
            evidence=relationship.evidence[:SETTINGS.graph.max_evidence_chars],
            ticker=ticker.upper(),
            filing=filing,
            chunk_index=chunk_number,
        )


def build_filing_graph(
    html_path: Path,
    ticker: str,
    llm,
) -> nx.MultiDiGraph:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_text(html_to_text(html))
    structured_llm = llm.with_structured_output(ExtractionResult)
    graph = nx.MultiDiGraph()
    instructions = (
        "Extract only facts explicitly supported by this SEC filing excerpt. "
        "Use only the requested entity types: Company, Person, Metric, Segment, "
        "Product, Risk, Date, and Amount. Include concise evidence for every "
        "entity and relationship. Do not infer unsupported facts."
    )
    for chunk_number, chunk in enumerate(chunks):
        messages = [
            SystemMessage(content=instructions),
            HumanMessage(content=f"Filing excerpt:\n{chunk}"),
        ]
        result = structured_llm.invoke(messages)
        record_chat_usage("graph_extraction", get_model_identifier(), messages, result)
        if not isinstance(result, ExtractionResult):
            raise TypeError("Structured LLM output did not match ExtractionResult.")
        _add_extraction(
            graph,
            result,
            ticker,
            html_path.parent.name,
            chunk_number,
        )
    return graph


def build_graphs(
    tickers: list[str] | None = None,
    filing_root: Path = FILING_ROOT,
    graph_root: Path = GRAPH_ROOT,
    llm=None,
) -> dict[str, Path]:
    if tickers is None:
        if not filing_root.is_dir():
            raise FileNotFoundError(f"Filing directory does not exist: {filing_root}")
        tickers = sorted(path.name.upper() for path in filing_root.iterdir() if path.is_dir())
    if not tickers:
        raise FileNotFoundError(f"No ticker filing directories found in {filing_root}.")

    model = llm if llm is not None else get_chat_model()
    graph_root.mkdir(parents=True, exist_ok=True)
    ticker_graphs: dict[str, nx.MultiDiGraph] = {}
    outputs: dict[str, Path] = {}

    for ticker in tickers:
        ticker = ticker.upper()
        ticker_dir = filing_root / ticker
        if not ticker_dir.is_dir():
            raise FileNotFoundError(f"No downloaded filings found for {ticker}: {ticker_dir}")
        html_paths = sorted(
            path
            for path in ticker_dir.glob("*/*")
            if path.is_file() and path.suffix.lower() in {".htm", ".html"}
        )
        if not html_paths:
            raise FileNotFoundError(f"No downloaded HTML filings found for {ticker}.")

        graph = nx.MultiDiGraph()
        for html_path in html_paths:
            filing_graph = build_filing_graph(html_path, ticker, model)
            graph = nx.compose(graph, filing_graph)
        output_path = graph_root / f"{ticker}.graphml"
        nx.write_graphml(graph, output_path)
        ticker_graphs[ticker] = graph
        outputs[ticker] = output_path

    combined = nx.MultiDiGraph()
    for graph in ticker_graphs.values():
        combined = nx.compose(combined, graph)
    combined_path = graph_root / "combined.graphml"
    nx.write_graphml(combined, combined_path)
    outputs["combined"] = combined_path
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        nargs="+",
        help=(
            "Tickers to process (default: all directories under "
            f"{SETTINGS.paths.filings_dir}/)"
        ),
    )
    parser.add_argument("--filing-dir", type=Path, default=FILING_ROOT)
    parser.add_argument("--graph-dir", type=Path, default=GRAPH_ROOT)
    args = parser.parse_args()
    for ticker, path in build_graphs(args.tickers, args.filing_dir, args.graph_dir).items():
        print(f"Saved {ticker} graph to {path}")


if __name__ == "__main__":
    main()
