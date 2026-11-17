"""Embed downloaded SEC filing text and persist it in Chroma."""

from __future__ import annotations

import argparse
from pathlib import Path
from corporate_atlas.paths import DATA_ROOT

from corporate_atlas.core.build_knowledge_graph import chunk_text, html_to_text
from corporate_atlas.core.token_usage import record_embedding_usage
from corporate_atlas.core.vector_store import DEFAULT_VECTOR_ROOT, embedding_settings, open_vector_store
from corporate_atlas.settings import SETTINGS

FILING_ROOT = DATA_ROOT / SETTINGS.paths.filings_dir
DEFAULT_CHUNK_SIZE = SETTINGS.indexing.chunk_size
DEFAULT_OVERLAP = SETTINGS.indexing.overlap


def build_vector_store(
    tickers: list[str] | None = None,
    filing_root: Path = FILING_ROOT,
    vector_root: Path = DEFAULT_VECTOR_ROOT,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> int:
    """Index filing text by stable filing/chunk IDs; return the number indexed."""
    if tickers is None:
        if not filing_root.is_dir():
            raise FileNotFoundError(f"Filing directory does not exist: {filing_root}")
        tickers = sorted(
            path.name.upper() for path in filing_root.iterdir() if path.is_dir()
        )
    tickers = [ticker.upper() for ticker in tickers]
    if not tickers:
        raise FileNotFoundError(f"No ticker filing directories found in {filing_root}.")
    # Validate chunk configuration before loading provider integrations.
    chunk_text("validation", chunk_size=chunk_size, overlap=overlap)

    documents: list[str] = []
    metadatas: list[dict[str, str | int]] = []
    ids: list[str] = []
    for ticker in tickers:
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
        for html_path in html_paths:
            text = html_to_text(
                html_path.read_text(encoding="utf-8", errors="replace")
            )
            accession = html_path.parent.name
            for chunk_number, chunk in enumerate(
                chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            ):
                documents.append(chunk)
                metadatas.append(
                    {
                        "ticker": ticker,
                        "filing": accession,
                        "chunk_index": chunk_number,
                        "source": str(html_path),
                    }
                )
                ids.append(f"{ticker}:{accession}:{chunk_number}")

    provider, model_name, _ = embedding_settings()
    model = f"{provider}:{model_name}"
    store = open_vector_store(vector_root, create=True)
    existing = store.get(where={"ticker": {"$in": tickers}}).get("ids", [])
    store.add_texts(texts=documents, metadatas=metadatas, ids=ids)
    stale_ids = sorted(
        document_id for document_id in set(existing) - set(ids)
        if not document_id.startswith(("stock:", "wikimedia:"))
    )
    if stale_ids:
        store.delete(ids=stale_ids)
    record_embedding_usage(documents, model)
    return len(documents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", help="Tickers to index (default: all)")
    parser.add_argument("--filing-dir", type=Path, default=FILING_ROOT)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_ROOT)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()
    count = build_vector_store(
        args.tickers,
        args.filing_dir,
        args.vector_dir,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )
    print(f"Indexed {count} filing chunks in {args.vector_dir}")


if __name__ == "__main__":
    main()
