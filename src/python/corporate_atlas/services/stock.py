"""Fetch current market data and store it alongside the filing vectors."""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

from corporate_atlas.core.stock_market import (
    DEFAULT_VECTOR_ROOT,
    StockDataUnavailable,
    index_stock_documents,
)
from corporate_atlas.settings import SETTINGS


def prepare_stock_market(
    symbols,
    *,
    vector_root=DEFAULT_VECTOR_ROOT,
    range_name=SETTINGS.market_data.default_range,
    interval=SETTINGS.market_data.default_interval,
):
    """Fetch current stock records and add them to the vector database."""
    return index_stock_documents(symbols, vector_root=vector_root, range_name=range_name, interval=interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=None, help="Ticker symbols to fetch and embed.")
    parser.add_argument("tickers_positional", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_ROOT, help="Chroma persistence directory.")
    parser.add_argument(
        "--range",
        default=SETTINGS.market_data.default_range,
        choices=SETTINGS.market_data.supported_ranges,
        help="Stock chart range.",
    )
    parser.add_argument(
        "--interval",
        default=SETTINGS.market_data.default_interval,
        choices=list(SETTINGS.market_data.alpaca_timeframes),
        help="Stock chart interval.",
    )
    args = parser.parse_args()
    tickers = args.tickers or args.tickers_positional
    if not tickers:
        raise SystemExit("Provide at least one ticker symbol.")
    try:
        ids = prepare_stock_market(tickers, vector_root=args.vector_dir, range_name=args.range, interval=args.interval)
    except StockDataUnavailable as exc:
        raise SystemExit(str(exc)) from None
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise SystemExit(
                "A stock-data provider is rate limiting market-data requests. Wait a few minutes, then retry."
            ) from None
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise SystemExit(f"Market data request failed (HTTP {status}).") from None
    except requests.RequestException:
        raise SystemExit("Unable to reach a stock-data provider. Check your connection and try again.") from None
    print(f"Indexed {len(ids)} stock snapshots.")


if __name__ == "__main__":
    main()
