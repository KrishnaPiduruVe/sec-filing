"""Validated application settings loaded from the packaged TOML file."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsSettings(_ConfigModel):
    data_dir: str
    filings_dir: str
    vector_dir: str
    graph_dir: str
    usage_database: str
    vector_collection: str
    frontend_static_dir: str


class ApiSettings(_ConfigModel):
    host: str
    client_host: str
    port: int = Field(ge=1, le=65535)
    trusted_hosts: list[str]
    allowed_origin_hosts: list[str]
    allowed_origin_ports: list[int] = Field(min_length=1)


class FrontendSettings(_ConfigModel):
    dev_host: str
    dev_port: int = Field(ge=1, le=65535)
    job_poll_interval_ms: int = Field(gt=0)
    stock_chart_ranges: list[str] = Field(min_length=1)
    api_proxy_prefixes: list[str] = Field(min_length=1)
    build_static_relative_path: str


class HttpSettings(_ConfigModel):
    default_timeout_seconds: float = Field(gt=0)
    sec_timeout_seconds: float = Field(gt=0)
    api_client_connect_timeout_seconds: float = Field(gt=0)
    api_client_read_timeout_seconds: float = Field(gt=0)
    sec_min_interval_seconds: float = Field(ge=0)
    sec_download_chunk_bytes: int = Field(gt=0)


class SecSettings(_ConfigModel):
    www_base_url: str
    data_base_url: str
    company_tickers_path: str
    submissions_path: str
    archive_path: str
    filing_index_filename: str
    user_agent_env_var: str
    default_tickers: list[str] = Field(min_length=1)


class MarketDataSettings(_ConfigModel):
    default_range: str
    default_interval: str
    maximum_range_name: str
    default_currency: str
    yahoo_include_adjusted_close: bool
    supported_ranges: list[str] = Field(min_length=1)
    alpaca_range_days: dict[str, int]
    maximum_history_start: str
    alpaca_timeframes: dict[str, str]
    yahoo_base_url: str
    yahoo_quote_summary_path: str
    yahoo_chart_path: str
    yahoo_quote_modules: list[str] = Field(min_length=1)
    alpaca_base_url: str
    alpaca_snapshot_path: str
    alpaca_bars_path: str
    alpaca_feed: str
    alpaca_adjustment: str
    alpaca_sort_order: str
    alpaca_bar_limit: int = Field(gt=0)


class IndexingSettings(_ConfigModel):
    chunk_size: int = Field(gt=0)
    overlap: int = Field(ge=0)
    batch_size: int = Field(gt=0)
    batch_delay_seconds: float = Field(ge=0)
    max_retries: int = Field(ge=0)
    quota_backoff_seconds: float = Field(gt=0)
    quota_backoff_multiplier: float = Field(ge=1)
    max_batch_size: int = Field(gt=0)
    max_batch_delay_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "IndexingSettings":
        if self.overlap >= self.chunk_size:
            raise ValueError("indexing.overlap must be smaller than indexing.chunk_size.")
        return self


class GraphSettings(_ConfigModel):
    chunk_size: int = Field(gt=0)
    overlap: int = Field(ge=0)
    max_evidence_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "GraphSettings":
        if self.overlap >= self.chunk_size:
            raise ValueError("graph.overlap must be smaller than graph.chunk_size.")
        return self


class QuerySettings(_ConfigModel):
    default_mode: Literal["hybrid", "graph", "vector", "usage"]
    default_top_k: int = Field(gt=0)
    max_top_k: int = Field(gt=0)
    max_question_chars: int = Field(gt=0)
    max_history_messages: int = Field(gt=0)
    max_history_message_chars: int = Field(gt=0)
    max_sql_chars: int = Field(gt=0)
    max_sql_result_rows: int = Field(gt=0)


class LimitsSettings(_ConfigModel):
    ticker_input_chars: int = Field(gt=0)
    ticker_symbol_chars: int = Field(gt=0)
    tickers_per_job: int = Field(gt=0)
    filing_delete_selections: int = Field(gt=0)
    job_history_entries: int = Field(gt=0)
    job_output_chars: int = Field(gt=0)


class JobsSettings(_ConfigModel):
    prepare_stop_wait_seconds: float = Field(gt=0)
    default_stop_wait_seconds: float = Field(gt=0)
    shutdown_timeout_seconds: float = Field(gt=0)
    shutdown_poll_interval_seconds: float = Field(gt=0)


class LauncherSettings(_ConfigModel):
    startup_timeout_seconds: float = Field(gt=0)
    frontend_timeout_seconds: float = Field(gt=0)
    readiness_request_timeout_seconds: float = Field(gt=0)
    existing_service_timeout_seconds: float = Field(gt=0)
    poll_interval_seconds: float = Field(gt=0)
    graceful_shutdown_timeout_seconds: float = Field(gt=0)
    forced_shutdown_timeout_seconds: float = Field(gt=0)
    monitor_interval_seconds: float = Field(gt=0)


class TokenUsageSettings(_ConfigModel):
    default_tokenizer_model: str


class AppSettings(_ConfigModel):
    paths: PathsSettings
    api: ApiSettings
    frontend: FrontendSettings
    http: HttpSettings
    sec: SecSettings
    market_data: MarketDataSettings
    indexing: IndexingSettings
    graph: GraphSettings
    query: QuerySettings
    limits: LimitsSettings
    jobs: JobsSettings
    launcher: LauncherSettings
    token_usage: TokenUsageSettings

    @model_validator(mode="after")
    def validate_settings_relationships(self) -> "AppSettings":
        if self.query.default_top_k > self.query.max_top_k:
            raise ValueError("query.default_top_k cannot exceed query.max_top_k.")
        if self.market_data.default_range not in self.market_data.supported_ranges:
            raise ValueError("market_data.default_range must be a supported range.")
        if self.market_data.default_interval not in self.market_data.alpaca_timeframes:
            raise ValueError("market_data.default_interval must have an Alpaca timeframe.")
        if not set(self.frontend.stock_chart_ranges).issubset(
            self.market_data.supported_ranges
        ):
            raise ValueError(
                "frontend.stock_chart_ranges must be supported market-data ranges."
            )
        return self


def load_settings(config_path: Path | None = None) -> AppSettings:
    """Load and validate TOML settings; credentials remain in environment/.env."""
    path = config_path or Path(
        os.environ.get(
            "ATLAS_CONFIG_FILE",
            str(Path(__file__).with_name("config.toml")),
        )
    )
    path = path.expanduser()
    if not path.is_absolute():
        path = path.resolve()
    with path.open("rb") as config_file:
        values: dict[str, Any] = tomllib.load(config_file)
    return AppSettings.model_validate(values)


SETTINGS = load_settings()
