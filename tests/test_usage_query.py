import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from corporate_atlas.services.usage_query import (
    _execute_usage_query,
    _sql_from_response,
    answer_usage_question,
)


def _create_usage_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE token_usage (
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
        connection.executemany(
            """
            INSERT INTO token_usage
                (recorded_at, operation, model, input_tokens, output_tokens, estimated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-11-01T10:00:00+00:00", "answer", "test-model", 100, 25, 0),
                ("2026-11-02T10:00:00+00:00", "embedding", "test-embed", 50, 0, 1),
            ],
        )


def test_usage_question_runs_read_only_sql_and_summarizes_rows(tmp_path, monkeypatch):
    database = tmp_path / "usage.sqlite3"
    _create_usage_db(database)
    queries = []

    class FakeResponse:
        def __init__(self, content):
            self.content = content
            self.usage_metadata = {"input_tokens": 10, "output_tokens": 2}

    class FakeModel:
        def invoke(self, messages):
            if len(queries) == 0:
                queries.append(messages)
                return FakeResponse(
                    "SELECT operation, SUM(input_tokens) AS input_tokens "
                    "FROM token_usage GROUP BY operation ORDER BY operation"
                )
            queries.append(messages)
            return FakeResponse("Answer: answer used 100 input tokens.")

    monkeypatch.setattr(
        "corporate_atlas.services.usage_query.record_chat_usage",
        lambda *args, **kwargs: None,
    )
    answer = answer_usage_question(
        "You should look into SQLite to get this info.",
        db_path=database,
        llm=FakeModel(),
        history=[
            {"role": "user", "content": "How many input tokens were used by operation?"},
            {"role": "assistant", "content": "The SEC evidence did not include that."},
        ],
    )

    assert answer == "Answer: answer used 100 input tokens."
    assert len(queries) == 2
    assert "How many input tokens were used by operation?" in queries[0][1].content
    assert "The SEC evidence did not include that." not in queries[0][1].content
    result = _execute_usage_query(
        "SELECT operation, SUM(input_tokens) AS tokens FROM token_usage GROUP BY operation",
        database,
    )
    assert result == [{"operation": "answer", "tokens": 100}, {"operation": "embedding", "tokens": 50}]


def test_query_service_passes_history_to_usage_sql(monkeypatch, capsys):
    from corporate_atlas.services.query import main

    history = [{"role": "user", "content": "How many tokens did I consume?"}]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "corporate_atlas.services.query",
            "--mode",
            "usage",
            "--history",
            json.dumps(history),
            "--",
            "Look in SQLite for that.",
        ],
    )
    with patch(
        "corporate_atlas.services.usage_query.answer_usage_question",
        return_value="You consumed 125 tokens.",
    ) as answer_usage:
        main()
    answer_usage.assert_called_once_with(
        "Look in SQLite for that.",
        history=history,
    )
    assert capsys.readouterr().out.strip() == "You consumed 125 tokens."


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM token_usage",
        "SELECT name FROM sqlite_master",
        "SELECT operation FROM token_usage; DROP TABLE token_usage",
    ],
)
def test_generated_sql_is_restricted_to_single_usage_select(query):
    with pytest.raises(ValueError, match="outside the token-usage SQL scope"):
        _sql_from_response(query)


def test_usage_sql_authorizer_rejects_non_usage_tables(tmp_path):
    database = tmp_path / "usage.sqlite3"
    _create_usage_db(database)
    with pytest.raises(ValueError, match="not authorized"):
        _execute_usage_query(
            "SELECT usage.operation FROM token_usage AS usage "
            "JOIN sqlite_master AS schema_data ON 1=1",
            database,
        )
