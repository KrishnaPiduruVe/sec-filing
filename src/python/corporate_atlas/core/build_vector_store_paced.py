"""Index SEC filings in paced batches, retrying temporary embedding quota errors.

Run: python -m corporate_atlas.core.build_vector_store_paced --tickers AAPL
Successful batches persist immediately. Reruns re-embed chunks using stable IDs.
Defaults target the observed Google free-tier limits; shared/daily quotas can
still be exhausted. Keep the embedding model consistent with the existing index.
"""

from __future__ import annotations

import argparse
import math
import time
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
    batch_size: int = SETTINGS.indexing.batch_size,
    batch_delay: float = SETTINGS.indexing.batch_delay_seconds,
    max_retries: int = SETTINGS.indexing.max_retries,
) -> int:
    """Index filing text by stable filing/chunk IDs; return the number indexed."""
    if batch_size <= 0 or max_retries < 0:
        raise ValueError("Require batch_size > 0 and max_retries >= 0.")
    if not math.isfinite(batch_delay) or batch_delay < 0:
        raise ValueError("batch_delay must be finite and nonnegative.")
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
    print(f"Prepared {len(documents)} chunks; batch size {batch_size}, pause {batch_delay:g}s.", flush=True)
    for start in range(0, len(documents), batch_size):
        if start and batch_delay:
            print(f"Waiting {batch_delay:g}s before next batch...", flush=True)
            time.sleep(batch_delay)
        end = min(start + batch_size, len(documents))
        for attempt in range(max_retries + 1):
            try:
                store.add_texts(
                    texts=documents[start:end],
                    metadatas=metadatas[start:end],
                    ids=ids[start:end],
                )
                break
            except Exception as exc:
                # LangChain wraps Google's original quota exception.
                message = str(exc).lower()
                quota_error = any(marker in message for marker in (
                    "429", "resource_exhausted", "rate_limit_exceeded"
                ))
                if not quota_error or attempt == max_retries:
                    raise
                wait = max(
                    SETTINGS.indexing.quota_backoff_seconds,
                    batch_delay,
                ) * SETTINGS.indexing.quota_backoff_multiplier**attempt
                print(f"Quota reached; retry {attempt + 1}/{max_retries} in {wait:g}s.", flush=True)
                time.sleep(wait)
        # Record completed batches even if a later batch fails.
        record_embedding_usage(documents[start:end], model)
        print(f"Indexed {end}/{len(documents)} chunks", flush=True)
    # Preserve old chunks until every replacement batch has succeeded.
    stale_ids = sorted(
        document_id for document_id in set(existing) - set(ids)
        if not document_id.startswith(("stock:", "wikimedia:"))
    )
    if stale_ids:
        store.delete(ids=stale_ids)
    return len(documents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", help="Tickers to index (default: all)")
    parser.add_argument("--filing-dir", type=Path, default=FILING_ROOT)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_ROOT)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=SETTINGS.indexing.batch_size,
        help="Chunks per batch.",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=SETTINGS.indexing.batch_delay_seconds,
        help="Seconds between successful batches.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=SETTINGS.indexing.max_retries,
        help="Quota retries per batch, with increasing waits.",
    )
    args = parser.parse_args()
    count = build_vector_store(
        args.tickers,
        args.filing_dir,
        args.vector_dir,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        batch_size=args.batch_size,
        batch_delay=args.batch_delay,
        max_retries=args.max_retries,
    )
    print(f"Indexed {count} filing chunks in {args.vector_dir}")


if __name__ == "__main__":
    main()
