from __future__ import annotations

import sys
from pathlib import Path

import requests
import pytest

import corporate_atlas.core.stock_market as stock_market
from corporate_atlas.core.stock_market import (
    build_stock_document,
    fetch_stock_chart,
    fetch_stock_quote,
    fetch_stock_snapshot,
    index_stock_documents,
)
from corporate_atlas.services import stock


@pytest.fixture(autouse=True)
def alpaca_credentials_missing(monkeypatch):
    monkeypatch.setattr(stock_market, "_alpaca_headers", lambda: None)


def test_fetch_stock_quote_extracts_core_market_fields(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "quoteSummary": {
                    "result": [{
                        "price": {
                            "shortName": "Apple Inc.",
                            "longName": "Apple Inc.",
                            "exchangeName": "NASDAQ",
                            "currency": "USD",
                            "regularMarketPrice": {"raw": 201.42},
                            "regularMarketTime": {"raw": 1730000000},
                        },
                        "summaryDetail": {
                            "previousClose": {"raw": 198.5},
                            "open": {"raw": 199.2},
                            "dayRange": {"raw": "197.50 - 202.10"},
                            "fiftyTwoWeekRange": {"raw": "164.08 - 237.23"},
                            "marketCap": {"raw": 3000000000000},
                            "trailingPE": {"raw": 32.56},
                            "volume": {"raw": 60000000},
                            "averageVolume": {"raw": 70000000},
                            "dividendYield": {"raw": 0.005},
                            "exchange": {"raw": "NMS"},
                        },
                        "defaultKeyStatistics": {
                            "beta": {"raw": 1.23},
                            "priceToBook": {"raw": 42.1},
                        },
                        "assetProfile": {
                            "sector": "Technology",
                            "industry": "Consumer Electronics",
                            "website": "https://apple.com",
                            "longBusinessSummary": "Apple designs and sells consumer electronics.",
                        },
                    }]
                }
            }

    monkeypatch.setattr("corporate_atlas.core.stock_market.requests.get", lambda *a, **k: FakeResponse())
    quote = fetch_stock_quote("AAPL")

    assert quote["symbol"] == "AAPL"
    assert quote["current_price"] == 201.42
    assert quote["market_cap"] == 3000000000000
    assert quote["sector"] == "Technology"
    assert quote["industry"] == "Consumer Electronics"
    assert quote["website"] == "https://apple.com"


def test_fetch_stock_chart_parses_close_series(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "chart": {
                    "result": [{
                        "timestamp": [1700000000, 1700003600],
                        "indicators": {
                            "quote": [{
                                "open": [195.0, 196.5],
                                "high": [196.0, 197.2],
                                "low": [194.8, 195.9],
                                "close": [195.8, 196.9],
                                "volume": [5000, 4800],
                            }]
                        },
                    }]
                }
            }

    monkeypatch.setattr("corporate_atlas.core.stock_market.requests.get", lambda *a, **k: FakeResponse())
    points = fetch_stock_chart("AAPL", range_name="1mo", interval="1d")

    assert len(points) == 2
    assert points[0]["close"] == 195.8
    assert points[1]["volume"] == 4800


def test_alpaca_is_primary_for_snapshot_and_historical_bars(monkeypatch) -> None:
    monkeypatch.setattr(
        stock_market,
        "_alpaca_headers",
        lambda: {"APCA-API-KEY-ID": "test-key", "APCA-API-SECRET-KEY": "test-secret"},
    )
    requests_seen = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, *, headers, params, timeout):
        requests_seen.append((url, headers, params))
        if url.endswith("/snapshot"):
            return FakeResponse({
                "latestTrade": {"t": "2026-11-16T19:50:00Z", "p": 254.25},
                "dailyBar": {"t": "2026-11-16T00:00:00Z", "o": 252.0, "h": 256.0, "l": 251.0, "c": 254.0, "v": 1000},
                "prevDailyBar": {"c": 250.0},
            })
        return FakeResponse({"bars": [
            {"t": "2026-11-13T00:00:00Z", "o": 248.0, "h": 251.0, "l": 247.0, "c": 250.0, "v": 900},
            {"t": "2026-11-16T00:00:00Z", "o": 252.0, "h": 256.0, "l": 251.0, "c": 254.0, "v": 1000},
        ]})

    monkeypatch.setattr(stock_market.requests, "get", fake_get)
    monkeypatch.setattr(
        stock_market,
        "_fetch_yahoo_quote",
        lambda symbol: {
            "symbol": symbol,
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "market_cap": 3_000_000_000_000,
            "fifty_two_week_high": 275.0,
            "fifty_two_week_low": 160.0,
            "quote_source": "yahoo_fallback",
        },
    )
    snapshot = fetch_stock_snapshot("AAPL")

    assert snapshot["quote"]["quote_source"] == "alpaca"
    assert snapshot["quote"]["fundamentals_source"] == "yahoo"
    assert snapshot["quote"]["name"] == "Apple Inc."
    assert snapshot["quote"]["market_cap"] == 3_000_000_000_000
    assert snapshot["quote"]["fifty_two_week_high"] == 275.0
    assert snapshot["quote"]["fifty_two_week_low"] == 160.0
    assert snapshot["quote"]["current_price"] == 254.25
    assert snapshot["quote"]["previous_close"] == 250.0
    assert snapshot["chart"][1]["open"] == 252.0
    assert snapshot["chart"][1]["high"] == 256.0
    assert len(requests_seen) == 2
    assert all(request[1]["APCA-API-KEY-ID"] == "test-key" for request in requests_seen)
    assert requests_seen[0][2]["feed"] == "iex"


def test_alpaca_snapshot_survives_yahoo_fundamentals_failure(monkeypatch) -> None:
    quote = {
        "symbol": "AAPL",
        "name": "AAPL",
        "current_price": 254.25,
        "quote_source": "alpaca",
    }
    chart = [{"timestamp": "2026-11-16T00:00:00+00:00", "close": 254.0}]
    monkeypatch.setattr(
        stock_market,
        "_fetch_alpaca_stock_data",
        lambda *args, **kwargs: (quote.copy(), chart),
    )
    monkeypatch.setattr(
        stock_market,
        "_fetch_yahoo_quote",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.HTTPError("rate limited")),
    )

    snapshot = fetch_stock_snapshot("AAPL")

    assert snapshot["quote"]["quote_source"] == "alpaca"
    assert snapshot["quote"]["fundamentals_source"] == "unavailable"
    assert snapshot["quote"]["current_price"] == 254.25
    assert snapshot["chart"] == chart


def test_yahoo_is_used_when_alpaca_fails(monkeypatch) -> None:
    yahoo_quote = {"symbol": "AAPL", "name": "Apple Inc.", "quote_source": "yahoo_fallback"}
    yahoo_chart = [{"timestamp": "2026-11-16T00:00:00+00:00", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}]
    monkeypatch.setattr(
        stock_market,
        "_fetch_alpaca_stock_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.HTTPError("Alpaca unavailable")),
    )
    monkeypatch.setattr(stock_market, "_fetch_yahoo_stock_data", lambda *args, **kwargs: (yahoo_quote, yahoo_chart))

    snapshot = fetch_stock_snapshot("AAPL")

    assert snapshot == {"quote": yahoo_quote, "chart": yahoo_chart}


def test_quote_summary_rate_limit_falls_back_to_chart_data(monkeypatch) -> None:
    class ChartResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "chart": {
                    "result": [{
                        "meta": {
                            "symbol": "AAPL",
                            "longName": "Apple Inc.",
                            "exchangeName": "NASDAQ",
                            "currency": "USD",
                            "regularMarketPrice": 220.5,
                            "previousClose": 218.0,
                            "regularMarketDayHigh": 221.0,
                            "regularMarketDayLow": 216.0,
                            "fiftyTwoWeekHigh": 240.0,
                            "fiftyTwoWeekLow": 160.0,
                            "regularMarketVolume": 42000000,
                        },
                        "timestamp": [1700000000],
                        "indicators": {
                            "quote": [{
                                "open": [218.5],
                                "high": [221.0],
                                "low": [216.0],
                                "close": [220.5],
                                "volume": [42000000],
                            }]
                        },
                    }]
                }
            }

    class RateLimitedResponse:
        status_code = 429

        def raise_for_status(self):
            raise requests.HTTPError("429 Client Error", response=self)

    def fake_get(url, **kwargs):
        if "/chart/" in url:
            return ChartResponse()
        return RateLimitedResponse()

    monkeypatch.setattr("corporate_atlas.core.stock_market.requests.get", fake_get)

    content, metadata = build_stock_document("AAPL")

    assert metadata["name"] == "Apple Inc."
    assert metadata["exchange"] == "NASDAQ"
    assert "Current price: USD 220.5" in content
    assert "Market cap: N/A" in content
    assert "rate-limited its quote endpoint" in content


def test_stock_job_reports_rate_limit_without_traceback(monkeypatch) -> None:
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("429 Client Error", response=response)

    def rate_limited(*args, **kwargs):
        raise error

    monkeypatch.setattr(stock, "prepare_stock_market", rate_limited)
    monkeypatch.setattr(sys, "argv", ["stock", "--tickers", "AAPL"])

    with pytest.raises(SystemExit, match="rate limiting market-data requests"):
        stock.main()


def test_build_stock_document_and_indexing_create_text_and_metadata(monkeypatch, tmp_path: Path, capsys) -> None:
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_get(url, params=None, timeout=20, **kwargs):
        if "quoteSummary" in url:
            return FakeResponse({
                "quoteSummary": {"result": [{
                    "price": {
                        "shortName": "Apple Inc.",
                        "exchangeName": "NASDAQ",
                        "currency": "USD",
                        "regularMarketPrice": {"raw": 210.0},
                    },
                    "summaryDetail": {
                        "previousClose": {"raw": 205.0},
                        "open": {"raw": 206.0},
                        "dayRange": {"raw": "205.00 - 212.00"},
                        "fiftyTwoWeekRange": {"raw": "180.00 - 230.00"},
                        "marketCap": {"raw": 3100000000000},
                        "trailingPE": {"raw": 30.0},
                        "volume": {"raw": 60000000},
                        "averageVolume": {"raw": 70000000},
                        "dividendYield": {"raw": 0.006},
                    },
                    "defaultKeyStatistics": {"beta": {"raw": 1.1}},
                    "assetProfile": {
                        "sector": "Technology",
                        "industry": "Consumer Electronics",
                        "website": "https://apple.com",
                        "longBusinessSummary": "Apple makes devices and services.",
                    },
                }]}
            })
        return FakeResponse({
            "chart": {"result": [{
                "timestamp": [1700000000],
                "indicators": {"quote": [{"open": [205.0], "high": [211.0], "low": [204.0], "close": [210.0], "volume": [60000000]}]},
            }]}
        })

    class FakeStore:
        def __init__(self):
            self.calls = []

        def add_texts(self, texts, metadatas=None, ids=None):
            self.calls.append({"texts": texts, "metadatas": metadatas, "ids": ids})
            return ids

    fake_store = FakeStore()
    monkeypatch.setattr("corporate_atlas.core.stock_market.requests.get", fake_get)
    monkeypatch.setattr("corporate_atlas.core.stock_market.open_vector_store", lambda *a, **k: fake_store)
    monkeypatch.setattr("corporate_atlas.core.stock_market.record_embedding_usage", lambda *a, **k: None)
    monkeypatch.setattr("corporate_atlas.core.stock_market.embedding_settings", lambda: ("test", "embed", "secret"))

    ids = index_stock_documents(["AAPL"], vector_root=tmp_path / "vectors")

    assert ids == ["stock:AAPL"]
    assert len(fake_store.calls) == 1
    assert "Ticker: AAPL" in fake_store.calls[0]["texts"][0]
    assert fake_store.calls[0]["metadatas"][0]["source"] == "stock_market"
    output = capsys.readouterr().out
    assert "Fetching stock snapshot for AAPL" in output
    assert "Embedding 1 stock snapshot(s)" in output
    assert "Indexed 1 stock snapshot(s)" in output

    document_text, metadata = build_stock_document("AAPL")
    assert "Company:" in document_text
    assert metadata["ticker"] == "AAPL"
