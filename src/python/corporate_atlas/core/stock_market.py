"""Fetch and index current stock information for research queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
from typing import Any, Sequence

import requests
from dotenv import load_dotenv

from corporate_atlas.paths import ENV_FILE
from corporate_atlas.core.token_usage import record_embedding_usage
from corporate_atlas.core.vector_store import DEFAULT_VECTOR_ROOT, embedding_settings, open_vector_store
from corporate_atlas.settings import SETTINGS

YAHOO_FINANCE_BASE = SETTINGS.market_data.yahoo_base_url
ALPACA_DATA_BASE = SETTINGS.market_data.alpaca_base_url


class StockDataUnavailable(RuntimeError):
    """Raised when neither configured stock-data provider can return data."""


def _normalize_symbol(symbol: str) -> str:
    value = (symbol or "").strip().upper()
    ticker_pattern = rf"[A-Z][A-Z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}}"
    if not re.fullmatch(ticker_pattern, value):
        raise ValueError("Enter a valid ticker symbol.")
    return value


def _alpaca_headers() -> dict[str, str] | None:
    load_dotenv(ENV_FILE, override=False)
    key = os.getenv("APCA_API_KEY_ID", "").strip()
    secret = os.getenv("APCA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        return None
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("%", "")
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def _get_nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _fetch_yahoo_quote(symbol: str) -> dict[str, Any]:
    """Return detailed market and company metadata from Yahoo Finance."""
    tick = _normalize_symbol(symbol)
    response = requests.get(
        f"{YAHOO_FINANCE_BASE}{SETTINGS.market_data.yahoo_quote_summary_path.format(symbol=tick)}",
        params={
            "modules": ",".join(SETTINGS.market_data.yahoo_quote_modules),
        },
        timeout=SETTINGS.http.default_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    result = _get_nested(payload, "quoteSummary", "result")
    if not result:
        raise ValueError(f"Stock data unavailable for {tick}.")
    item = result[0]
    price = item.get("price") or {}
    summary_detail = item.get("summaryDetail") or {}
    default_stats = item.get("defaultKeyStatistics") or {}
    asset_profile = item.get("assetProfile") or {}
    financial_data = item.get("financialData") or {}

    regular_market_price = _coalesce(
        _get_nested(price, "regularMarketPrice", "raw"),
        _get_nested(price, "regularMarketPrice"),
        _get_nested(summary_detail, "previousClose", "raw"),
    )
    previous_close = _coalesce(
        _get_nested(summary_detail, "previousClose", "raw"),
        _get_nested(summary_detail, "previousClose"),
    )
    open_price = _coalesce(
        _get_nested(summary_detail, "open", "raw"),
        _get_nested(summary_detail, "open"),
    )
    day_range = _coalesce(
        _get_nested(summary_detail, "dayRange", "raw"),
        _get_nested(summary_detail, "dayRange"),
    )
    fifty_two_week_range = _coalesce(
        _get_nested(summary_detail, "fiftyTwoWeekRange", "raw"),
        _get_nested(summary_detail, "fiftyTwoWeekRange"),
    )
    market_cap = _coalesce(
        _get_nested(summary_detail, "marketCap", "raw"),
        _get_nested(summary_detail, "marketCap"),
        _get_nested(financial_data, "marketCap", "raw"),
    )
    trailing_pe = _coalesce(
        _get_nested(summary_detail, "trailingPE", "raw"),
        _get_nested(summary_detail, "trailingPE"),
        _get_nested(default_stats, "trailingPE", "raw"),
    )
    beta = _coalesce(
        _get_nested(default_stats, "beta", "raw"),
        _get_nested(default_stats, "beta"),
    )
    dividend_yield = _coalesce(
        _get_nested(summary_detail, "dividendYield", "raw"),
        _get_nested(summary_detail, "dividendYield"),
        _get_nested(financial_data, "dividendYield", "raw"),
    )
    regular_volume = _coalesce(
        _get_nested(summary_detail, "volume", "raw"),
        _get_nested(summary_detail, "volume"),
        _get_nested(price, "regularMarketVolume", "raw"),
        _get_nested(price, "regularMarketVolume"),
    )
    average_volume = _coalesce(
        _get_nested(summary_detail, "averageVolume", "raw"),
        _get_nested(summary_detail, "averageVolume"),
        _get_nested(default_stats, "averageVolume", "raw"),
    )

    quote = {
        "symbol": tick,
        "name": _coalesce(
            _get_nested(price, "shortName"),
            _get_nested(price, "longName"),
            _get_nested(asset_profile, "shortName"),
            tick,
        ),
        "exchange": _coalesce(
            _get_nested(price, "exchangeName"),
            _get_nested(price, "fullExchangeName"),
            _get_nested(summary_detail, "exchange", "raw"),
        ),
        "currency": _coalesce(
            _get_nested(price, "currency"),
            _get_nested(summary_detail, "currency"),
        ),
        "current_price": _as_float(regular_market_price),
        "previous_close": _as_float(previous_close),
        "open": _as_float(open_price),
        "day_range": day_range,
        "fifty_two_week_range": fifty_two_week_range,
        "market_cap": _as_float(market_cap),
        "trailing_pe": _as_float(trailing_pe),
        "beta": _as_float(beta),
        "dividend_yield": _as_float(dividend_yield),
        "volume": _as_float(regular_volume),
        "average_volume": _as_float(average_volume),
        "sector": _coalesce(_get_nested(asset_profile, "sector"), _get_nested(financial_data, "sector")),
        "industry": _coalesce(_get_nested(asset_profile, "industry"), _get_nested(financial_data, "industry")),
        "website": _coalesce(_get_nested(asset_profile, "website"), _get_nested(financial_data, "website")),
        "long_business_summary": _coalesce(_get_nested(asset_profile, "longBusinessSummary"), ""),
        "quote_time": _coalesce(_get_nested(price, "regularMarketTime", "raw"), _get_nested(price, "regularMarketTime")),
        "market_state": _coalesce(_get_nested(price, "marketState"), ""),
        "fifty_two_week_high": _as_float(_coalesce(_get_nested(summary_detail, "fiftyTwoWeekHigh", "raw"), _get_nested(summary_detail, "fiftyTwoWeekHigh"))),
        "fifty_two_week_low": _as_float(_coalesce(_get_nested(summary_detail, "fiftyTwoWeekLow", "raw"), _get_nested(summary_detail, "fiftyTwoWeekLow"))),
        "price_to_book": _as_float(_coalesce(_get_nested(default_stats, "priceToBook", "raw"), _get_nested(default_stats, "priceToBook"))),
    }
    quote["quote_source"] = "yahoo_fallback"
    return quote


def _fetch_chart_result(
    symbol: str,
    *,
    range_name: str,
    interval: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = requests.get(
        f"{YAHOO_FINANCE_BASE}{SETTINGS.market_data.yahoo_chart_path.format(symbol=symbol)}",
        params={
            "range": range_name,
            "interval": interval,
            "includeAdjustedClose": str(SETTINGS.market_data.yahoo_include_adjusted_close).lower(),
        },
        timeout=SETTINGS.http.default_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    result = _get_nested(payload, "chart", "result")
    if not result:
        return {}, {}
    chart = result[0]
    return chart.get("meta") or {}, chart


def _chart_points(chart: dict[str, Any]) -> list[dict[str, Any]]:
    if not chart:
        return []
    times = chart.get("timestamp") or []
    quote = (chart.get("indicators") or {}).get("quote") or [{}]
    points = quote[0]
    opens = points.get("open") or []
    highs = points.get("high") or []
    lows = points.get("low") or []
    closes = points.get("close") or []
    volumes = points.get("volume") or []

    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(times):
        close_value = closes[index] if index < len(closes) else None
        if close_value is None:
            continue
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": close_value,
                "volume": volumes[index] if index < len(volumes) else None,
            }
        )
    return rows


def _alpaca_start_time(range_name: str) -> str:
    now = datetime.now(timezone.utc)
    if range_name == SETTINGS.market_data.maximum_range_name:
        start = datetime.fromisoformat(SETTINGS.market_data.maximum_history_start).replace(
            tzinfo=timezone.utc
        )
    else:
        try:
            start = now - timedelta(days=SETTINGS.market_data.alpaca_range_days[range_name])
        except KeyError as exc:
            raise ValueError(f"Unsupported stock chart range: {range_name}.") from exc
    return start.isoformat().replace("+00:00", "Z")


def _alpaca_timeframe(interval: str) -> str:
    try:
        return SETTINGS.market_data.alpaca_timeframes[interval]
    except KeyError as exc:
        raise ValueError(f"Unsupported Alpaca chart interval: {interval}.") from exc


def _chart_points_from_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    for bar in bars:
        close = _as_float(bar.get("c"))
        timestamp = bar.get("t")
        if close is None or not isinstance(timestamp, str):
            continue
        point_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if point_time.tzinfo is None:
            point_time = point_time.replace(tzinfo=timezone.utc)
        points.append(
            {
                "timestamp": point_time.isoformat(),
                "open": _as_float(bar.get("o")),
                "high": _as_float(bar.get("h")),
                "low": _as_float(bar.get("l")),
                "close": close,
                "volume": _as_float(bar.get("v")),
            }
        )
    return points


def _epoch_time(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return int(timestamp.timestamp())


def _fetch_alpaca_stock_data(
    symbol: str,
    *,
    range_name: str,
    interval: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    headers = _alpaca_headers()
    if headers is None:
        raise ValueError("Alpaca API credentials are not configured.")

    tick = _normalize_symbol(symbol)
    snapshot_response = requests.get(
        f"{ALPACA_DATA_BASE}{SETTINGS.market_data.alpaca_snapshot_path.format(symbol=tick)}",
        headers=headers,
        params={"feed": SETTINGS.market_data.alpaca_feed},
        timeout=SETTINGS.http.default_timeout_seconds,
    )
    snapshot_response.raise_for_status()
    snapshot = snapshot_response.json()

    bars_response = requests.get(
        f"{ALPACA_DATA_BASE}{SETTINGS.market_data.alpaca_bars_path.format(symbol=tick)}",
        headers=headers,
        params={
            "timeframe": _alpaca_timeframe(interval),
            "start": _alpaca_start_time(range_name),
            "limit": SETTINGS.market_data.alpaca_bar_limit,
            "adjustment": SETTINGS.market_data.alpaca_adjustment,
            "feed": SETTINGS.market_data.alpaca_feed,
            "sort": SETTINGS.market_data.alpaca_sort_order,
        },
        timeout=SETTINGS.http.default_timeout_seconds,
    )
    bars_response.raise_for_status()
    chart = _chart_points_from_bars(bars_response.json().get("bars") or [])
    if not chart:
        raise ValueError(f"Alpaca returned no price bars for {tick}.")

    latest = chart[-1]
    daily = snapshot.get("dailyBar") or {}
    previous = snapshot.get("prevDailyBar") or {}
    trade = snapshot.get("latestTrade") or {}
    current_price = _as_float(trade.get("p"), _as_float(daily.get("c"), latest["close"]))
    previous_close = _as_float(previous.get("c"), chart[-2]["close"] if len(chart) > 1 else None)
    day_high = _as_float(daily.get("h"), latest.get("high"))
    day_low = _as_float(daily.get("l"), latest.get("low"))
    volumes = [point["volume"] for point in chart if point["volume"] is not None]
    quote = {
        "symbol": tick,
        "name": tick,
        "exchange": None,
        "currency": SETTINGS.market_data.default_currency,
        "current_price": current_price,
        "previous_close": previous_close,
        "open": _as_float(daily.get("o"), latest.get("open")),
        "day_range": f"{day_low:g} - {day_high:g}" if day_low is not None and day_high is not None else None,
        "fifty_two_week_range": None,
        "market_cap": None,
        "trailing_pe": None,
        "beta": None,
        "dividend_yield": None,
        "volume": _as_float(daily.get("v"), latest.get("volume")),
        "average_volume": sum(volumes) / len(volumes) if volumes else None,
        "sector": None,
        "industry": None,
        "website": None,
        "long_business_summary": "",
        "quote_time": _epoch_time(trade.get("t")) or _epoch_time(daily.get("t")),
        "market_state": SETTINGS.market_data.alpaca_feed.upper(),
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "price_to_book": None,
        "quote_source": "alpaca",
    }
    return quote, chart


def _quote_from_chart_metadata(
    symbol: str,
    metadata: dict[str, Any],
    chart: dict[str, Any],
) -> dict[str, Any]:
    points = _chart_points(chart)
    latest = points[-1] if points else {}
    day_high = _as_float(metadata.get("regularMarketDayHigh"))
    day_low = _as_float(metadata.get("regularMarketDayLow"))
    year_high = _as_float(metadata.get("fiftyTwoWeekHigh"))
    year_low = _as_float(metadata.get("fiftyTwoWeekLow"))
    return {
        "symbol": symbol,
        "name": _coalesce(metadata.get("longName"), metadata.get("shortName"), symbol),
        "exchange": _coalesce(metadata.get("fullExchangeName"), metadata.get("exchangeName")),
        "currency": metadata.get("currency") or SETTINGS.market_data.default_currency,
        "current_price": _as_float(metadata.get("regularMarketPrice"), latest.get("close")),
        "previous_close": _as_float(
            _coalesce(metadata.get("previousClose"), metadata.get("chartPreviousClose"))
        ),
        "open": _as_float(latest.get("open")),
        "day_range": (
            f"{day_low:g} - {day_high:g}"
            if day_low is not None and day_high is not None
            else None
        ),
        "fifty_two_week_range": (
            f"{year_low:g} - {year_high:g}"
            if year_low is not None and year_high is not None
            else None
        ),
        "market_cap": None,
        "trailing_pe": None,
        "beta": None,
        "dividend_yield": None,
        "volume": _as_float(metadata.get("regularMarketVolume"), latest.get("volume")),
        "average_volume": None,
        "sector": None,
        "industry": None,
        "website": None,
        "long_business_summary": "",
        "quote_time": metadata.get("regularMarketTime"),
        "market_state": metadata.get("marketState", ""),
        "fifty_two_week_high": year_high,
        "fifty_two_week_low": year_low,
        "price_to_book": None,
        "quote_source": "chart_fallback",
    }


def _fetch_yahoo_stock_data(
    symbol: str,
    *,
    range_name: str,
    interval: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata, chart = _fetch_chart_result(symbol, range_name=range_name, interval=interval)
    points = _chart_points(chart)
    try:
        quote = _fetch_yahoo_quote(symbol)
    except (requests.RequestException, ValueError):
        if not metadata and not points:
            raise
        quote = _quote_from_chart_metadata(symbol, metadata, chart)
    if quote.get("current_price") is None:
        if not points:
            raise ValueError(f"No price data is available for {symbol}.")
        quote["current_price"] = points[-1]["close"]
    return quote, points


def _fetch_stock_data(
    symbol: str,
    *,
    range_name: str,
    interval: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tick = _normalize_symbol(symbol)
    try:
        quote, chart = _fetch_alpaca_stock_data(
            tick,
            range_name=range_name,
            interval=interval,
        )
    except (requests.RequestException, ValueError) as alpaca_error:
        print(f"Alpaca unavailable ({alpaca_error}); trying Yahoo Finance fallback.", flush=True)
        try:
            return _fetch_yahoo_stock_data(tick, range_name=range_name, interval=interval)
        except (requests.RequestException, ValueError) as yahoo_error:
            raise StockDataUnavailable(
                f"Alpaca and Yahoo Finance could not provide stock data for {tick}. "
                f"Alpaca: {alpaca_error}. Yahoo Finance: {yahoo_error}."
            ) from yahoo_error

    try:
        yahoo_quote = _fetch_yahoo_quote(tick)
    except (requests.RequestException, ValueError) as error:
        quote["fundamentals_source"] = "unavailable"
        print(
            f"Yahoo Finance fundamentals unavailable ({error}); retaining Alpaca market data.",
            flush=True,
        )
    else:
        for field in (
            "name",
            "exchange",
            "currency",
            "fifty_two_week_range",
            "market_cap",
            "trailing_pe",
            "beta",
            "dividend_yield",
            "average_volume",
            "sector",
            "industry",
            "website",
            "long_business_summary",
            "fifty_two_week_high",
            "fifty_two_week_low",
            "price_to_book",
        ):
            missing_primary_value = quote.get(field) in (None, "")
            if field == "name" and quote.get(field) == tick:
                missing_primary_value = True
            prefer_fundamental_value = field == "average_volume"
            if (
                (missing_primary_value or prefer_fundamental_value)
                and yahoo_quote.get(field) not in (None, "")
            ):
                quote[field] = yahoo_quote[field]
        quote["fundamentals_source"] = "yahoo"
    return quote, chart


def fetch_stock_quote(
    symbol: str,
    *,
    range_name: str = SETTINGS.market_data.default_range,
    interval: str = SETTINGS.market_data.default_interval,
) -> dict[str, Any]:
    """Return current market and company metadata, preferring Alpaca."""
    quote, _ = _fetch_stock_data(symbol, range_name=range_name, interval=interval)
    return quote


def fetch_stock_chart(
    symbol: str,
    *,
    range_name: str = SETTINGS.market_data.default_range,
    interval: str = SETTINGS.market_data.default_interval,
) -> list[dict[str, Any]]:
    """Return a recent OHLCV chart series, preferring Alpaca."""
    tick = _normalize_symbol(symbol)
    try:
        _, chart = _fetch_alpaca_stock_data(tick, range_name=range_name, interval=interval)
        return chart
    except (requests.RequestException, ValueError) as alpaca_error:
        print(f"Alpaca unavailable ({alpaca_error}); trying Yahoo Finance fallback.", flush=True)
        try:
            _, response_chart = _fetch_chart_result(
                tick,
                range_name=range_name,
                interval=interval,
            )
        except (requests.RequestException, ValueError) as yahoo_error:
            raise StockDataUnavailable(
                f"Alpaca and Yahoo Finance could not provide chart data for {tick}. "
                f"Alpaca: {alpaca_error}. Yahoo Finance: {yahoo_error}."
            ) from yahoo_error
        points = _chart_points(response_chart)
        if not points:
            raise StockDataUnavailable(
                f"Alpaca and Yahoo Finance could not provide chart data for {tick}. "
                f"Alpaca: {alpaca_error}. Yahoo Finance returned no price bars."
            )
        return points


def fetch_stock_snapshot(
    symbol: str,
    *,
    range_name: str = SETTINGS.market_data.default_range,
    interval: str = SETTINGS.market_data.default_interval,
) -> dict[str, Any]:
    """Fetch live quote details and a chart series for the stock page."""
    quote, chart = _fetch_stock_data(
        symbol,
        range_name=range_name,
        interval=interval,
    )
    return {
        "quote": quote,
        "chart": chart,
    }


def indexed_stock_companies(vector_root: Path | str = DEFAULT_VECTOR_ROOT) -> list[dict[str, Any]]:
    """List stock snapshots currently indexed in the existing Chroma collection."""
    path = Path(vector_root)
    if not path.is_dir():
        return []

    import chromadb

    client = chromadb.PersistentClient(path=str(path))
    try:
        collection = client.get_collection(SETTINGS.paths.vector_collection)
    except chromadb.errors.NotFoundError:
        return []

    metadata_rows = collection.get(
        where={"source": "stock_market"},
        include=["metadatas"],
    ).get("metadatas") or []
    companies: dict[str, dict[str, Any]] = {}
    for metadata in metadata_rows:
        if not metadata or not metadata.get("ticker"):
            continue
        ticker = str(metadata["ticker"]).upper()
        companies[ticker] = {
            "ticker": ticker,
            "name": metadata.get("name") or ticker,
            "exchange": metadata.get("exchange"),
            "updated_at": metadata.get("updated_at"),
        }
    return [companies[ticker] for ticker in sorted(companies)]


def build_stock_document(
    symbol: str,
    *,
    range_name: str = SETTINGS.market_data.default_range,
    interval: str = SETTINGS.market_data.default_interval,
) -> tuple[str, dict[str, Any]]:
    """Build a natural-language summary for vector embedding."""
    tick = _normalize_symbol(symbol)
    quote, chart = _fetch_stock_data(tick, range_name=range_name, interval=interval)
    latest = chart[-1] if chart else {}
    previous = chart[-2] if len(chart) > 1 else {}
    price_change = None
    if latest and previous:
        price_change = (latest.get("close") or 0) - (previous.get("close") or 0)

    price_value = quote.get("current_price")
    range_text = quote.get("day_range") or "N/A"
    currency = quote.get("currency") or SETTINGS.market_data.default_currency
    market_cap = quote.get("market_cap")
    if market_cap is not None:
        market_cap_text = f"{market_cap:,.0f}"
    else:
        market_cap_text = "N/A"

    lines = [
        f"Ticker: {quote['symbol']}",
        f"Company: {quote.get('name')}",
        f"Exchange: {quote.get('exchange') or 'N/A'}",
        f"Currency: {currency}",
        f"Current price: {currency} {price_value if price_value is not None else 'N/A'}",
        f"Previous close: {currency} {quote.get('previous_close') if quote.get('previous_close') is not None else 'N/A'}",
        f"Open: {currency} {quote.get('open') if quote.get('open') is not None else 'N/A'}",
        f"Day range: {range_text}",
        f"52-week range: {quote.get('fifty_two_week_range') or 'N/A'}",
        f"Market cap: {market_cap_text}",
        f"Volume: {quote.get('volume') if quote.get('volume') is not None else 'N/A'}",
        f"Average volume: {quote.get('average_volume') if quote.get('average_volume') is not None else 'N/A'}",
        f"P/E ratio: {quote.get('trailing_pe') if quote.get('trailing_pe') is not None else 'N/A'}",
        f"Beta: {quote.get('beta') if quote.get('beta') is not None else 'N/A'}",
        f"Dividend yield: {quote.get('dividend_yield') if quote.get('dividend_yield') is not None else 'N/A'}",
        f"Sector: {quote.get('sector') or 'N/A'}",
        f"Industry: {quote.get('industry') or 'N/A'}",
        f"Website: {quote.get('website') or 'N/A'}",
        f"Market state: {quote.get('market_state') or 'N/A'}",
        f"Price-to-book: {quote.get('price_to_book') if quote.get('price_to_book') is not None else 'N/A'}",
    ]
    if quote.get("long_business_summary"):
        lines.append(f"Business summary: {quote['long_business_summary']}")
    if quote.get("quote_source") == "alpaca":
        lines.append("Stock price and OHLCV data source: Alpaca IEX market-data feed.")
        if quote.get("fundamentals_source") == "yahoo":
            lines.append("Company fundamentals are supplemented with Yahoo Finance data.")
        else:
            lines.append("Yahoo Finance fundamentals were unavailable; some company metrics may be missing.")
    elif quote.get("quote_source") == "yahoo_fallback":
        lines.append("Alpaca was unavailable; Yahoo Finance is the backup stock-data provider.")
    if quote.get("quote_source") == "chart_fallback":
        lines.append("Quote details are limited because Yahoo Finance rate-limited its quote endpoint.")
    if chart:
        history = "; ".join(
            f"{point['timestamp'][:10]} close={point.get('close')}" for point in chart[-5:]
        )
        lines.append(f"Recent chart history: {history}")
        if price_change is not None:
            lines.append(f"Most recent daily change: {currency} {price_change:.2f}")

    metadata = {
        "ticker": tick,
        "source": "stock_market",
        "symbol": tick,
        "name": quote.get("name"),
        "exchange": quote.get("exchange"),
        "market_state": quote.get("market_state"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return "\n".join(lines), metadata


def index_stock_documents(
    symbols: Sequence[str],
    *,
    vector_root: Path | str = DEFAULT_VECTOR_ROOT,
    range_name: str = SETTINGS.market_data.default_range,
    interval: str = SETTINGS.market_data.default_interval,
) -> list[str]:
    """Embed current stock snapshots into the persistent Chroma collection."""
    vector_path = Path(vector_root)
    store = open_vector_store(vector_path, create=True)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for symbol in symbols:
        normalized_symbol = _normalize_symbol(symbol)
        print(f"Fetching stock snapshot for {normalized_symbol}...", flush=True)
        content, metadata = build_stock_document(normalized_symbol, range_name=range_name, interval=interval)
        symbol_id = f"stock:{normalized_symbol}"
        ids.append(symbol_id)
        documents.append(content)
        metadatas.append({key: value for key, value in metadata.items() if value is not None})

    if documents:
        print(f"Embedding {len(documents)} stock snapshot(s)...", flush=True)
        store.add_texts(texts=documents, metadatas=metadatas, ids=ids)
        provider, model_name, _ = embedding_settings()
        record_embedding_usage(documents, f"{provider}:{model_name}", operation="stock_market_embedding")
        print(f"Indexed {len(documents)} stock snapshot(s): {', '.join(ids)}", flush=True)
    return ids


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="Stock tickers to fetch and index.")
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_ROOT, help="Vector store directory.")
    parser.add_argument(
        "--range",
        default=SETTINGS.market_data.default_range,
        choices=SETTINGS.market_data.supported_ranges,
        help="Chart range.",
    )
    parser.add_argument(
        "--interval",
        default=SETTINGS.market_data.default_interval,
        choices=list(SETTINGS.market_data.alpaca_timeframes),
        help="Chart interval.",
    )
    args = parser.parse_args()
    ids = index_stock_documents(args.tickers, vector_root=args.vector_dir, range_name=args.range, interval=args.interval)
    print(f"Indexed {len(ids)} stock snapshots: {', '.join(ids)}")


if __name__ == "__main__":
    main()
