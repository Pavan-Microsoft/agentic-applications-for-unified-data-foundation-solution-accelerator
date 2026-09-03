"""Unit tests for src/api/python/history_sql.py.

Every external dependency is mocked: pyodbc connections/cursors, the Azure CLI
credential (async), the AI Foundry ``AIProjectClient`` used for title
generation, Application Insights telemetry, OpenTelemetry spans, FastAPI
request objects and environment variables. No network, Azure or database
connection is ever opened.
"""

import json
import os
import struct
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pyodbc
import pytest
from azure.core.exceptions import HttpResponseError
from fastapi import HTTPException

import history_sql


USER = {"user_principal_id": "user-1"}
ANON = {"user_principal_id": None}
FIXED_UUID = UUID("11111111-2222-3333-4444-555555555555")


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class FakeAsyncCM:
    """Minimal async context manager yielding a fixed value."""

    def __init__(self, value):
        self.value = value
        self.exited = False

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        self.exited = True
        return False


class OutputItem:
    """Stand-in for an AI Foundry response output item."""

    def __init__(self, item_type, content=None):
        self.type = item_type
        self.content = content


class ContentlessItem:
    """Output item deliberately missing a ``content`` attribute."""

    def __init__(self, item_type):
        self.type = item_type


class TextPart:
    """Content part exposing a ``text`` attribute."""

    def __init__(self, text):
        self.text = text


class OpaquePart:
    """Content part deliberately missing a ``text`` attribute."""


def make_conn(rows=None, columns=None, execute_error=None, cursor_error=None):
    """Build a (connection, cursor) MagicMock pair mimicking pyodbc."""
    conn = MagicMock()
    cursor = MagicMock()
    if cursor_error is not None:
        conn.cursor.side_effect = cursor_error
    else:
        conn.cursor.return_value = cursor
    if execute_error is not None:
        cursor.execute.side_effect = execute_error
    cursor.description = [(name,) for name in (columns or [])]
    cursor.fetchall.return_value = list(rows or [])
    return conn, cursor


def make_request(body=None, headers=None):
    """Build a FastAPI-Request-like double with an awaitable ``json()``."""
    request = MagicMock()
    request.headers = headers if headers is not None else {"x-ms-client-principal-id": "user-1"}
    request.json = AsyncMock(return_value={} if body is None else body)
    return request


def make_credential(token_value="fake-token"):
    """Build an async AzureCliCredential double."""
    credential = MagicMock()
    credential.get_token = AsyncMock(return_value=SimpleNamespace(token=token_value))
    credential.close = AsyncMock()
    return credential


def token_struct_for(token_value):
    """Recompute the ODBC access-token struct the module builds."""
    token_bytes = token_value.encode("utf-16-LE")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def event_names(tracker):
    """Collect event names passed to a patched track_event_if_configured."""
    return [call.args[0] for call in tracker.call_args_list]


def body_of(response):
    """Decode a JSONResponse body back into Python objects."""
    return json.loads(response.body)


@pytest.fixture
def endpoint_env():
    """Patch auth, telemetry and tracing for route-handler tests."""
    with patch.object(history_sql, "get_authenticated_user_details") as auth, \
            patch.object(history_sql, "track_event_if_configured") as track, \
            patch.object(history_sql, "trace") as trace_mock:
        auth.return_value = dict(USER)
        span = MagicMock()
        trace_mock.get_current_span.return_value = span
        yield SimpleNamespace(auth=auth, track=track, trace=trace_mock, span=span)


# --------------------------------------------------------------------------- #
# track_event_if_configured
# --------------------------------------------------------------------------- #


def test_track_event_if_configured_forwards_event_when_connection_string_present():
    with patch.dict(os.environ, {"APPLICATIONINSIGHTS_CONNECTION_STRING": "conn-str"}), \
            patch.object(history_sql, "track_event") as track:
        history_sql.track_event_if_configured("ConversationsListed", {"user_id": "user-1"})

    track.assert_called_once_with("ConversationsListed", {"user_id": "user-1"})


def test_track_event_if_configured_skips_and_warns_when_not_configured():
    with patch.dict(os.environ, {}, clear=True), \
            patch.object(history_sql, "track_event") as track, \
            patch.object(history_sql.logging, "warning") as warn:
        history_sql.track_event_if_configured("ConversationsListed", {"user_id": "user-1"})

    track.assert_not_called()
    warn.assert_called_once()
    assert warn.call_args.args[1] == "ConversationsListed"


# --------------------------------------------------------------------------- #
# get_fabric_db_connection / get_db_connection
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_fabric_db_connection_prod_uses_driver18_connection_string():
    sentinel = MagicMock(name="conn18")
    env = {"FABRIC_SQL_CONNECTION_STRING": "DRIVER=18;SERVER=s;DATABASE=d;"}
    with patch.dict(os.environ, env, clear=True), \
            patch.object(history_sql.pyodbc, "connect", return_value=sentinel) as connect, \
            patch.object(history_sql, "AzureCliCredential") as cred_cls:
        result = await history_sql.get_fabric_db_connection()

    assert result is sentinel
    connect.assert_called_once_with("DRIVER=18;SERVER=s;DATABASE=d;")
    cred_cls.assert_not_called()


@pytest.mark.asyncio
async def test_get_fabric_db_connection_dev_uses_cli_token_with_driver18():
    sentinel = MagicMock(name="conn-dev18")
    credential = make_credential("dev-token")
    env = {"APP_ENV": "DEV", "FABRIC_SQL_SERVER": "srv", "FABRIC_SQL_DATABASE": "db"}
    with patch.dict(os.environ, env, clear=True), \
            patch.object(history_sql.pyodbc, "connect", return_value=sentinel) as connect, \
            patch.object(history_sql, "AzureCliCredential", return_value=credential):
        result = await history_sql.get_fabric_db_connection()

    assert result is sentinel
    credential.get_token.assert_awaited_once_with("https://database.windows.net/.default")
    credential.close.assert_awaited_once()
    connect.assert_called_once_with(
        "DRIVER=ODBC Driver 18 for SQL Server;SERVER=srv;DATABASE=db;",
        attrs_before={1256: token_struct_for("dev-token")},
    )


@pytest.mark.asyncio
async def test_get_fabric_db_connection_prod_falls_back_to_driver17_string():
    sentinel = MagicMock(name="conn17")
    env = {
        "FABRIC_SQL_CONNECTION_STRING": "DRIVER=18;",
        "FABRIC_SQL_SERVER": "srv",
        "FABRIC_SQL_DATABASE": "db",
        "API_UID": "uid-9",
    }
    with patch.dict(os.environ, env, clear=True), \
            patch.object(history_sql.pyodbc, "connect", side_effect=[RuntimeError("driver 18 missing"), sentinel]) as connect:
        result = await history_sql.get_fabric_db_connection()

    assert result is sentinel
    assert connect.call_count == 2
    assert connect.call_args_list[1].args[0] == (
        "DRIVER=ODBC Driver 17 for SQL Server;SERVER=srv;DATABASE=db;"
        "UID=uid-9;Authentication=ActiveDirectoryMSI"
    )


@pytest.mark.asyncio
async def test_get_fabric_db_connection_dev_falls_back_to_driver17_with_token():
    sentinel = MagicMock(name="conn-dev17")
    credential = make_credential("dev-token")
    env = {"APP_ENV": "dev", "FABRIC_SQL_SERVER": "srv", "FABRIC_SQL_DATABASE": "db"}
    with patch.dict(os.environ, env, clear=True), \
            patch.object(history_sql.pyodbc, "connect", side_effect=[RuntimeError("boom"), sentinel]) as connect, \
            patch.object(history_sql, "AzureCliCredential", return_value=credential):
        result = await history_sql.get_fabric_db_connection()

    assert result is sentinel
    assert credential.close.await_count == 2
    assert credential.get_token.await_count == 2
    assert connect.call_args_list[1].args[0] == "DRIVER=ODBC Driver 17 for SQL Server;SERVER=srv;DATABASE=db;"
    assert connect.call_args_list[1].kwargs == {"attrs_before": {1256: token_struct_for("dev-token")}}


@pytest.mark.asyncio
async def test_get_fabric_db_connection_returns_none_when_fallback_raises_pyodbc_error():
    with patch.dict(os.environ, {"FABRIC_SQL_CONNECTION_STRING": "cs"}, clear=True), \
            patch.object(history_sql.pyodbc, "connect", side_effect=[RuntimeError("first"), pyodbc.Error("fallback")]), \
            patch.object(history_sql.logging, "info") as info:
        result = await history_sql.get_fabric_db_connection()

    assert result is None
    assert "FABRIC-SQL:Failed to connect Fabric SQL Database: %s" in info.call_args.args[0]


@pytest.mark.asyncio
async def test_get_fabric_db_connection_propagates_non_pyodbc_fallback_errors():
    with patch.dict(os.environ, {"FABRIC_SQL_CONNECTION_STRING": "cs"}, clear=True), \
            patch.object(history_sql.pyodbc, "connect", side_effect=[RuntimeError("first"), OSError("driver crash")]):
        with pytest.raises(OSError, match="driver crash"):
            await history_sql.get_fabric_db_connection()


@pytest.mark.asyncio
async def test_get_db_connection_delegates_to_fabric_connection():
    sentinel = MagicMock(name="fabric-conn")
    with patch.object(history_sql, "get_fabric_db_connection", AsyncMock(return_value=sentinel)) as fabric:
        result = await history_sql.get_db_connection()

    assert result is sentinel
    fabric.assert_awaited_once_with()


# --------------------------------------------------------------------------- #
# run_nonquery_params
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_nonquery_params_returns_false_when_connection_is_none():
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=None)), \
            patch.object(history_sql.logging, "error") as error:
        result = await history_sql.run_nonquery_params("DELETE FROM t WHERE id = ?", ("c1",))

    assert result is False
    error.assert_called_once_with("Failed to establish database connection")


@pytest.mark.asyncio
async def test_run_nonquery_params_commits_and_closes_on_success():
    conn, cursor = make_conn()
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)):
        result = await history_sql.run_nonquery_params("DELETE FROM t WHERE id = ?", ("c1",))

    assert result is True
    cursor.execute.assert_called_once_with("DELETE FROM t WHERE id = ?", ("c1",))
    conn.commit.assert_called_once_with()
    cursor.close.assert_called_once_with()
    conn.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_run_nonquery_params_defaults_params_to_empty_tuple():
    conn, cursor = make_conn()
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)):
        result = await history_sql.run_nonquery_params("DELETE FROM t")

    assert result is True
    cursor.execute.assert_called_once_with("DELETE FROM t", ())


@pytest.mark.asyncio
async def test_run_nonquery_params_returns_false_and_closes_when_execute_fails():
    conn, cursor = make_conn(execute_error=RuntimeError("bad sql"))
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)), \
            patch.object(history_sql.logging, "error") as error:
        result = await history_sql.run_nonquery_params("DELETE FROM t WHERE id = ?", ("c1",))

    assert result is False
    conn.commit.assert_not_called()
    cursor.close.assert_called_once_with()
    conn.close.assert_called_once_with()
    assert error.call_args.args[0] == "Error executing SQL query: %s"


@pytest.mark.asyncio
async def test_run_nonquery_params_skips_cursor_close_when_cursor_creation_fails():
    conn, cursor = make_conn(cursor_error=RuntimeError("no cursor"))
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)):
        result = await history_sql.run_nonquery_params("DELETE FROM t")

    assert result is False
    cursor.close.assert_not_called()
    conn.close.assert_called_once_with()


# --------------------------------------------------------------------------- #
# run_query_params
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_query_params_returns_none_when_connection_is_none():
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=None)), \
            patch.object(history_sql.logging, "error") as error:
        result = await history_sql.run_query_params("SELECT 1", ())

    assert result is None
    error.assert_called_once_with("Failed to establish database connection")


@pytest.mark.asyncio
async def test_run_query_params_normalizes_dates_and_decimals():
    rows = [(datetime(2024, 5, 6, 7, 8, 9), date(2024, 5, 6), Decimal("1.50"), "hello", None)]
    conn, cursor = make_conn(rows=rows, columns=["ts", "day", "amount", "title", "empty"])
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)):
        result = await history_sql.run_query_params("SELECT * FROM t WHERE id = ?", ("c1",))

    assert result == [{
        "ts": "2024-05-06T07:08:09",
        "day": "2024-05-06",
        "amount": 1.5,
        "title": "hello",
        "empty": None,
    }]
    # Decimal("1.50") == 1.5 is True, so pin the concrete type the cast produces.
    assert isinstance(result[0]["amount"], float)
    assert isinstance(result[0]["ts"], str)
    cursor.execute.assert_called_once_with("SELECT * FROM t WHERE id = ?", ("c1",))
    cursor.close.assert_called_once_with()
    conn.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_run_query_params_returns_empty_list_when_no_rows():
    conn, cursor = make_conn(rows=[], columns=["title"])
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)):
        result = await history_sql.run_query_params("SELECT title FROM t")

    assert result == []
    cursor.execute.assert_called_once_with("SELECT title FROM t", ())
    conn.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_run_query_params_returns_none_and_closes_when_execute_fails():
    conn, cursor = make_conn(execute_error=RuntimeError("bad sql"))
    with patch.object(history_sql, "get_db_connection", AsyncMock(return_value=conn)), \
            patch.object(history_sql.logging, "error") as error:
        result = await history_sql.run_query_params("SELECT 1")

    assert result is None
    cursor.close.assert_called_once_with()
    conn.close.assert_called_once_with()
    assert error.call_args.args[0] == "Error executing SQL query: %s"


# --------------------------------------------------------------------------- #
# get_conversations
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_conversations_filters_by_user_and_applies_sort_order():
    rows = [{"conversation_id": "c1", "title": "First"}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=rows)) as query:
        result = await history_sql.get_conversations("user-1", limit=25, sort_order="ASC", offset=0)

    assert result == rows
    sql, params = query.await_args.args
    assert "where userId = ?" in sql
    assert sql.endswith("order by updatedAt ASC")
    assert params == ("user-1",)


@pytest.mark.asyncio
async def test_get_conversations_without_user_selects_all_conversations():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])) as query:
        result = await history_sql.get_conversations(None, limit=25)

    assert result == []
    sql, params = query.await_args.args
    assert "where userId" not in sql
    assert sql.endswith("ORDER BY updatedAt DESC")
    assert params == ()


@pytest.mark.asyncio
async def test_get_conversations_propagates_query_errors():
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        with pytest.raises(RuntimeError, match="db down"):
            await history_sql.get_conversations("user-1", limit=25)

    log.assert_called_once_with("Error in get_conversation")


# --------------------------------------------------------------------------- #
# get_conversation_messages
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_none_without_conversation_id():
    with patch.object(history_sql, "run_query_params", AsyncMock()) as query, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.get_conversation_messages("user-1", "")

    assert result is None
    query.assert_not_awaited()
    warn.assert_called_once_with("No conversation_id found, cannot retrieve conversation messages.")


@pytest.mark.asyncio
async def test_get_conversation_messages_deserializes_citations_and_json_content():
    rows = [{
        "role": "assistant",
        "content": '{"answer": "42"}',
        "citations": '[{"title": "doc"}]',
        "feedback": "",
    }]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=rows)) as query:
        result = await history_sql.get_conversation_messages("user-1", "c1", sort_order="DESC")

    assert result == [{
        "role": "assistant",
        "content": {"answer": "42"},
        "citations": [{"title": "doc"}],
        "feedback": "",
    }]
    sql, params = query.await_args.args
    assert "where userId = ? and conversation_id = ?" in sql
    assert sql.endswith("order by updatedAt DESC")
    assert params == ("user-1", "c1")


@pytest.mark.asyncio
async def test_get_conversation_messages_without_user_filters_on_conversation_only():
    rows = [{"role": "user", "content": "plain text", "citations": None, "feedback": None}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=rows)) as query:
        result = await history_sql.get_conversation_messages(None, "c1")

    assert result == [{"role": "user", "content": "plain text", "citations": [], "feedback": None}]
    sql, params = query.await_args.args
    assert "userId" not in sql
    assert sql.endswith("order by updatedAt ASC")
    assert params == ("c1",)


@pytest.mark.asyncio
async def test_get_conversation_messages_replaces_unparsable_citations_with_empty_list():
    rows = [{"role": "assistant", "content": 42, "citations": "not-json", "feedback": ""}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=rows)), \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.get_conversation_messages("user-1", "c1")

    assert result[0]["citations"] == []
    assert result[0]["content"] == 42
    assert warn.call_args.args[0] == "Failed to deserialize citations: %s"


@pytest.mark.asyncio
async def test_get_conversation_messages_does_not_mutate_source_rows():
    rows = [{"role": "user", "content": '"hi"', "citations": '["a"]', "feedback": ""}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=rows)):
        result = await history_sql.get_conversation_messages("user-1", "c1")

    assert result[0]["content"] == "hi"
    assert rows[0]["content"] == '"hi"'
    assert rows[0]["citations"] == '["a"]'


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_none_when_query_returns_none():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=None)), \
            patch.object(history_sql.logger, "exception") as log:
        result = await history_sql.get_conversation_messages("user-1", "c1")

    assert result is None
    log.assert_called_once()


# --------------------------------------------------------------------------- #
# delete_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_conversation_returns_false_without_conversation_id():
    with patch.object(history_sql, "run_query_params", AsyncMock()) as query, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.delete_conversation("user-1", None)

    assert result is False
    query.assert_not_awaited()
    warn.assert_called_once_with("No conversation_id found, cannot delete conversation.")


@pytest.mark.asyncio
async def test_delete_conversation_returns_false_when_conversation_missing():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.delete_conversation("user-1", "c1")

    assert result is False
    nonquery.assert_not_awaited()
    assert warn.call_args.args == ("Conversation %s not found.", "c1")


@pytest.mark.asyncio
async def test_delete_conversation_denies_when_user_does_not_own_conversation():
    owned_by_other = [{"userId": "user-2", "conversation_id": "c1"}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=owned_by_other)), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.delete_conversation("user-1", "c1")

    assert result is False
    nonquery.assert_not_awaited()
    assert warn.call_args.args == (
        "User %s does not have permission to delete %s.", "user-1", "c1",
    )


@pytest.mark.asyncio
async def test_delete_conversation_removes_messages_then_conversation_for_owner():
    owned = [{"userId": "user-1", "conversation_id": "c1"}]
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=owned)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.delete_conversation("user-1", "c1")

    assert result is True
    assert nonquery.await_count == 2
    first_sql, first_params = nonquery.await_args_list[0].args
    second_sql, second_params = nonquery.await_args_list[1].args
    assert first_sql.startswith("DELETE FROM hst_conversation_messages")
    assert second_sql.startswith("DELETE FROM hst_conversations")
    assert first_params == ("user-1", "c1")
    assert second_params == ("user-1", "c1")


@pytest.mark.asyncio
async def test_delete_conversation_without_user_deletes_by_conversation_id_only():
    existing = [{"userId": "user-2", "conversation_id": "c1"}]
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=existing)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.delete_conversation(None, "c1")

    assert result is True
    assert nonquery.await_count == 2
    assert nonquery.await_args_list[0].args == (
        "DELETE FROM hst_conversation_messages where conversation_id = ?", "c1",
    )
    assert nonquery.await_args_list[1].args == (
        "DELETE FROM hst_conversations where conversation_id = ?", "c1",
    )


@pytest.mark.asyncio
async def test_delete_conversation_returns_false_on_unexpected_error():
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        result = await history_sql.delete_conversation("user-1", "c1")

    assert result is False
    log.assert_called_once()


# --------------------------------------------------------------------------- #
# delete_all_conversations
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_all_conversations_scopes_deletes_to_user():
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.delete_all_conversations("user-1")

    assert result is True
    assert nonquery.await_args_list[0].args == (
        "DELETE FROM hst_conversation_messages WHERE userId = ?", ("user-1",),
    )
    assert nonquery.await_args_list[1].args == (
        "DELETE FROM hst_conversations WHERE userId = ?", ("user-1",),
    )


@pytest.mark.asyncio
async def test_delete_all_conversations_without_user_deletes_every_row():
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.delete_all_conversations(None)

    assert result is True
    assert nonquery.await_args_list[0].args == ("DELETE FROM hst_conversation_messages",)
    assert nonquery.await_args_list[1].args == ("DELETE FROM hst_conversations",)


@pytest.mark.asyncio
async def test_delete_all_conversations_returns_false_when_message_delete_fails():
    nonquery = AsyncMock(side_effect=[False, True])
    with patch.object(history_sql, "run_nonquery_params", nonquery), \
            patch.object(history_sql.logger, "error") as error:
        result = await history_sql.delete_all_conversations("user-1")

    assert result is False
    assert error.call_args.args == ("Failed to delete all conversations for user %s", "user-1")


@pytest.mark.asyncio
async def test_delete_all_conversations_returns_false_when_conversation_delete_fails():
    nonquery = AsyncMock(side_effect=[True, False])
    with patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.delete_all_conversations("user-1")

    assert result is False


@pytest.mark.asyncio
async def test_delete_all_conversations_returns_false_on_unexpected_error():
    with patch.object(history_sql, "run_nonquery_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        result = await history_sql.delete_all_conversations("user-1")

    assert result is False
    log.assert_called_once()


# --------------------------------------------------------------------------- #
# rename_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rename_conversation_returns_false_without_conversation_id():
    with patch.object(history_sql, "run_query_params", AsyncMock()) as query, \
            patch.object(history_sql.logger, "exception") as log:
        result = await history_sql.rename_conversation("user-1", None, "New title")

    assert result is False
    query.assert_not_awaited()
    log.assert_called_once()


@pytest.mark.asyncio
async def test_rename_conversation_returns_false_when_title_is_none():
    with patch.object(history_sql, "run_query_params", AsyncMock()) as query, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.rename_conversation("user-1", "c1", None)

    assert result is False
    query.assert_not_awaited()
    assert warn.call_args.args == (
        "Title is None, cannot rename title of the conversation %s.", "c1",
    )


@pytest.mark.asyncio
async def test_rename_conversation_returns_false_when_conversation_missing():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery:
        result = await history_sql.rename_conversation("user-1", "c1", "New title")

    assert result is False
    nonquery.assert_not_awaited()


@pytest.mark.asyncio
async def test_rename_conversation_denies_when_user_does_not_own_conversation():
    owned_by_other = [{"userId": "user-2", "conversation_id": "c1"}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=owned_by_other)), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.rename_conversation("user-1", "c1", "New title")

    assert result is False
    nonquery.assert_not_awaited()
    assert warn.call_args.args == (
        "User %s does not have permission to rename %s.", "user-1", "c1",
    )


@pytest.mark.asyncio
async def test_rename_conversation_updates_title_for_owner():
    owned = [{"userId": "user-1", "conversation_id": "c1"}]
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=owned)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.rename_conversation("user-1", "c1", "New title")

    assert result is True
    sql, params = nonquery.await_args.args
    assert sql == "UPDATE hst_conversations SET title = ? WHERE userId = ?  and conversation_id = ?"
    assert params == ("New title", "user-1", "c1")


@pytest.mark.asyncio
async def test_rename_conversation_without_user_updates_by_conversation_id():
    existing = [{"userId": "user-2", "conversation_id": "c1"}]
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=existing)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.rename_conversation(None, "c1", "New title")

    assert result is True
    sql, params = nonquery.await_args.args
    assert sql == "UPDATE hst_conversations SET title = ? WHERE conversation_id = ?"
    assert params == ("New title", "c1")


@pytest.mark.asyncio
async def test_rename_conversation_returns_false_on_unexpected_error():
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        result = await history_sql.rename_conversation("user-1", "c1", "New title")

    assert result is False
    log.assert_called_once()


# --------------------------------------------------------------------------- #
# generate_fallback_title / _generate_fallback_title_from_message
# --------------------------------------------------------------------------- #


def test_generate_fallback_title_uses_first_user_message():
    messages = [
        {"role": "assistant", "content": "ignored"},
        {"role": "user", "content": "how many invoices are overdue this quarter"},
        {"role": "user", "content": "second question"},
    ]

    assert history_sql.generate_fallback_title(messages) == "how many invoices are"


def test_generate_fallback_title_defaults_when_no_user_messages():
    assert history_sql.generate_fallback_title([{"role": "assistant", "content": "hi"}]) == "New Conversation"


def test_generate_fallback_title_from_message_truncates_to_four_words():
    assert history_sql._generate_fallback_title_from_message("one two three four five") == "one two three four"


def test_generate_fallback_title_from_message_stringifies_dict_content():
    result = history_sql._generate_fallback_title_from_message({"text": "hello brave new world today"})

    assert result == "{'text': 'hello brave new"


@pytest.mark.parametrize("content", ["", "   ", None, 0])
def test_generate_fallback_title_from_message_defaults_for_blank_content(content):
    assert history_sql._generate_fallback_title_from_message(content) == "New Conversation"


def test_generate_fallback_title_from_message_stringifies_non_string_content():
    assert history_sql._generate_fallback_title_from_message(12345) == "12345"


# --------------------------------------------------------------------------- #
# generate_title
# --------------------------------------------------------------------------- #


def make_foundry_client(output=None, create_error=None):
    """Build an AIProjectClient double exposing the OpenAI-style surface."""
    openai_client = MagicMock()
    openai_client.conversations.create = AsyncMock(return_value=SimpleNamespace(id="conv-abc"))
    if create_error is not None:
        openai_client.responses.create = AsyncMock(side_effect=create_error)
    else:
        openai_client.responses.create = AsyncMock(
            return_value=SimpleNamespace(output=list(output or []))
        )
    project_client = MagicMock()
    project_client.get_openai_client.return_value = openai_client
    return project_client, openai_client


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_no_user_messages():
    messages = [{"role": "assistant", "content": "hello"}]
    with patch.object(history_sql, "AIProjectClient") as client_cls:
        result = await history_sql.generate_title(messages)

    assert result == "New Conversation"
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_endpoint_not_configured():
    messages = [{"role": "user", "content": "show me overdue invoices please"}]
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", None), \
            patch.object(history_sql, "AIProjectClient") as client_cls:
        result = await history_sql.generate_title(messages)

    assert result == "show me overdue invoices"
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_generate_title_returns_agent_text_and_sends_combined_prompt():
    messages = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "an answer"},
        {"role": "user", "content": "second question"},
    ]
    output = [
        ContentlessItem("reasoning"),
        OutputItem("message", [TextPart("\n  Overdue "), TextPart("Invoice Report  \n")]),
    ]
    project_client, openai_client = make_foundry_client(output=output)
    credential = MagicMock(name="credential")
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", "https://foundry.example/api"), \
            patch.object(history_sql, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history_sql, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history_sql, "AIProjectClient", return_value=FakeAsyncCM(project_client)) as client_cls:
        result = await history_sql.generate_title(messages)

    assert result == "Overdue Invoice Report"
    client_cls.assert_called_once_with(endpoint="https://foundry.example/api", credential=credential)
    openai_client.conversations.create.assert_awaited_once_with()
    create_kwargs = openai_client.responses.create.await_args.kwargs
    assert create_kwargs["conversation"] == "conv-abc"
    assert create_kwargs["input"] == (
        "Generate a 4-word or less title for this request:\n"
        "first question\nsecond question"
    )
    assert create_kwargs["extra_body"] == {
        "agent_reference": {"name": "TitleAgent", "type": "agent_reference"}
    }


@pytest.mark.asyncio
async def test_generate_title_skips_non_message_and_contentless_output_items():
    messages = [{"role": "user", "content": "quarterly revenue by region breakdown"}]
    output = [
        OutputItem("tool_call", [TextPart("ignored tool text")]),
        ContentlessItem("message"),
        OutputItem("message", None),
        OutputItem("message", [OpaquePart(), TextPart("Regional Revenue")]),
    ]
    project_client, _ = make_foundry_client(output=output)
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", "https://foundry.example/api"), \
            patch.object(history_sql, "get_azure_credential_async", AsyncMock(return_value=MagicMock())), \
            patch.object(history_sql, "AIProjectClient", return_value=FakeAsyncCM(project_client)):
        result = await history_sql.generate_title(messages)

    assert result == "Regional Revenue"


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_agent_returns_no_text():
    messages = [{"role": "user", "content": "quarterly revenue by region breakdown"}]
    project_client, _ = make_foundry_client(output=[OutputItem("message", [OpaquePart()])])
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", "https://foundry.example/api"), \
            patch.object(history_sql, "get_azure_credential_async", AsyncMock(return_value=MagicMock())), \
            patch.object(history_sql, "AIProjectClient", return_value=FakeAsyncCM(project_client)):
        result = await history_sql.generate_title(messages)

    assert result == "quarterly revenue by region"


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_http_response_error():
    messages = [{"role": "user", "content": "quarterly revenue by region breakdown"}]
    project_client, _ = make_foundry_client(create_error=HttpResponseError("agent unavailable"))
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", "https://foundry.example/api"), \
            patch.object(history_sql, "get_azure_credential_async", AsyncMock(return_value=MagicMock())), \
            patch.object(history_sql, "AIProjectClient", return_value=FakeAsyncCM(project_client)), \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.generate_title(messages)

    assert result == "quarterly revenue by region"
    assert warn.call_args.args[0] == (
        "HttpResponseError generating title with Azure AI Foundry agent: %s"
    )


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_unexpected_error():
    messages = [{"role": "user", "content": "quarterly revenue by region breakdown"}]
    with patch.object(history_sql, "AZURE_AI_AGENT_ENDPOINT", "https://foundry.example/api"), \
            patch.object(history_sql, "get_azure_credential_async", AsyncMock(side_effect=RuntimeError("no creds"))), \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.generate_title(messages)

    assert result == "quarterly revenue by region"
    assert warn.call_args.args[0] == "Error generating title with Azure AI Foundry agent: %s"


# --------------------------------------------------------------------------- #
# create_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_conversation_returns_existing_conversation_without_insert():
    existing = [{"conversation_id": "c1", "title": "Existing"}]
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=existing)), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery:
        result = await history_sql.create_conversation("user-1", title="New", conversation_id="c1")

    assert result == existing
    nonquery.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_conversation_inserts_row_with_matching_timestamps():
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.create_conversation("user-1", title="Overdue", conversation_id="c1")

    assert result is True
    sql, params = nonquery.await_args.args
    assert sql.startswith("INSERT INTO hst_conversations")
    assert params[:3] == ("user-1", "c1", "Overdue")
    assert params[3] == params[4]
    datetime.fromisoformat(params[3])


@pytest.mark.asyncio
async def test_create_conversation_generates_id_when_missing():
    nonquery = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])) as query, \
            patch.object(history_sql, "run_nonquery_params", nonquery), \
            patch.object(history_sql.uuid, "uuid4", return_value=FIXED_UUID), \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.create_conversation("user-1")

    assert result is True
    assert query.await_args.args[1] == (str(FIXED_UUID),)
    assert nonquery.await_args.args[1][1] == str(FIXED_UUID)
    assert nonquery.await_args.args[1][2] == ""
    warn.assert_called_once_with("No conversation_id found, generating a new one.")


@pytest.mark.asyncio
async def test_create_conversation_propagates_errors():
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        with pytest.raises(RuntimeError, match="db down"):
            await history_sql.create_conversation("user-1", conversation_id="c1")

    log.assert_called_once_with("Error in create_conversation")


# --------------------------------------------------------------------------- #
# create_message
# --------------------------------------------------------------------------- #


CONVERSATION_ROW = [{"conversation_id": "c1", "userId": "user-1"}]


@pytest.mark.asyncio
async def test_create_message_returns_none_without_conversation_id():
    with patch.object(history_sql, "run_query_params", AsyncMock()) as query, \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.create_message("m1", None, "user-1", {"role": "user", "content": "hi", "id": "m1"})

    assert result is None
    query.assert_not_awaited()
    warn.assert_called_once_with("No conversation_id found, cannot create conversation message.")


@pytest.mark.asyncio
async def test_create_message_returns_none_when_conversation_missing():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=[])), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock()) as nonquery, \
            patch.object(history_sql.logger, "error") as error:
        result = await history_sql.create_message("m1", "c1", "user-1", {"role": "user", "content": "hi", "id": "m1"})

    assert result is None
    nonquery.assert_not_awaited()
    assert error.call_args.args == ("Conversation not found for ID: %s", "c1")


@pytest.mark.asyncio
async def test_create_message_inserts_message_then_touches_conversation():
    nonquery = AsyncMock(return_value=True)
    message = {
        "role": "assistant",
        "content": "Here is the answer",
        "id": "m1",
        "citations": [{"title": "doc-1"}],
    }
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=CONVERSATION_ROW)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.create_message("m1", "c1", "user-1", message)

    assert result is True
    assert nonquery.await_count == 2
    insert_sql, insert_params = nonquery.await_args_list[0].args
    assert insert_sql.startswith("INSERT INTO hst_conversation_messages")
    assert insert_params[:7] == (
        "user-1", "c1", "assistant", "m1", "Here is the answer", '[{"title": "doc-1"}]', "",
    )
    assert insert_params[7] == insert_params[8]
    update_sql, update_params = nonquery.await_args_list[1].args
    assert update_sql == "UPDATE hst_conversations SET updatedAt = ? WHERE conversation_id = ?"
    assert update_params == (insert_params[8], "c1")


@pytest.mark.asyncio
async def test_create_message_serializes_dict_content():
    nonquery = AsyncMock(return_value=True)
    message = {"role": "assistant", "content": {"answer": 42}, "id": "m1"}
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=CONVERSATION_ROW)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.create_message("m1", "c1", "user-1", message)

    assert result is True
    insert_params = nonquery.await_args_list[0].args[1]
    assert insert_params[4] == '{"answer": 42}'
    assert insert_params[5] == ""


@pytest.mark.asyncio
async def test_create_message_stores_empty_citations_when_serialization_fails():
    nonquery = AsyncMock(return_value=True)
    message = {"role": "user", "content": "hi", "id": "m1", "citations": [object()]}
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=CONVERSATION_ROW)), \
            patch.object(history_sql, "run_nonquery_params", nonquery), \
            patch.object(history_sql.logger, "warning") as warn:
        result = await history_sql.create_message("m1", "c1", "user-1", message)

    assert result is True
    assert nonquery.await_args_list[0].args[1][5] == ""
    assert warn.call_args.args[0] == "Failed to serialize citations: %s"


@pytest.mark.asyncio
async def test_create_message_returns_false_when_insert_fails():
    nonquery = AsyncMock(return_value=False)
    message = {"role": "user", "content": "hi", "id": "m1"}
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=CONVERSATION_ROW)), \
            patch.object(history_sql, "run_nonquery_params", nonquery):
        result = await history_sql.create_message("m1", "c1", "user-1", message)

    assert result is False
    assert nonquery.await_count == 1


@pytest.mark.asyncio
async def test_create_message_propagates_errors():
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=CONVERSATION_ROW)), \
            patch.object(history_sql, "run_nonquery_params", AsyncMock(return_value=True)), \
            patch.object(history_sql.logger, "exception") as log:
        with pytest.raises(KeyError):
            await history_sql.create_message("m1", "c1", "user-1", {"content": "hi", "id": "m1"})

    log.assert_called_once_with("Error in create_message")


# --------------------------------------------------------------------------- #
# update_conversation
# --------------------------------------------------------------------------- #


UPDATED_ROW = [{"conversation_id": "c1", "title": "Overdue Invoices", "updatedAt": "2024-05-06T07:08:09"}]


@pytest.mark.asyncio
async def test_update_conversation_creates_conversation_and_returns_summary():
    request_json = {
        "conversation_id": "c1",
        "messages": [
            {"role": "user", "content": "hi", "id": "m1"},
            {"role": "assistant", "content": "hello", "id": "m2"},
        ],
    }
    query = AsyncMock(side_effect=[[], UPDATED_ROW])
    create_conv = AsyncMock(return_value=True)
    create_msg = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", query), \
            patch.object(history_sql, "generate_title", AsyncMock(return_value="Overdue Invoices")) as title, \
            patch.object(history_sql, "create_conversation", create_conv), \
            patch.object(history_sql, "create_message", create_msg):
        result = await history_sql.update_conversation("user-1", request_json)

    assert result == {"id": "c1", "title": "Overdue Invoices", "updatedAt": "2024-05-06T07:08:09"}
    title.assert_awaited_once_with(request_json["messages"])
    create_conv.assert_awaited_once_with(user_id="user-1", conversation_id="c1", title="Overdue Invoices")
    assert create_msg.await_count == 2
    assert create_msg.await_args_list[1].kwargs["uuid"] == "m2"


@pytest.mark.asyncio
async def test_update_conversation_skips_creation_for_existing_conversation():
    request_json = {
        "conversation_id": "c1",
        "messages": [
            {"role": "user", "content": "hi", "id": "m1"},
            {"role": "error", "content": "boom", "id": "m2"},
        ],
    }
    query = AsyncMock(side_effect=[UPDATED_ROW, UPDATED_ROW])
    with patch.object(history_sql, "run_query_params", query), \
            patch.object(history_sql, "generate_title", AsyncMock()) as title, \
            patch.object(history_sql, "create_conversation", AsyncMock()) as create_conv, \
            patch.object(history_sql, "create_message", AsyncMock(return_value=True)):
        result = await history_sql.update_conversation("user-1", request_json)

    assert result["title"] == "Overdue Invoices"
    title.assert_not_awaited()
    create_conv.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_conversation_persists_tool_message_before_assistant():
    tool_message = {"role": "tool", "content": "tool output", "id": "m2"}
    request_json = {
        "conversation_id": "c1",
        "messages": [
            {"role": "user", "content": "hi", "id": "m1"},
            tool_message,
            {"role": "assistant", "content": "hello", "id": "m3"},
        ],
    }
    create_msg = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=[UPDATED_ROW, UPDATED_ROW])), \
            patch.object(history_sql, "create_message", create_msg):
        result = await history_sql.update_conversation("user-1", request_json)

    assert result["id"] == "c1"
    assert create_msg.await_count == 3
    assert create_msg.await_args_list[1].kwargs["input_message"] is tool_message
    assert create_msg.await_args_list[2].kwargs["uuid"] == "m3"


@pytest.mark.asyncio
async def test_update_conversation_uses_last_user_message_for_the_user_row():
    first_user = {"role": "user", "content": "first", "id": "m1"}
    last_user = {"role": "user", "content": "latest", "id": "m3"}
    request_json = {
        "conversation_id": "c1",
        "messages": [first_user, {"role": "assistant", "content": "a", "id": "m2"}, last_user,
                     {"role": "assistant", "content": "b", "id": "m4"}],
    }
    create_msg = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=[UPDATED_ROW, UPDATED_ROW])), \
            patch.object(history_sql, "create_message", create_msg), \
            patch.object(history_sql.uuid, "uuid4", return_value=FIXED_UUID):
        await history_sql.update_conversation("user-1", request_json)

    assert create_msg.await_args_list[0].kwargs["input_message"] is last_user
    assert create_msg.await_args_list[0].kwargs["uuid"] == str(FIXED_UUID)


@pytest.mark.asyncio
async def test_update_conversation_rejects_request_without_leading_user_message():
    request_json = {"conversation_id": "c1", "messages": [{"role": "assistant", "content": "hi", "id": "m1"}]}
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=UPDATED_ROW)), \
            patch.object(history_sql, "create_message", AsyncMock()) as create_msg:
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation("user-1", request_json)

    assert exc.value.status_code == 400
    assert exc.value.detail == "User message not found"
    create_msg.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_conversation_rejects_empty_message_list():
    request_json = {"conversation_id": "c1", "messages": []}
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=UPDATED_ROW)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation("user-1", request_json)

    assert exc.value.status_code == 400
    assert exc.value.detail == "User message not found"


@pytest.mark.asyncio
async def test_update_conversation_raises_when_user_message_cannot_be_created():
    request_json = {
        "conversation_id": "c1",
        "messages": [
            {"role": "user", "content": "hi", "id": "m1"},
            {"role": "assistant", "content": "hello", "id": "m2"},
        ],
    }
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=UPDATED_ROW)), \
            patch.object(history_sql, "create_message", AsyncMock(return_value=None)) as create_msg:
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation("user-1", request_json)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Conversation not found"
    assert create_msg.await_count == 1


@pytest.mark.asyncio
async def test_update_conversation_rejects_request_without_trailing_assistant_message():
    request_json = {"conversation_id": "c1", "messages": [{"role": "user", "content": "hi", "id": "m1"}]}
    create_msg = AsyncMock(return_value=True)
    with patch.object(history_sql, "run_query_params", AsyncMock(return_value=UPDATED_ROW)), \
            patch.object(history_sql, "create_message", create_msg):
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation("user-1", request_json)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Assistant message not found"
    assert create_msg.await_count == 1


@pytest.mark.asyncio
async def test_update_conversation_returns_none_when_conversation_disappears():
    request_json = {
        "conversation_id": "c1",
        "messages": [
            {"role": "user", "content": "hi", "id": "m1"},
            {"role": "assistant", "content": "hello", "id": "m2"},
        ],
    }
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=[UPDATED_ROW, []])), \
            patch.object(history_sql, "create_message", AsyncMock(return_value=True)):
        result = await history_sql.update_conversation("user-1", request_json)

    assert result is None


@pytest.mark.asyncio
async def test_update_conversation_propagates_unexpected_errors():
    with patch.object(history_sql, "run_query_params", AsyncMock(side_effect=RuntimeError("db down"))), \
            patch.object(history_sql.logger, "exception") as log:
        with pytest.raises(RuntimeError, match="db down"):
            await history_sql.update_conversation("user-1", {"conversation_id": "c1", "messages": []})

    log.assert_called_once_with("Error in update_conversation")


# --------------------------------------------------------------------------- #
# GET /list
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_conversations_returns_conversations_and_tracks_event(endpoint_env):
    conversations = [{"conversation_id": "c1", "title": "First"}]
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=conversations)) as get_convs:
        response = await history_sql.list_conversations(make_request(), offset=5, limit=10)

    assert response.status_code == 200
    assert body_of(response) == conversations
    get_convs.assert_awaited_once_with("user-1", offset=5, limit=10)
    endpoint_env.track.assert_called_once_with("ConversationsListed", {
        "user_id": "user-1", "offset": 5, "limit": 10, "conversation_count": 1,
    })


@pytest.mark.asyncio
async def test_list_conversations_skips_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=[])):
        response = await history_sql.list_conversations(make_request(), offset=0, limit=25)

    assert response.status_code == 200
    assert body_of(response) == []
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_list_conversations_reraises_http_exception(endpoint_env):
    endpoint_env.auth.side_effect = HTTPException(status_code=401, detail="unauthorized")
    with pytest.raises(HTTPException) as exc:
        await history_sql.list_conversations(make_request(), offset=0, limit=25)

    assert exc.value.status_code == 401
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_list_conversations_returns_500_and_records_span_on_error(endpoint_env):
    with patch.object(history_sql, "get_conversations", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.list_conversations(make_request(), offset=0, limit=25)

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    assert event_names(endpoint_env.track) == ["ListConversationsError"]
    assert endpoint_env.track.call_args.args[1]["error_type"] == "RuntimeError"
    endpoint_env.span.record_exception.assert_called_once()
    endpoint_env.span.set_status.assert_called_once()


@pytest.mark.asyncio
async def test_list_conversations_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    with patch.object(history_sql, "get_conversations", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.list_conversations(make_request(), offset=0, limit=25)

    assert response.status_code == 500
    endpoint_env.span.record_exception.assert_not_called()


# --------------------------------------------------------------------------- #
# GET /read
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_read_conversation_returns_messages(endpoint_env):
    messages = [{"role": "user", "content": "hi", "citations": []}]
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(return_value=messages)) as get_msgs:
        response = await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert response.status_code == 200
    assert body_of(response) == {"conversation_id": "c1", "messages": messages}
    get_msgs.assert_awaited_once_with("user-1", "c1")
    endpoint_env.track.assert_called_once_with("ConversationRead", {
        "user_id": "user-1", "conversation_id": "c1", "message_count": 1,
    })


@pytest.mark.asyncio
async def test_read_conversation_rejects_missing_conversation_id(endpoint_env):
    with patch.object(history_sql, "get_conversation_messages", AsyncMock()) as get_msgs:
        with pytest.raises(HTTPException) as exc:
            await history_sql.get_conversation_messages_endpoint(make_request(), id="")

    assert exc.value.status_code == 400
    assert exc.value.detail == "conversation_id is required"
    get_msgs.assert_not_awaited()
    assert event_names(endpoint_env.track) == ["ReadConversationValidationError"]


@pytest.mark.asyncio
async def test_read_conversation_skips_validation_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with pytest.raises(HTTPException) as exc:
        await history_sql.get_conversation_messages_endpoint(make_request(), id="")

    assert exc.value.status_code == 400
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_read_conversation_returns_404_when_no_messages(endpoint_env):
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(return_value=[])):
        with pytest.raises(HTTPException) as exc:
            await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert exc.value.status_code == 404
    assert "Conversation c1 was not found" in exc.value.detail
    assert event_names(endpoint_env.track) == ["ReadConversationNotFound"]


@pytest.mark.asyncio
async def test_read_conversation_returns_404_when_messages_is_none(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert exc.value.status_code == 404
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_read_conversation_skips_success_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(return_value=[{"role": "user"}])):
        response = await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert response.status_code == 200
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_read_conversation_returns_500_on_unexpected_error(endpoint_env):
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    payload = endpoint_env.track.call_args.args[1]
    assert payload["conversation_id"] == "c1"
    assert payload["error_type"] == "RuntimeError"
    endpoint_env.span.set_status.assert_called_once()


@pytest.mark.asyncio
async def test_read_conversation_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    with patch.object(history_sql, "get_conversation_messages", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.get_conversation_messages_endpoint(make_request(), id="c1")

    assert response.status_code == 500
    endpoint_env.span.record_exception.assert_not_called()


# --------------------------------------------------------------------------- #
# DELETE /delete
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_returns_success(endpoint_env):
    with patch.object(history_sql, "delete_conversation", AsyncMock(return_value=True)) as delete:
        response = await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert response.status_code == 200
    assert body_of(response) == {
        "message": "Successfully deleted conversation and messages",
        "conversation_id": "c1",
    }
    delete.assert_awaited_once_with("user-1", "c1")
    endpoint_env.track.assert_called_once_with("ConversationDeleted", {
        "user_id": "user-1", "conversation_id": "c1",
    })


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_rejects_missing_id(endpoint_env):
    with patch.object(history_sql, "delete_conversation", AsyncMock()) as delete:
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_conversation_endpoint(make_request(), id="")

    assert exc.value.status_code == 400
    assert exc.value.detail == "conversation_id is required"
    delete.assert_not_awaited()
    assert event_names(endpoint_env.track) == ["DeleteConversationValidationError"]


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_returns_404_when_not_deleted(endpoint_env):
    with patch.object(history_sql, "delete_conversation", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert exc.value.status_code == 404
    assert "not found or user does not have permission" in exc.value.detail
    assert event_names(endpoint_env.track) == ["DeleteConversationNotFound"]


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_skips_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "delete_conversation", AsyncMock(return_value=True)):
        response = await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert response.status_code == 200
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_skips_not_found_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "delete_conversation", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert exc.value.status_code == 404
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_returns_500_on_unexpected_error(endpoint_env):
    with patch.object(history_sql, "delete_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    assert event_names(endpoint_env.track) == ["DeleteConversationError"]
    endpoint_env.span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_delete_conversation_endpoint_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    with patch.object(history_sql, "delete_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.delete_conversation_endpoint(make_request(), id="c1")

    assert response.status_code == 500
    endpoint_env.span.set_status.assert_not_called()


# --------------------------------------------------------------------------- #
# DELETE /delete_all
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_returns_success(endpoint_env):
    conversations = [{"conversation_id": "c1"}, {"conversation_id": "c2"}]
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=conversations)) as get_convs, \
            patch.object(history_sql, "delete_all_conversations", AsyncMock(return_value=True)) as delete_all:
        response = await history_sql.delete_all_conversations_endpoint(make_request())

    assert response.status_code == 200
    assert body_of(response) == {"message": "Successfully deleted all conversations for user user-1"}
    get_convs.assert_awaited_once_with("user-1", offset=0, limit=None)
    delete_all.assert_awaited_once_with("user-1")
    endpoint_env.track.assert_called_once_with("AllConversationsDeleted", {
        "user_id": "user-1", "deleted_count": 2,
    })


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_returns_404_when_nothing_to_delete(endpoint_env):
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=[])), \
            patch.object(history_sql, "delete_all_conversations", AsyncMock()) as delete_all:
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_all_conversations_endpoint(make_request())

    assert exc.value.status_code == 404
    assert exc.value.detail == "No conversations for user-1 were found"
    delete_all.assert_not_awaited()
    assert event_names(endpoint_env.track) == ["DeleteAllConversationsNotFound"]


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_returns_404_when_delete_fails(endpoint_env):
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=[{"conversation_id": "c1"}])), \
            patch.object(history_sql, "delete_all_conversations", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_all_conversations_endpoint(make_request())

    assert exc.value.status_code == 404
    assert exc.value.detail == "Conversation not found for user user-1"
    assert event_names(endpoint_env.track) == ["DeleteAllConversationsNotFound"]


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_skips_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=[{"conversation_id": "c1"}])), \
            patch.object(history_sql, "delete_all_conversations", AsyncMock(return_value=True)):
        response = await history_sql.delete_all_conversations_endpoint(make_request())

    assert response.status_code == 200
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_skips_failure_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with patch.object(history_sql, "get_conversations", AsyncMock(return_value=[{"conversation_id": "c1"}])), \
            patch.object(history_sql, "delete_all_conversations", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.delete_all_conversations_endpoint(make_request())

    assert exc.value.status_code == 404
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_returns_500_on_unexpected_error(endpoint_env):
    with patch.object(history_sql, "get_conversations", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.delete_all_conversations_endpoint(make_request())

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    assert event_names(endpoint_env.track) == ["DeleteAllConversationsError"]
    endpoint_env.span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_delete_all_conversations_endpoint_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    with patch.object(history_sql, "get_conversations", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.delete_all_conversations_endpoint(make_request())

    assert response.status_code == 500
    endpoint_env.span.set_status.assert_not_called()


# --------------------------------------------------------------------------- #
# POST /rename
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_returns_success(endpoint_env):
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(return_value=True)) as rename:
        response = await history_sql.rename_conversation_endpoint(request)

    assert response.status_code == 200
    assert body_of(response) == {
        "message": "Successfully renamed title of conversation c1 to title 'New title'"
    }
    rename.assert_awaited_once_with("user-1", "c1", "New title")
    endpoint_env.track.assert_called_once_with("ConversationRenamedTitle", {
        "user_id": "user-1", "conversation_id": "c1", "new_title": "New title",
    })


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_rejects_missing_conversation_id(endpoint_env):
    request = make_request({"title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock()) as rename:
        with pytest.raises(HTTPException) as exc:
            await history_sql.rename_conversation_endpoint(request)

    assert exc.value.status_code == 400
    assert exc.value.detail == "conversation_id is required"
    rename.assert_not_awaited()
    assert endpoint_env.track.call_args.args[1]["error"] == "conversation_id is required"


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_rejects_missing_title(endpoint_env):
    request = make_request({"conversation_id": "c1"})
    with patch.object(history_sql, "rename_conversation", AsyncMock()) as rename:
        with pytest.raises(HTTPException) as exc:
            await history_sql.rename_conversation_endpoint(request)

    assert exc.value.status_code == 400
    assert exc.value.detail == "title is required"
    rename.assert_not_awaited()
    assert endpoint_env.track.call_args.args[1]["error"] == "title is required"


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_skips_validation_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    with pytest.raises(HTTPException):
        await history_sql.rename_conversation_endpoint(make_request({"title": "New title"}))
    with pytest.raises(HTTPException):
        await history_sql.rename_conversation_endpoint(make_request({"conversation_id": "c1"}))

    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_returns_404_when_rename_fails(endpoint_env):
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.rename_conversation_endpoint(request)

    assert exc.value.status_code == 404
    assert "not found or user does not have permission to rename" in exc.value.detail
    assert event_names(endpoint_env.track) == ["ConversationRenamedTitleNotFound"]


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_skips_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(return_value=True)):
        response = await history_sql.rename_conversation_endpoint(request)

    assert response.status_code == 200
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_skips_not_found_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.rename_conversation_endpoint(request)

    assert exc.value.status_code == 404
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_returns_500_on_unexpected_error(endpoint_env):
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.rename_conversation_endpoint(request)

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    payload = endpoint_env.track.call_args.args[1]
    assert payload["conversation_id"] == "c1"
    assert payload["error_type"] == "RuntimeError"
    endpoint_env.span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_rename_conversation_endpoint_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    request = make_request({"conversation_id": "c1", "title": "New title"})
    with patch.object(history_sql, "rename_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.rename_conversation_endpoint(request)

    assert response.status_code == 500
    endpoint_env.span.set_status.assert_not_called()


# --------------------------------------------------------------------------- #
# POST /update
# --------------------------------------------------------------------------- #


UPDATE_BODY = {
    "conversation_id": "c1",
    "messages": [
        {"role": "user", "content": "hi", "id": "m1"},
        {"role": "assistant", "content": "hello", "id": "m2"},
    ],
}
UPDATE_RESULT = {"id": "c1", "title": "Overdue Invoices", "updatedAt": "2024-05-06T07:08:09"}


@pytest.mark.asyncio
async def test_update_conversation_endpoint_returns_updated_conversation(endpoint_env):
    request = make_request(UPDATE_BODY)
    with patch.object(history_sql, "update_conversation", AsyncMock(return_value=UPDATE_RESULT)) as update:
        response = await history_sql.update_conversation_endpoint(request)

    assert response.status_code == 200
    assert body_of(response) == {
        "success": True,
        "data": {
            "title": "Overdue Invoices",
            "date": "2024-05-06T07:08:09",
            "conversation_id": "c1",
        },
    }
    update.assert_awaited_once_with("user-1", UPDATE_BODY)
    endpoint_env.track.assert_called_once_with("ConversationUpdated", {
        "user_id": "user-1", "conversation_id": "c1", "title": "Overdue Invoices",
    })


@pytest.mark.asyncio
async def test_update_conversation_endpoint_rejects_missing_conversation_id(endpoint_env):
    request = make_request({"messages": []})
    with patch.object(history_sql, "update_conversation", AsyncMock()) as update:
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation_endpoint(request)

    assert exc.value.status_code == 400
    assert exc.value.detail == "No conversation_id found"
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_conversation_endpoint_returns_500_when_update_returns_nothing(endpoint_env):
    request = make_request(UPDATE_BODY)
    with patch.object(history_sql, "update_conversation", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await history_sql.update_conversation_endpoint(request)

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to update conversation"
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_update_conversation_endpoint_skips_telemetry_for_anonymous_user(endpoint_env):
    endpoint_env.auth.return_value = dict(ANON)
    request = make_request(UPDATE_BODY)
    with patch.object(history_sql, "update_conversation", AsyncMock(return_value=UPDATE_RESULT)):
        response = await history_sql.update_conversation_endpoint(request)

    assert response.status_code == 200
    endpoint_env.track.assert_not_called()


@pytest.mark.asyncio
async def test_update_conversation_endpoint_returns_500_on_unexpected_error(endpoint_env):
    request = make_request(UPDATE_BODY)
    with patch.object(history_sql, "update_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.update_conversation_endpoint(request)

    assert response.status_code == 500
    assert body_of(response) == {"error": "An internal error has occurred!"}
    payload = endpoint_env.track.call_args.args[1]
    assert payload["conversation_id"] == "c1"
    assert payload["error_type"] == "RuntimeError"
    endpoint_env.span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_update_conversation_endpoint_handles_missing_span(endpoint_env):
    endpoint_env.trace.get_current_span.return_value = None
    request = make_request(UPDATE_BODY)
    with patch.object(history_sql, "update_conversation", AsyncMock(side_effect=RuntimeError("db down"))):
        response = await history_sql.update_conversation_endpoint(request)

    assert response.status_code == 500
    endpoint_env.span.set_status.assert_not_called()


# --------------------------------------------------------------------------- #
# Module configuration
# --------------------------------------------------------------------------- #


def test_router_exposes_expected_history_routes():
    routes = {(route.path, tuple(sorted(route.methods))) for route in history_sql.router.routes}

    assert ("/list", ("GET",)) in routes
    assert ("/read", ("GET",)) in routes
    assert ("/delete", ("DELETE",)) in routes
    assert ("/delete_all", ("DELETE",)) in routes
    assert ("/rename", ("POST",)) in routes
    assert ("/update", ("POST",)) in routes


def test_use_chat_history_enabled_defaults_to_true():
    assert history_sql.USE_CHAT_HISTORY_ENABLED is True
