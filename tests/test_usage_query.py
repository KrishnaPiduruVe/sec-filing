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


def test_usage_costs_and_job_ids_are_saved_in_legacy_database(tmp_path, monkeypatch):
    from corporate_atlas.core.token_usage import model_usage, record_usage

    database = tmp_path / "usage.sqlite3"
    _create_usage_db(database)
    assert model_usage("first", database) == []

    monkeypatch.setenv("ATLAS_USAGE_JOB_ID", "first")
    record_usage("answer", "gemini-3.5-flash-lite", 1000, 100, estimated=False, db_path=database)
    monkeypatch.setenv("ATLAS_USAGE_JOB_ID", "second")
    record_usage("answer", "unknown-model", 500, 100, estimated=True, db_path=database)

    first, = model_usage("first", database)
    assert first["input_tokens"] == 1000
    assert first["output_tokens"] == 100
    assert first["cost_usd"] == pytest.approx(0.00055)
    assert model_usage("second", database)[0]["unpriced_events"] == 1
    with sqlite3.connect(database) as connection:
        saved, = connection.execute("SELECT cost_usd FROM token_usage WHERE job_id = 'first'").fetchone()
    assert saved == pytest.approx(0.00055)
    assert len(model_usage(db_path=database)) == 4
    assert model_usage(db_path=database, job_ids=["first", "first"]) == [first]
    assert model_usage(db_path=database, job_ids=[]) == []


def test_usage_question_reads_text_blocks_and_retries_reasoning_only_reply(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage
    from unittest.mock import Mock

    database = tmp_path / "usage.sqlite3"
    _create_usage_db(database)
    usage_log = Mock()
    monkeypatch.setattr("corporate_atlas.services.usage_query.record_chat_usage", usage_log)

    model = Mock()
    model.invoke.side_effect = [
        AIMessage(content=[{"type": "reasoning", "reasoning": "Compute total."}]),
        AIMessage(content=[
            {"type": "reasoning", "text": "This block is internal reasoning."},
            {"type": "text", "text": "SELECT SUM(input_tokens) AS total FROM token_usage"},
        ]),
        AIMessage(content=[{"type": "text", "text": "You used 150 input tokens."}]),
    ]

    answer = answer_usage_question("How many input tokens did I use?", db_path=database, llm=model)

    assert answer == "You used 150 input tokens."
    assert [call.args[0] for call in usage_log.call_args_list] == [
        "usage_sql_generation", "usage_sql_generation", "usage_sql_answer",
    ]
    assert '"total": 150' in model.invoke.call_args.args[0][1].content
