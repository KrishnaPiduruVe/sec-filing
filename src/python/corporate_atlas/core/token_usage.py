"""Persist token-usage metrics for model and embedding operations."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from corporate_atlas.paths import DATA_ROOT
from typing import Any

from dotenv import load_dotenv
from corporate_atlas.paths import ENV_FILE
from corporate_atlas.settings import SETTINGS

DEFAULT_DB_PATH = DATA_ROOT / SETTINGS.paths.usage_database


def _db_path(db_path: Path | None = None) -> Path:
    load_dotenv(ENV_FILE, override=False)
    path = db_path or Path(os.getenv("TOKEN_USAGE_DB", str(DEFAULT_DB_PATH)))
    return path if path.is_absolute() else DATA_ROOT / path


def usage_db_path(db_path: Path | None = None) -> Path:
    """Return the configured SQLite token-usage database path."""
    return _db_path(db_path)


def count_tokens(text: str, model: str | None = None) -> int:
    """Count tokens locally; fall back to a documented approximation if needed."""
    try:
        import tiktoken
    except ImportError:
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))

    try:
        encoding = tiktoken.encoding_for_model(
            model or SETTINGS.token_usage.default_tokenizer_model
        )
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def _message_text(messages: Any) -> str:
    if hasattr(messages, "content"):
        messages = messages.content
    if isinstance(messages, str):
        return messages
    if not isinstance(messages, Sequence):
        return str(messages)

    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, Sequence):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(str(item))
        else:
            parts.append(str(content))
    return "\n".join(parts)


def _usage_counts(response: Any) -> tuple[int, int] | None:
    usage: Any = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        metadata = getattr(response, "response_metadata", {})
        if isinstance(metadata, dict):
            usage = metadata.get("token_usage") or metadata.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return input_tokens, output_tokens
    return None


def record_usage(
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
    *,
    estimated: bool,
    db_path: Path | None = None,
) -> None:
    """Append one usage event to the configured SQLite database."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative.")
    path = usage_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                operation TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                estimated INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO token_usage
                (recorded_at, operation, model, input_tokens, output_tokens, estimated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                operation,
                model,
                input_tokens,
                output_tokens,
                int(estimated),
            ),
        )


def record_chat_usage(
    operation: str,
    model: str,
    messages: Any,
    response: Any,
) -> None:
    """Record API-reported usage, or a marked local estimate if unavailable."""
    counts = _usage_counts(response)
    if counts is None:
        input_tokens = count_tokens(_message_text(messages), model)
        output_tokens = count_tokens(_message_text(response), model)
        estimated = True
    else:
        input_tokens, output_tokens = counts
        estimated = False
    record_usage(
        operation,
        model,
        input_tokens,
        output_tokens,
        estimated=estimated,
    )


def record_embedding_usage(
    texts: Sequence[str],
    model: str,
    *,
    operation: str = "embedding",
) -> None:
    """Record estimated input tokens for one successful embedding batch."""
    record_usage(
        operation,
        model,
        sum(count_tokens(text, model) for text in texts),
        estimated=True,
    )


def usage_summary(db_path: Path | None = None) -> list[tuple[str, int, int, int, int]]:
    """Return totals by operation: input, output, events, and estimated events."""
    path = usage_db_path(db_path)
    if not path.is_file():
        return []
    with sqlite3.connect(path) as connection:
        return connection.execute(
            """
            SELECT operation, SUM(input_tokens), SUM(output_tokens), COUNT(*),
                   SUM(estimated)
            FROM token_usage
            GROUP BY operation
            ORDER BY operation
            """
        ).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Usage database (default: TOKEN_USAGE_DB)")
    args = parser.parse_args()
    rows = usage_summary(args.db)
    if not rows:
        print("No token usage has been recorded.")
        return
    print("Operation       Input tokens  Output tokens  Events  Estimated")
    for operation, input_tokens, output_tokens, events, estimated in rows:
        print(
            f"{operation:<15} {input_tokens:>12} {output_tokens:>14} "
            f"{events:>7} {estimated:>11}"
        )


if __name__ == "__main__":
    main()
