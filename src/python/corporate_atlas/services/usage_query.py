"""Answer token-usage questions with read-only SQL over the local usage database."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from corporate_atlas.core.llm_config import (
    ModelResponseTextError,
    extract_response_text,
    get_chat_model,
    get_model_identifier,
)
from corporate_atlas.core.response_format import CHART_INSTRUCTIONS
from corporate_atlas.core.token_usage import record_chat_usage, usage_db_path
from corporate_atlas.settings import SETTINGS

USAGE_COLUMNS = {
    "recorded_at",
    "operation",
    "model",
    "input_tokens",
    "output_tokens",
    "estimated",
    "cost_usd",
    "job_id",
}
USAGE_FUNCTIONS = {
    "avg",
    "coalesce",
    "count",
    "date",
    "datetime",
    "ifnull",
    "julianday",
    "max",
    "min",
    "round",
    "strftime",
    "sum",
    "total",
}


def _sql_from_response(response: Any) -> str:
    query = extract_response_text(response)
    fenced = re.fullmatch(r"```(?:sql)?\s*(.*?)\s*```", query, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        query = fenced.group(1).strip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    if (
        len(query) > SETTINGS.query.max_sql_chars
        or not re.match(r"(?is)^select\b", query)
        or ";" in query
        or "--" in query
        or "/*" in query
        or "*/" in query
        or not re.search(r"(?is)\bfrom\s+token_usage\b", query)
    ):
        raise ValueError("The model returned a query outside the token-usage SQL scope.")
    return query


def _usage_sql_authorizer(
    action: int,
    first_arg: str | None,
    second_arg: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if first_arg == "token_usage" and second_arg in USAGE_COLUMNS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (second_arg or first_arg or "").casefold()
        return sqlite3.SQLITE_OK if function_name in USAGE_FUNCTIONS else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY


def _execute_usage_query(query: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = usage_db_path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Token usage database not found: {path}")

    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.set_authorizer(_usage_sql_authorizer)
        cursor = connection.execute(
            f"SELECT * FROM ({query}) AS usage_result "
            f"LIMIT {SETTINGS.query.max_sql_result_rows}"
        )
        columns = [description[0] for description in cursor.description or ()]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to query the token-usage database: {exc}") from exc
    finally:
        connection.close()


def _invoke_usage_model(model, model_name, operation, messages, missing_text_message):
    for attempt in range(2):
        response = model.invoke(messages)
        record_chat_usage(operation, model_name, messages, response)
        try:
            return extract_response_text(response)
        except ModelResponseTextError as exc:
            if attempt == 1:
                raise ValueError(missing_text_message) from exc


def answer_usage_question(
    question: str,
    *,
    db_path: Path | None = None,
    llm: Any = None,
    history: Sequence[dict[str, str]] = (),
) -> str:
    """Translate a token-usage question to constrained SQL and summarize its result."""
    prompt_text = question.strip()
    if not prompt_text or len(prompt_text) > SETTINGS.query.max_question_chars:
        raise ValueError(
            f"Enter a token-usage question of 1–{SETTINGS.query.max_question_chars} characters."
        )
    model = llm if llm is not None else get_chat_model()
    model_name = "test-model" if llm is not None else get_model_identifier()
    previous_questions = [
        message["content"]
        for message in history
        if message.get("role") == "user" and message.get("content", "").strip()
    ][-SETTINGS.query.max_history_messages:]
    conversation_context = "\n".join(
        f"- {previous_question}" for previous_question in previous_questions
    ) or "(No prior user requests.)"

    sql_messages = [
        SystemMessage(
            content=(
                "Convert the current user question into exactly one SQLite SELECT statement. "
                "Use prior user requests only to resolve references in the current request; "
                "ignore prior assistant answers. "
                "The only table is token_usage(recorded_at, operation, model, input_tokens, "
                "output_tokens, estimated, cost_usd, job_id). recorded_at is an ISO-8601 UTC timestamp. "
                "cost_usd is the estimated USD cost saved at recording time, or NULL if unavailable. "
                "job_id identifies the job if recorded. "
                "estimated is 0 for provider-reported usage and 1 for an estimate. "
                "Use only those columns and this table. Do not query schema metadata, "
                "other tables, or use writes, pragmas, comments, or multiple statements. "
                "Return SQL only, and use aggregate results when the question asks for totals."
            )
        ),
        HumanMessage(
            content=(
                f"Prior user requests (reference only):\n{conversation_context}\n\n"
                f"Current user question: {prompt_text}"
            )
        ),
    ]
    sql_text = _invoke_usage_model(
        model, model_name, "usage_sql_generation", sql_messages,
        "The model returned no text for the usage lookup. Try asking a more specific token-usage question.",
    )
    sql = _sql_from_response(sql_text)
    rows = _execute_usage_query(sql, db_path)

    answer_messages = [
        SystemMessage(
            content=(
                "Answer the token-usage question using only the supplied SQLite result rows. "
                "Use prior user requests only to resolve references, and answer the current "
                "question rather than earlier questions. "
                "Do not invent values. Distinguish estimated usage from provider-reported usage. "
                "If there are no rows, state that no matching usage records were found. " + CHART_INSTRUCTIONS
            )
        ),
        HumanMessage(
            content=(
                f"Prior user requests (reference only):\n{conversation_context}\n\n"
                f"Current question: {prompt_text}\n\n"
                "SQLite result rows "
                f"(maximum {SETTINGS.query.max_sql_result_rows}): "
                f"{json.dumps(rows, default=str)}"
            )
        ),
    ]
    return _invoke_usage_model(
        model, model_name, "usage_sql_answer", answer_messages,
        "The model returned no text while summarizing usage. Try asking again.",
    )
