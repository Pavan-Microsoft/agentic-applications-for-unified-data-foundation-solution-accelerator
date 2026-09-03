"""Unit tests for src/api/python/history.py.

Every external dependency (CosmosDB clients, Azure credentials, the AI Foundry
``AIProjectClient``, Application Insights telemetry, OpenTelemetry spans,
FastAPI request objects and environment variables) is mocked; no network,
Azure or database calls are made.
"""

import json
import os
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError
from azure.cosmos import exceptions

import history


USER = {"user_principal_id": "user-1"}
FIXED_TIME = "2024-05-06T07:08:09"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class AsyncIterator:
    """Async-iterable stand-in for ``container_client.query_items``."""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._iterator = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeAsyncCM:
    """Minimal async context manager returning a fixed value."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class OutputItem:
    """Stand-in for an AI Foundry response output item (real attributes)."""

    def __init__(self, item_type, content=None):
        self.type = item_type
        self.content = content


class TextPart:
    """Content part exposing a ``text`` attribute."""

    def __init__(self, text):
        self.text = text


class OpaquePart:
    """Content part deliberately missing a ``text`` attribute."""


def make_client(enable_message_feedback=False):
    """Build a CosmosConversationClient wired to MagicMock Cosmos objects."""
    with patch.object(history, "CosmosClient") as cosmos_cls:
        cosmos = MagicMock()
        cosmos_cls.return_value = cosmos
        client = history.CosmosConversationClient(
            cosmosdb_endpoint="https://acct.documents.azure.com:443/",
            credential=MagicMock(),
            database_name="db",
            container_name="conversations",
            enable_message_feedback=enable_message_feedback,
        )
    client.cosmosdb_client.close = AsyncMock()
    return client


def make_request(body=None, headers=None):
    """Build a FastAPI-Request-like double with an awaitable ``json()``."""
    request = MagicMock()
    request.headers = headers if headers is not None else {"x-ms-client-principal-id": "user-1"}
    request.json = AsyncMock(return_value={} if body is None else body)
    return request


def event_names(tracker):
    """Collect the event names passed to a patched track_event_if_configured."""
    return [call.args[0] for call in tracker.call_args_list]


# --------------------------------------------------------------------------- #
# track_event_if_configured
# --------------------------------------------------------------------------- #


def test_track_event_if_configured_forwards_event_when_connection_string_present():
    with patch.dict(os.environ, {"APPLICATIONINSIGHTS_CONNECTION_STRING": "conn-str"}), \
            patch.object(history, "track_event") as track:
        history.track_event_if_configured("SomeEvent", {"user_id": "user-1"})

    track.assert_called_once_with("SomeEvent", {"user_id": "user-1"})


def test_track_event_if_configured_skips_and_warns_when_not_configured():
    with patch.dict(os.environ, {}, clear=True), \
            patch.object(history, "track_event") as track, \
            patch.object(history.logging, "warning") as warning:
        history.track_event_if_configured("SomeEvent", {"user_id": "user-1"})

    track.assert_not_called()
    warning.assert_called_once()
    assert warning.call_args.args[1] == "SomeEvent"


# --------------------------------------------------------------------------- #
# CosmosConversationClient.__init__
# --------------------------------------------------------------------------- #


def test_client_init_wires_database_and_container_clients():
    credential = MagicMock()
    with patch.object(history, "CosmosClient") as cosmos_cls:
        cosmos = MagicMock()
        cosmos_cls.return_value = cosmos
        database = cosmos.get_database_client.return_value
        container = database.get_container_client.return_value
        client = history.CosmosConversationClient(
            cosmosdb_endpoint="https://acct.documents.azure.com:443/",
            credential=credential,
            database_name="db",
            container_name="conversations",
            enable_message_feedback=True,
        )

    cosmos_cls.assert_called_once_with(
        "https://acct.documents.azure.com:443/", credential=credential
    )
    cosmos.get_database_client.assert_called_once_with("db")
    database.get_container_client.assert_called_once_with("conversations")
    assert client.cosmosdb_client is cosmos
    assert client.database_client is database
    assert client.container_client is container
    assert client.cosmosdb_endpoint == "https://acct.documents.azure.com:443/"
    assert client.database_name == "db"
    assert client.container_name == "conversations"
    assert client.enable_message_feedback is True


def test_client_init_raises_invalid_credentials_for_401():
    error = exceptions.CosmosHttpResponseError(status_code=401, message="unauthorized")
    with patch.object(history, "CosmosClient", side_effect=error):
        with pytest.raises(ValueError) as excinfo:
            history.CosmosConversationClient(
                "https://acct/", MagicMock(), "db", "conversations"
            )

    assert str(excinfo.value) == "Invalid credentials"
    assert excinfo.value.__cause__ is error


def test_client_init_raises_invalid_endpoint_for_non_401_status():
    error = exceptions.CosmosHttpResponseError(status_code=503, message="unavailable")
    with patch.object(history, "CosmosClient", side_effect=error):
        with pytest.raises(ValueError) as excinfo:
            history.CosmosConversationClient(
                "https://acct/", MagicMock(), "db", "conversations"
            )

    assert str(excinfo.value) == "Invalid CosmosDB endpoint"
    assert excinfo.value.__cause__ is error


def test_client_init_raises_invalid_database_name_when_database_missing():
    with patch.object(history, "CosmosClient") as cosmos_cls:
        cosmos_cls.return_value.get_database_client.side_effect = (
            exceptions.CosmosResourceNotFoundError(message="no database")
        )
        with pytest.raises(ValueError) as excinfo:
            history.CosmosConversationClient(
                "https://acct/", MagicMock(), "missing-db", "conversations"
            )

    assert str(excinfo.value) == "Invalid CosmosDB database name"


def test_client_init_raises_invalid_container_name_when_container_missing():
    with patch.object(history, "CosmosClient") as cosmos_cls:
        database = cosmos_cls.return_value.get_database_client.return_value
        database.get_container_client.side_effect = (
            exceptions.CosmosResourceNotFoundError(message="no container")
        )
        with pytest.raises(ValueError) as excinfo:
            history.CosmosConversationClient(
                "https://acct/", MagicMock(), "db", "missing-container"
            )

    assert str(excinfo.value) == "Invalid CosmosDB container name"


# --------------------------------------------------------------------------- #
# CosmosConversationClient.ensure
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_attribute", ["cosmosdb_client", "database_client", "container_client"])
async def test_ensure_reports_uninitialized_client_without_reading(missing_attribute):
    client = make_client()
    client.database_client.read = AsyncMock()
    setattr(client, missing_attribute, None)

    success, message = await client.ensure()

    assert success is False
    assert message == "CosmosDB client not initialized correctly"
    if missing_attribute != "database_client":
        client.database_client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_reports_missing_database():
    client = make_client()
    client.database_client.read = AsyncMock(side_effect=Exception("db gone"))
    client.container_client.read = AsyncMock()

    success, message = await client.ensure()

    assert success is False
    assert message == (
        "CosmosDB database db on account https://acct.documents.azure.com:443/ not found"
    )
    client.container_client.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_reports_missing_container():
    client = make_client()
    client.database_client.read = AsyncMock()
    client.container_client.read = AsyncMock(side_effect=Exception("container gone"))

    success, message = await client.ensure()

    assert success is False
    assert message == "CosmosDB container conversations not found"


@pytest.mark.asyncio
async def test_ensure_succeeds_when_database_and_container_readable():
    client = make_client()
    client.database_client.read = AsyncMock()
    client.container_client.read = AsyncMock()

    success, message = await client.ensure()

    assert success is True
    assert message == "CosmosDB client initialized successfully"
    client.database_client.read.assert_awaited_once()
    client.container_client.read.assert_awaited_once()


# --------------------------------------------------------------------------- #
# CosmosConversationClient.create_conversation / upsert_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_conversation_builds_document_and_returns_upsert_response():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value={"id": "conv-1"})

    with patch.object(history, "datetime") as fake_datetime:
        fake_datetime.utcnow.return_value.isoformat.return_value = FIXED_TIME
        result = await client.create_conversation("user-1", conversation_id="conv-1", title="A Title")

    assert result == {"id": "conv-1"}
    document = client.container_client.upsert_item.await_args.args[0]
    assert document == {
        "id": "conv-1",
        "type": "conversation",
        "createdAt": FIXED_TIME,
        "updatedAt": FIXED_TIME,
        "userId": "user-1",
        "title": "A Title",
        "conversation_id": "conv-1",
    }


@pytest.mark.asyncio
async def test_create_conversation_returns_false_when_upsert_returns_falsy():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value=None)

    assert await client.create_conversation("user-1", "conv-1", "T") is False


@pytest.mark.asyncio
async def test_upsert_conversation_returns_response_or_false():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value={"id": "conv-1"})
    assert await client.upsert_conversation({"id": "conv-1"}) == {"id": "conv-1"}
    client.container_client.upsert_item.assert_awaited_once_with({"id": "conv-1"})

    client.container_client.upsert_item = AsyncMock(return_value={})
    assert await client.upsert_conversation({"id": "conv-1"}) is False


# --------------------------------------------------------------------------- #
# CosmosConversationClient.delete_conversation / delete_messages
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_conversation_deletes_existing_item():
    client = make_client()
    client.container_client.read_item = AsyncMock(return_value={"id": "conv-1"})
    client.container_client.delete_item = AsyncMock(return_value={"deleted": True})

    result = await client.delete_conversation("user-1", "conv-1")

    assert result == {"deleted": True}
    client.container_client.read_item.assert_awaited_once_with(
        item="conv-1", partition_key="user-1"
    )
    client.container_client.delete_item.assert_awaited_once_with(
        item="conv-1", partition_key="user-1"
    )


@pytest.mark.asyncio
async def test_delete_conversation_returns_true_without_deleting_when_absent():
    client = make_client()
    client.container_client.read_item = AsyncMock(return_value=None)
    client.container_client.delete_item = AsyncMock()

    assert await client.delete_conversation("user-1", "conv-1") is True
    client.container_client.delete_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_messages_deletes_every_message_and_returns_responses():
    client = make_client()
    client.get_messages = AsyncMock(return_value=[{"id": "m1"}, {"id": "m2"}])
    client.container_client.delete_item = AsyncMock(side_effect=["r1", "r2"])

    result = await client.delete_messages("conv-1", "user-1")

    assert result == ["r1", "r2"]
    client.get_messages.assert_awaited_once_with("user-1", "conv-1")
    assert [call.kwargs for call in client.container_client.delete_item.await_args_list] == [
        {"item": "m1", "partition_key": "user-1"},
        {"item": "m2", "partition_key": "user-1"},
    ]


@pytest.mark.asyncio
async def test_delete_messages_returns_empty_list_when_no_messages():
    client = make_client()
    client.get_messages = AsyncMock(return_value=[])
    client.container_client.delete_item = AsyncMock()

    assert await client.delete_messages("conv-1", "user-1") == []
    client.container_client.delete_item.assert_not_awaited()


# --------------------------------------------------------------------------- #
# CosmosConversationClient query helpers
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_conversations_applies_pagination_and_sort_order():
    client = make_client()
    client.container_client.query_items = MagicMock(
        return_value=AsyncIterator([{"id": "c1"}, {"id": "c2"}])
    )

    result = await client.get_conversations("user-1", limit=5, sort_order="ASC", offset=10)

    assert result == [{"id": "c1"}, {"id": "c2"}]
    kwargs = client.container_client.query_items.call_args.kwargs
    assert kwargs["parameters"] == [{"name": "@userId", "value": "user-1"}]
    assert "order by c.updatedAt ASC" in kwargs["query"]
    assert kwargs["query"].endswith(" offset 10 limit 5")


@pytest.mark.asyncio
async def test_get_conversations_omits_pagination_when_limit_is_none():
    client = make_client()
    client.container_client.query_items = MagicMock(return_value=AsyncIterator([]))

    result = await client.get_conversations("user-1", limit=None)

    assert result == []
    query = client.container_client.query_items.call_args.kwargs["query"]
    assert "offset" not in query
    assert "limit" not in query
    assert query.endswith("order by c.updatedAt DESC")


@pytest.mark.asyncio
async def test_get_conversation_returns_first_match():
    client = make_client()
    client.container_client.query_items = MagicMock(
        return_value=AsyncIterator([{"id": "conv-1"}, {"id": "conv-2"}])
    )

    result = await client.get_conversation("user-1", "conv-1")

    assert result == {"id": "conv-1"}
    kwargs = client.container_client.query_items.call_args.kwargs
    assert kwargs["parameters"] == [
        {"name": "@conversationId", "value": "conv-1"},
        {"name": "@userId", "value": "user-1"},
    ]
    assert "c.type='conversation'" in kwargs["query"]


@pytest.mark.asyncio
async def test_get_conversation_returns_none_when_no_match():
    client = make_client()
    client.container_client.query_items = MagicMock(return_value=AsyncIterator([]))

    assert await client.get_conversation("user-1", "conv-1") is None


@pytest.mark.asyncio
async def test_get_messages_returns_all_items_for_conversation():
    client = make_client()
    client.container_client.query_items = MagicMock(
        return_value=AsyncIterator([{"id": "m1"}, {"id": "m2"}])
    )

    result = await client.get_messages("user-1", "conv-1")

    assert result == [{"id": "m1"}, {"id": "m2"}]
    kwargs = client.container_client.query_items.call_args.kwargs
    assert kwargs["parameters"] == [
        {"name": "@conversationId", "value": "conv-1"},
        {"name": "@userId", "value": "user-1"},
    ]
    assert "c.type='message'" in kwargs["query"]


# --------------------------------------------------------------------------- #
# CosmosConversationClient.create_message / update_message_feedback
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_message_persists_message_and_touches_parent_conversation():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value={"id": "msg-1"})
    client.get_conversation = AsyncMock(
        return_value={"id": "conv-1", "updatedAt": "2000-01-01T00:00:00"}
    )
    client.upsert_conversation = AsyncMock(return_value={"id": "conv-1"})

    with patch.object(history, "datetime") as fake_datetime:
        fake_datetime.utcnow.return_value.isoformat.return_value = FIXED_TIME
        result = await client.create_message(
            "msg-1", "conv-1", "user-1", {"role": "user", "content": "hello"}
        )

    assert result == {"id": "msg-1"}
    document = client.container_client.upsert_item.await_args.args[0]
    assert document == {
        "id": "msg-1",
        "type": "message",
        "userId": "user-1",
        "createdAt": FIXED_TIME,
        "updatedAt": FIXED_TIME,
        "conversationId": "conv-1",
        "role": "user",
        "content": {"role": "user", "content": "hello"},
    }
    assert "feedback" not in document
    client.upsert_conversation.assert_awaited_once_with(
        {"id": "conv-1", "updatedAt": FIXED_TIME}
    )


@pytest.mark.asyncio
async def test_create_message_adds_empty_feedback_when_feedback_enabled():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value={"id": "msg-1"})
    client.get_conversation = AsyncMock(return_value={"id": "conv-1"})
    client.upsert_conversation = AsyncMock()

    with patch.object(history, "AZURE_COSMOSDB_ENABLE_FEEDBACK", True):
        await client.create_message("msg-1", "conv-1", "user-1", {"role": "user"})

    document = client.container_client.upsert_item.await_args.args[0]
    assert document["feedback"] == ""


@pytest.mark.asyncio
async def test_create_message_returns_sentinel_when_conversation_missing():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value={"id": "msg-1"})
    client.get_conversation = AsyncMock(return_value=None)
    client.upsert_conversation = AsyncMock()

    result = await client.create_message("msg-1", "conv-1", "user-1", {"role": "user"})

    assert result == "Conversation not found"
    client.upsert_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_message_returns_false_when_upsert_returns_falsy():
    client = make_client()
    client.container_client.upsert_item = AsyncMock(return_value=None)
    client.get_conversation = AsyncMock()

    result = await client.create_message("msg-1", "conv-1", "user-1", {"role": "user"})

    assert result is False
    client.get_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_message_feedback_writes_feedback_to_existing_message():
    client = make_client()
    client.container_client.read_item = AsyncMock(return_value={"id": "msg-1"})
    client.container_client.upsert_item = AsyncMock(return_value={"id": "msg-1", "feedback": "positive"})

    result = await client.update_message_feedback("user-1", "msg-1", "positive")

    assert result == {"id": "msg-1", "feedback": "positive"}
    client.container_client.read_item.assert_awaited_once_with(
        item="msg-1", partition_key="user-1"
    )
    client.container_client.upsert_item.assert_awaited_once_with(
        {"id": "msg-1", "feedback": "positive"}
    )


@pytest.mark.asyncio
async def test_update_message_feedback_returns_false_when_message_missing():
    client = make_client()
    client.container_client.read_item = AsyncMock(return_value=None)
    client.container_client.upsert_item = AsyncMock()

    assert await client.update_message_feedback("user-1", "msg-1", "positive") is False
    client.container_client.upsert_item.assert_not_awaited()


# --------------------------------------------------------------------------- #
# init_cosmosdb_client
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_init_cosmosdb_client_returns_none_when_history_disabled():
    with patch.object(history, "CHAT_HISTORY_ENABLED", False), \
            patch.object(history, "CosmosConversationClient") as ctor:
        assert await history.init_cosmosdb_client() is None

    ctor.assert_not_called()


@pytest.mark.asyncio
async def test_init_cosmosdb_client_builds_client_with_account_endpoint():
    credential = MagicMock()
    with patch.object(history, "CHAT_HISTORY_ENABLED", True), \
            patch.object(history, "AZURE_COSMOSDB_ACCOUNT", "my-account"), \
            patch.object(history, "AZURE_COSMOSDB_DATABASE", "my-db"), \
            patch.object(history, "AZURE_COSMOSDB_CONVERSATIONS_CONTAINER", "my-container"), \
            patch.object(history, "AZURE_COSMOSDB_ENABLE_FEEDBACK", True), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "CosmosConversationClient") as ctor:
        result = await history.init_cosmosdb_client()

    assert result is ctor.return_value
    ctor.assert_called_once_with(
        cosmosdb_endpoint="https://my-account.documents.azure.com:443/",
        credential=credential,
        database_name="my-db",
        container_name="my-container",
        enable_message_feedback=True,
    )


@pytest.mark.asyncio
async def test_init_cosmosdb_client_propagates_credential_failure():
    with patch.object(history, "CHAT_HISTORY_ENABLED", True), \
            patch.object(history, "get_azure_credential_async", AsyncMock(side_effect=RuntimeError("no creds"))):
        with pytest.raises(RuntimeError, match="no creds"):
            await history.init_cosmosdb_client()


# --------------------------------------------------------------------------- #
# generate_fallback_title
# --------------------------------------------------------------------------- #


def test_generate_fallback_title_uses_first_four_words_of_first_user_message():
    messages = [
        {"role": "assistant", "content": "ignored assistant reply"},
        {"role": "user", "content": "please summarize the quarterly revenue report"},
        {"role": "user", "content": "second question"},
    ]

    assert history.generate_fallback_title(messages) == "please summarize the quarterly"


def test_generate_fallback_title_keeps_short_messages_intact():
    assert history.generate_fallback_title([{"role": "user", "content": "hi there"}]) == "hi there"


def test_generate_fallback_title_stringifies_dict_content():
    title = history.generate_fallback_title(
        [{"role": "user", "content": {"text": "hello world again please"}}]
    )

    assert title == "{'text': 'hello world again"


def test_generate_fallback_title_defaults_when_no_user_messages():
    assert history.generate_fallback_title([{"role": "assistant", "content": "hi"}]) == "New Conversation"
    assert history.generate_fallback_title([]) == "New Conversation"


def test_generate_fallback_title_defaults_for_empty_content():
    assert history.generate_fallback_title([{"role": "user", "content": ""}]) == "New Conversation"


def test_generate_fallback_title_defaults_for_whitespace_only_content():
    assert history.generate_fallback_title([{"role": "user", "content": "   \t  "}]) == "New Conversation"


# --------------------------------------------------------------------------- #
# generate_title
# --------------------------------------------------------------------------- #


def make_foundry_stack(output, conversation_id="conv-created"):
    """Build (credential, openai_client, patched AIProjectClient) doubles."""
    credential = MagicMock()
    credential.close = AsyncMock()

    openai_client = MagicMock()
    openai_client.conversations.create = AsyncMock(return_value=MagicMock(id=conversation_id))
    openai_client.responses.create = AsyncMock(return_value=MagicMock(output=output))

    project_client = MagicMock()
    project_client.get_openai_client = MagicMock(return_value=openai_client)
    return credential, openai_client, project_client


@pytest.mark.asyncio
async def test_generate_title_returns_agent_text_and_closes_credential():
    output = [
        OutputItem("reasoning", [TextPart("ignored")]),
        OutputItem("message", [TextPart("Quarterly "), TextPart("Revenue Report \n"), OpaquePart()]),
        OutputItem("message", None),
    ]
    credential, openai_client, project_client = make_foundry_stack(output)

    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "AIProjectClient", return_value=FakeAsyncCM(project_client)) as ctor:
        title = await history.generate_title(
            [{"role": "user", "content": "revenue please"}, {"role": "assistant", "content": "sure"}]
        )

    assert title == "Quarterly Revenue Report"
    ctor.assert_called_once_with(endpoint="https://endpoint/", credential=credential)
    credential.close.assert_awaited_once()
    openai_client.conversations.create.assert_awaited_once()
    kwargs = openai_client.responses.create.await_args.kwargs
    assert kwargs["conversation"] == "conv-created"
    assert kwargs["input"] == (
        "Generate a 4-word or less title for this request:\nrevenue please"
    )
    assert kwargs["extra_body"] == {
        "agent_reference": {"name": "TitleAgent", "type": "agent_reference"}
    }


@pytest.mark.asyncio
async def test_generate_title_joins_all_user_messages_into_prompt():
    credential, openai_client, project_client = make_foundry_stack([OutputItem("message", [TextPart("T")])])

    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "AIProjectClient", return_value=FakeAsyncCM(project_client)):
        await history.generate_title(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "skip me"},
                {"role": "user", "content": "second"},
            ]
        )

    assert openai_client.responses.create.await_args.kwargs["input"].endswith("first\nsecond")


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_agent_returns_no_text():
    credential, _, project_client = make_foundry_stack([OutputItem("reasoning", [TextPart("x")])])

    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "AIProjectClient", return_value=FakeAsyncCM(project_client)):
        title = await history.generate_title([{"role": "user", "content": "some question here now"}])

    assert title == "some question here now"
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_no_user_messages():
    with patch.object(history, "AIProjectClient") as ctor, \
            patch.object(history, "get_azure_credential_async", AsyncMock()) as credential_factory:
        title = await history.generate_title([{"role": "assistant", "content": "hello"}])

    assert title == "New Conversation"
    ctor.assert_not_called()
    credential_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_agent_endpoint_not_configured():
    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", None), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "AIProjectClient") as ctor, \
            patch.object(history, "get_azure_credential_async", AsyncMock()) as credential_factory:
        title = await history.generate_title([{"role": "user", "content": "budget forecast for teams"}])

    assert title == "budget forecast for teams"
    ctor.assert_not_called()
    credential_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_agent_name_not_configured():
    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", None), \
            patch.object(history, "AIProjectClient") as ctor, \
            patch.object(history, "get_azure_credential_async", AsyncMock()) as credential_factory:
        title = await history.generate_title([{"role": "user", "content": "budget forecast for teams"}])

    assert title == "budget forecast for teams"
    ctor.assert_not_called()
    credential_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_http_response_error():
    credential = MagicMock()
    credential.close = AsyncMock()

    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "AIProjectClient", side_effect=HttpResponseError(message="service down")):
        title = await history.generate_title([{"role": "user", "content": "annual report summary please"}])

    assert title == "annual report summary please"
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_title_falls_back_on_unexpected_error():
    credential = MagicMock()
    credential.close = AsyncMock()
    project_client = MagicMock()
    project_client.get_openai_client.side_effect = RuntimeError("boom")

    with patch.object(history, "AZURE_AI_AGENT_ENDPOINT", "https://endpoint/"), \
            patch.object(history, "AGENT_NAME_TITLE", "TitleAgent"), \
            patch.object(history, "get_azure_credential_async", AsyncMock(return_value=credential)), \
            patch.object(history, "AIProjectClient", return_value=FakeAsyncCM(project_client)):
        title = await history.generate_title([{"role": "user", "content": "annual report summary please"}])

    assert title == "annual report summary please"
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_title_propagates_key_error_when_messages_lack_role():
    # The except-handler delegates to generate_fallback_title, which re-reads "role".
    with pytest.raises(KeyError, match="role"):
        await history.generate_title([{"content": "no role key"}])


# --------------------------------------------------------------------------- #
# add_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_add_conversation_creates_conversation_and_message_when_id_absent():
    client = MagicMock()
    client.create_conversation = AsyncMock(
        return_value={"id": "conv-new", "createdAt": FIXED_TIME}
    )
    client.create_message = AsyncMock(return_value={"id": "msg-1"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)), \
            patch.object(history, "generate_title", AsyncMock(return_value="Generated Title")):
        result = await history.add_conversation(
            "user-1", {"messages": [{"role": "user", "content": "hi"}]}
        )

    assert result is True
    client.create_conversation.assert_awaited_once_with("user-1", "Generated Title")
    assert client.create_message.await_args.args[1:] == (
        "conv-new",
        "user-1",
        {"role": "user", "content": "hi"},
    )


@pytest.mark.asyncio
async def test_add_conversation_skips_creation_when_conversation_id_supplied():
    client = MagicMock()
    client.create_conversation = AsyncMock()
    client.create_message = AsyncMock(return_value={"id": "msg-1"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)), \
            patch.object(history, "generate_title", AsyncMock()) as title_generator:
        result = await history.add_conversation(
            "user-1",
            {"conversation_id": "conv-9", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert result is True
    client.create_conversation.assert_not_awaited()
    title_generator.assert_not_awaited()
    assert client.create_message.await_args.args[1] == "conv-9"


@pytest.mark.asyncio
async def test_add_conversation_raises_when_cosmos_not_configured():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="CosmosDB is not configured or unavailable"):
            await history.add_conversation(
                "user-1", {"messages": [{"role": "user", "content": "hi"}]}
            )


@pytest.mark.asyncio
async def test_add_conversation_raises_when_last_message_is_not_from_user():
    client = MagicMock()
    client.create_message = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(ValueError, match="No user message found"):
            await history.add_conversation(
                "user-1",
                {"conversation_id": "conv-9", "messages": [{"role": "assistant", "content": "hi"}]},
            )

    client.create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_conversation_raises_when_messages_empty():
    client = MagicMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(ValueError, match="No user message found"):
            await history.add_conversation("user-1", {"conversation_id": "conv-9"})


@pytest.mark.asyncio
async def test_add_conversation_raises_when_message_creation_reports_missing_conversation():
    client = MagicMock()
    client.create_message = AsyncMock(return_value="Conversation not found")

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(ValueError, match="Conversation not found for ID: conv-9"):
            await history.add_conversation(
                "user-1",
                {"conversation_id": "conv-9", "messages": [{"role": "user", "content": "hi"}]},
            )


# --------------------------------------------------------------------------- #
# update_conversation
# --------------------------------------------------------------------------- #


def make_update_client(conversation=None):
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=conversation)
    client.create_conversation = AsyncMock()
    client.create_message = AsyncMock(return_value={"id": "msg"})
    client.cosmosdb_client.close = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_update_conversation_writes_user_and_assistant_messages():
    conversation = {"id": "conv-1", "title": "Existing", "updatedAt": FIXED_TIME}
    client = make_update_client(conversation)

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.update_conversation(
            "user-1",
            {
                "conversation_id": "conv-1",
                "messages": [
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": "answer", "id": "msg-assistant"},
                ],
            },
        )

    assert result == {"id": "conv-1", "title": "Existing", "updatedAt": FIXED_TIME}
    assert client.create_message.await_count == 2
    user_call, assistant_call = client.create_message.await_args_list
    assert user_call.kwargs["input_message"] == {"role": "user", "content": "question"}
    assert assistant_call.kwargs["uuid"] == "msg-assistant"
    assert assistant_call.kwargs["input_message"]["role"] == "assistant"
    client.cosmosdb_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_conversation_writes_tool_message_before_assistant_message():
    client = make_update_client({"id": "conv-1", "title": "Existing"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.update_conversation(
            "user-1",
            {
                "conversation_id": "conv-1",
                "messages": [
                    {"role": "user", "content": "question"},
                    {"role": "tool", "content": "tool output"},
                    {"role": "error", "content": "failed", "id": "msg-error"},
                ],
            },
        )

    assert result["updatedAt"] is None
    assert client.create_message.await_count == 3
    assert client.create_message.await_args_list[1].kwargs["input_message"]["role"] == "tool"
    assert client.create_message.await_args_list[2].kwargs["uuid"] == "msg-error"


@pytest.mark.asyncio
async def test_update_conversation_uses_latest_user_message():
    client = make_update_client({"id": "conv-1", "title": "Existing"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        await history.update_conversation(
            "user-1",
            {
                "conversation_id": "conv-1",
                "messages": [
                    {"role": "user", "content": "first"},
                    {"role": "user", "content": "latest"},
                    {"role": "assistant", "content": "answer", "id": "msg-a"},
                ],
            },
        )

    assert client.create_message.await_args_list[0].kwargs["input_message"]["content"] == "latest"


@pytest.mark.asyncio
async def test_update_conversation_creates_conversation_when_missing():
    client = make_update_client(None)
    client.create_conversation = AsyncMock(
        return_value={"id": "conv-1", "title": "Generated Title"}
    )

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)), \
            patch.object(history, "generate_title", AsyncMock(return_value="Generated Title")):
        result = await history.update_conversation(
            "user-1",
            {
                "conversation_id": "conv-1",
                "messages": [
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": "answer", "id": "msg-a"},
                ],
            },
        )

    client.create_conversation.assert_awaited_once_with(
        user_id="user-1", conversation_id="conv-1", title="Generated Title"
    )
    assert result == {"id": "conv-1", "title": "Generated Title", "updatedAt": None}


@pytest.mark.asyncio
async def test_update_conversation_raises_without_conversation_id():
    with patch.object(history, "init_cosmosdb_client", AsyncMock()) as init:
        with pytest.raises(ValueError, match="No conversation_id found"):
            await history.update_conversation("user-1", {"messages": []})

    init.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_conversation_rejects_payload_without_leading_user_message():
    client = make_update_client({"id": "conv-1", "title": "Existing"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(history.HTTPException) as excinfo:
            await history.update_conversation(
                "user-1",
                {"conversation_id": "conv-1", "messages": [{"role": "assistant", "content": "a"}]},
            )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "User message not found"
    client.create_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_conversation_rejects_empty_message_list():
    client = make_update_client({"id": "conv-1", "title": "Existing"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(history.HTTPException) as excinfo:
            await history.update_conversation(
                "user-1", {"conversation_id": "conv-1", "messages": []}
            )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "User message not found"


@pytest.mark.asyncio
async def test_update_conversation_rejects_when_message_creation_reports_missing_conversation():
    client = make_update_client({"id": "conv-1", "title": "Existing"})
    client.create_message = AsyncMock(return_value="Conversation not found")

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(history.HTTPException) as excinfo:
            await history.update_conversation(
                "user-1",
                {"conversation_id": "conv-1", "messages": [{"role": "user", "content": "q"}]},
            )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Conversation not found"


@pytest.mark.asyncio
async def test_update_conversation_rejects_and_closes_client_without_assistant_message():
    client = make_update_client({"id": "conv-1", "title": "Existing"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(history.HTTPException) as excinfo:
            await history.update_conversation(
                "user-1",
                {"conversation_id": "conv-1", "messages": [{"role": "user", "content": "q"}]},
            )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "No assistant message found"
    client.cosmosdb_client.close.assert_awaited_once()


# --------------------------------------------------------------------------- #
# rename_conversation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rename_conversation_updates_title():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1", "title": "Old"})
    client.upsert_conversation = AsyncMock(return_value={"id": "conv-1", "title": "New"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.rename_conversation("user-1", "conv-1", "New")

    assert result == {"id": "conv-1", "title": "New"}
    client.upsert_conversation.assert_awaited_once_with({"id": "conv-1", "title": "New"})


@pytest.mark.asyncio
async def test_rename_conversation_raises_without_conversation_id():
    with patch.object(history, "init_cosmosdb_client", AsyncMock()) as init:
        with pytest.raises(ValueError, match="No conversation_id found"):
            await history.rename_conversation("user-1", None, "New")

    init.assert_not_awaited()


@pytest.mark.asyncio
async def test_rename_conversation_raises_404_when_conversation_missing():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=None)
    client.upsert_conversation = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        with pytest.raises(history.HTTPException) as excinfo:
            await history.rename_conversation("user-1", "conv-1", "New")

    assert excinfo.value.status_code == 404
    assert "conv-1" in excinfo.value.detail
    client.upsert_conversation.assert_not_awaited()


# --------------------------------------------------------------------------- #
# update_message_feedback (module level)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_module_update_message_feedback_returns_updated_message():
    client = MagicMock()
    client.update_message_feedback = AsyncMock(return_value={"id": "msg-1", "feedback": "positive"})

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.update_message_feedback("user-1", "msg-1", "positive")

    assert result == {"id": "msg-1", "feedback": "positive"}
    client.update_message_feedback.assert_awaited_once_with("user-1", "msg-1", "positive")


@pytest.mark.asyncio
async def test_module_update_message_feedback_returns_none_when_not_updated():
    client = MagicMock()
    client.update_message_feedback = AsyncMock(return_value=False)

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.update_message_feedback("user-1", "msg-1", "positive") is None


@pytest.mark.asyncio
async def test_module_update_message_feedback_propagates_errors():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=RuntimeError("cosmos down"))):
        with pytest.raises(RuntimeError, match="cosmos down"):
            await history.update_message_feedback("user-1", "msg-1", "positive")


# --------------------------------------------------------------------------- #
# delete_conversation (module level)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_module_delete_conversation_deletes_messages_then_conversation():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1", "userId": "user-1"})
    client.delete_messages = AsyncMock()
    client.delete_conversation = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.delete_conversation("user-1", "conv-1") is True

    client.delete_messages.assert_awaited_once_with("conv-1", "user-1")
    client.delete_conversation.assert_awaited_once_with("user-1", "conv-1")


@pytest.mark.asyncio
async def test_module_delete_conversation_returns_false_when_conversation_missing():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=None)
    client.delete_messages = AsyncMock()
    client.delete_conversation = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.delete_conversation("user-1", "conv-1") is False

    client.delete_messages.assert_not_awaited()
    client.delete_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_module_delete_conversation_returns_false_for_other_users_conversation():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1", "userId": "someone-else"})
    client.delete_messages = AsyncMock()
    client.delete_conversation = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.delete_conversation("user-1", "conv-1") is False

    client.delete_messages.assert_not_awaited()
    client.delete_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_module_delete_conversation_returns_false_on_error():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await history.delete_conversation("user-1", "conv-1") is False


# --------------------------------------------------------------------------- #
# get_conversations / get_messages / get_conversation_messages (module level)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_module_get_conversations_returns_client_results():
    client = MagicMock()
    client.get_conversations = AsyncMock(return_value=[{"id": "conv-1"}])

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.get_conversations("user-1", offset=5, limit=10)

    assert result == [{"id": "conv-1"}]
    client.get_conversations.assert_awaited_once_with("user-1", offset=5, limit=10)


@pytest.mark.asyncio
async def test_module_get_conversations_normalizes_falsy_result_to_empty_list():
    client = MagicMock()
    client.get_conversations = AsyncMock(return_value=None)

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.get_conversations("user-1", offset=0, limit=25) == []


@pytest.mark.asyncio
async def test_module_get_conversations_returns_empty_list_when_cosmos_unavailable():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=None)):
        assert await history.get_conversations("user-1", offset=0, limit=25) == []


@pytest.mark.asyncio
async def test_module_get_conversations_returns_empty_list_on_error():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await history.get_conversations("user-1", offset=0, limit=25) == []


@pytest.mark.asyncio
async def test_module_get_messages_returns_messages_for_existing_conversation():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1"})
    client.get_messages = AsyncMock(return_value=[{"id": "m1"}])

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.get_messages("user-1", "conv-1")

    assert result == [{"id": "m1"}]
    client.get_messages.assert_awaited_once_with("user-1", "conv-1")


@pytest.mark.asyncio
async def test_module_get_messages_returns_empty_list_when_conversation_missing():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=None)
    client.get_messages = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.get_messages("user-1", "conv-1") == []

    client.get_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_module_get_messages_returns_empty_list_when_cosmos_unavailable():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=None)):
        assert await history.get_messages("user-1", "conv-1") == []


@pytest.mark.asyncio
async def test_module_get_messages_returns_empty_list_on_error():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await history.get_messages("user-1", "conv-1") == []


@pytest.mark.asyncio
async def test_get_conversation_messages_formats_dict_and_string_content():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1"})
    client.get_messages = AsyncMock(
        return_value=[
            {
                "id": "m1",
                "role": "assistant",
                "content": {"content": "structured answer", "citations": ["doc-1"]},
                "createdAt": FIXED_TIME,
                "feedback": "positive",
            },
            {
                "id": "m2",
                "role": "user",
                "content": "plain question",
                "createdAt": FIXED_TIME,
            },
            {"id": "m3", "role": "user", "createdAt": FIXED_TIME},
        ]
    )

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        result = await history.get_conversation_messages("user-1", "conv-1")

    assert result == [
        {
            "id": "m1",
            "role": "assistant",
            "content": "structured answer",
            "createdAt": FIXED_TIME,
            "feedback": "positive",
            "citations": ["doc-1"],
        },
        {
            "id": "m2",
            "role": "user",
            "content": "plain question",
            "createdAt": FIXED_TIME,
            "feedback": None,
            "citations": "",
        },
        {
            "id": "m3",
            "role": "user",
            "content": "",
            "createdAt": FIXED_TIME,
            "feedback": None,
            "citations": "",
        },
    ]


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_none_when_conversation_missing():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=None)
    client.get_messages = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.get_conversation_messages("user-1", "conv-1") is None

    client.get_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_none_when_cosmos_unavailable():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=None)):
        assert await history.get_conversation_messages("user-1", "conv-1") is None


@pytest.mark.asyncio
async def test_get_conversation_messages_returns_none_on_malformed_message():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1"})
    client.get_messages = AsyncMock(return_value=[{"role": "user", "content": "no id key"}])

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.get_conversation_messages("user-1", "conv-1") is None


# --------------------------------------------------------------------------- #
# clear_messages / ensure_cosmos
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_clear_messages_deletes_messages_for_owning_user():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1", "user_id": "user-1"})
    client.delete_messages = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.clear_messages("user-1", "conv-1") is True

    client.delete_messages.assert_awaited_once_with("conv-1", "user-1")


@pytest.mark.asyncio
async def test_clear_messages_returns_false_when_conversation_missing():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value=None)
    client.delete_messages = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.clear_messages("user-1", "conv-1") is False

    client.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_messages_returns_false_for_other_users_conversation():
    client = MagicMock()
    client.get_conversation = AsyncMock(return_value={"id": "conv-1", "user_id": "someone-else"})
    client.delete_messages = AsyncMock()

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.clear_messages("user-1", "conv-1") is False

    client.delete_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_messages_returns_false_when_cosmos_unavailable():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=None)):
        assert await history.clear_messages("user-1", "conv-1") is False


@pytest.mark.asyncio
async def test_clear_messages_returns_false_on_error():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await history.clear_messages("user-1", "conv-1") is False


@pytest.mark.asyncio
async def test_ensure_cosmos_forwards_client_result():
    client = MagicMock()
    client.ensure = AsyncMock(return_value=(True, "CosmosDB client initialized successfully"))

    with patch.object(history, "init_cosmosdb_client", AsyncMock(return_value=client)):
        assert await history.ensure_cosmos() == (
            True,
            "CosmosDB client initialized successfully",
        )


@pytest.mark.asyncio
async def test_ensure_cosmos_returns_error_message_on_failure():
    with patch.object(history, "init_cosmosdb_client", AsyncMock(side_effect=ValueError("Invalid credentials"))):
        assert await history.ensure_cosmos() == (False, "Invalid credentials")


# --------------------------------------------------------------------------- #
# /generate route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_add_conversation_route_returns_handler_result_and_tracks_event():
    request = make_request({"messages": [{"role": "user", "content": "hi"}]})

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "add_conversation", AsyncMock(return_value=True)) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.add_conversation_route(request)

    assert response is True
    handler.assert_awaited_once_with("user-1", {"messages": [{"role": "user", "content": "hi"}]})
    assert event_names(tracker) == ["ConversationCreated"]
    assert tracker.call_args.args[1]["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_add_conversation_route_returns_500_and_records_span_on_error():
    span = MagicMock()

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "add_conversation", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker, \
            patch.object(history.trace, "get_current_span", return_value=span):
        response = await history.add_conversation_route(make_request({"messages": []}))

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "An internal error has occurred!"}
    assert event_names(tracker) == ["GenerateConversationError"]
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"
    assert tracker.call_args.args[1]["error"] == "boom"
    span.record_exception.assert_called_once()
    span.set_status.assert_called_once()


@pytest.mark.asyncio
async def test_add_conversation_route_handles_missing_span():
    with patch.object(history, "get_authenticated_user_details", side_effect=RuntimeError("no auth")), \
            patch.object(history, "track_event_if_configured") as tracker, \
            patch.object(history.trace, "get_current_span", return_value=None):
        response = await history.add_conversation_route(make_request())

    assert response.status_code == 500
    assert tracker.call_args.args[1]["user_id"] == ""


# --------------------------------------------------------------------------- #
# /update route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_conversation_route_returns_conversation_summary():
    update_response = {"id": "conv-1", "title": "Title", "updatedAt": FIXED_TIME}

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_conversation", AsyncMock(return_value=update_response)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_conversation_route(
            make_request({"conversation_id": "conv-1", "messages": []})
        )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "success": True,
        "data": {"title": "Title", "date": FIXED_TIME, "conversation_id": "conv-1"},
    }
    assert event_names(tracker) == ["ConversationUpdated"]


@pytest.mark.asyncio
async def test_update_conversation_route_returns_500_without_conversation_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_conversation", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_conversation_route(make_request({"messages": []}))

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["UpdateConversationError"]
    assert tracker.call_args.args[1]["error"] == "400: No conversation_id found"
    assert tracker.call_args.args[1]["error_type"] == "HTTPException"


@pytest.mark.asyncio
async def test_update_conversation_route_returns_500_when_update_yields_nothing():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_conversation", AsyncMock(return_value=None)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_conversation_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 500
    assert tracker.call_args.args[1]["conversation_id"] == "conv-1"
    assert tracker.call_args.args[1]["error"] == "500: Failed to update conversation"


@pytest.mark.asyncio
async def test_update_conversation_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_conversation", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_conversation_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "An internal error has occurred!"}
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /message_feedback route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_message_feedback_route_returns_success_payload():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_message_feedback", AsyncMock(return_value={"id": "msg-1"})) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_message_feedback_route(
            make_request({"message_id": "msg-1", "message_feedback": "positive"})
        )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "message": "Successfully updated message with feedback positive",
        "message_id": "msg-1",
    }
    handler.assert_awaited_once_with("user-1", "msg-1", "positive")
    assert event_names(tracker) == ["MessageFeedbackUpdated"]


@pytest.mark.asyncio
async def test_update_message_feedback_route_rejects_missing_message_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_message_feedback", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_message_feedback_route(
            make_request({"message_feedback": "positive"})
        )

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["MessageFeedbackValidationError", "MessageFeedbackError"]
    assert tracker.call_args_list[0].args[1]["error"] == "message_id is missing"


@pytest.mark.asyncio
async def test_update_message_feedback_route_rejects_missing_feedback():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_message_feedback", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_message_feedback_route(
            make_request({"message_id": "msg-1"})
        )

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert tracker.call_args_list[0].args[1]["error"] == "message_feedback is missing"


@pytest.mark.asyncio
async def test_update_message_feedback_route_tracks_not_found_when_update_returns_none():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_message_feedback", AsyncMock(return_value=None)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_message_feedback_route(
            make_request({"message_id": "msg-1", "message_feedback": "positive"})
        )

    assert response.status_code == 500
    assert event_names(tracker) == ["MessageFeedbackNotFound", "MessageFeedbackError"]


@pytest.mark.asyncio
async def test_update_message_feedback_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "update_message_feedback", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.update_message_feedback_route(
            make_request({"message_id": "msg-1", "message_feedback": "positive"})
        )

    assert response.status_code == 500
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /delete route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_conversation_route_returns_success_payload():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "delete_conversation", AsyncMock(return_value=True)) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_conversation_route(make_request(), id="conv-1")

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "message": "Successfully deleted conversation and messages",
        "conversation_id": "conv-1",
    }
    handler.assert_awaited_once_with("user-1", "conv-1")
    assert event_names(tracker) == ["ConversationDeleted"]


@pytest.mark.asyncio
async def test_delete_conversation_route_rejects_blank_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "delete_conversation", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_conversation_route(make_request(), id="")

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["DeleteConversationValidationError", "DeleteConversationError"]


@pytest.mark.asyncio
async def test_delete_conversation_route_tracks_not_found_when_delete_fails():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "delete_conversation", AsyncMock(return_value=False)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_conversation_route(make_request(), id="conv-1")

    assert response.status_code == 500
    assert event_names(tracker) == ["DeleteConversationNotFound", "DeleteConversationError"]
    assert tracker.call_args.args[1]["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_delete_conversation_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "delete_conversation", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_conversation_route(make_request(), id="conv-1")

    assert response.status_code == 500
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /list route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_conversations_returns_conversations_with_pagination():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(return_value=[{"id": "conv-1"}])) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.list_conversations(make_request(), offset=10, limit=5)

    assert response.status_code == 200
    assert json.loads(response.body) == [{"id": "conv-1"}]
    handler.assert_awaited_once_with("user-1", offset=10, limit=5)
    assert event_names(tracker) == ["ConversationsListed"]
    assert tracker.call_args.args[1]["conversation_count"] == 1


@pytest.mark.asyncio
async def test_list_conversations_returns_404_when_result_is_not_a_list():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(return_value={"unexpected": True})), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.list_conversations(make_request(), offset=0, limit=25)

    assert response.status_code == 404
    assert json.loads(response.body) == {"error": "No conversations for user-1 were found"}
    assert event_names(tracker) == ["ListConversationsNotFound"]


@pytest.mark.asyncio
async def test_list_conversations_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.list_conversations(make_request(), offset=0, limit=25)

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "An internal error has occurred!"}
    assert event_names(tracker) == ["ListConversationsError"]


# --------------------------------------------------------------------------- #
# /read route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_conversation_messages_route_returns_messages():
    messages = [{"id": "m1", "role": "user", "content": "hi"}]

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversation_messages", AsyncMock(return_value=messages)) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.get_conversation_messages_route(make_request(), id="conv-1")

    assert response.status_code == 200
    assert json.loads(response.body) == {"conversation_id": "conv-1", "messages": messages}
    handler.assert_awaited_once_with("user-1", "conv-1")
    assert event_names(tracker) == ["ConversationRead"]
    assert tracker.call_args.args[1]["message_count"] == 1


@pytest.mark.asyncio
async def test_get_conversation_messages_route_rejects_blank_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversation_messages", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.get_conversation_messages_route(make_request(), id="")

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["ReadConversationValidationError", "ReadConversationError"]


@pytest.mark.asyncio
async def test_get_conversation_messages_route_tracks_not_found_for_empty_result():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversation_messages", AsyncMock(return_value=None)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.get_conversation_messages_route(make_request(), id="conv-1")

    assert response.status_code == 500
    assert event_names(tracker) == ["ReadConversationNotFound", "ReadConversationError"]
    assert tracker.call_args.args[1]["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_get_conversation_messages_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversation_messages", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.get_conversation_messages_route(make_request(), id="conv-1")

    assert response.status_code == 500
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /rename route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rename_conversation_route_returns_updated_conversation():
    renamed = {"id": "conv-1", "title": "New Title"}

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "rename_conversation", AsyncMock(return_value=renamed)) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.rename_conversation_route(
            make_request({"conversation_id": "conv-1", "title": "New Title"})
        )

    assert response.status_code == 200
    assert json.loads(response.body) == renamed
    handler.assert_awaited_once_with("user-1", "conv-1", "New Title")
    assert event_names(tracker) == ["ConversationRenamed"]
    assert tracker.call_args.args[1]["new_title"] == "New Title"


@pytest.mark.asyncio
async def test_rename_conversation_route_rejects_missing_conversation_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "rename_conversation", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.rename_conversation_route(make_request({"title": "New Title"}))

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["RenameConversationValidationError", "RenameConversationError"]
    assert tracker.call_args_list[0].args[1]["error"] == "conversation_id is required"


@pytest.mark.asyncio
async def test_rename_conversation_route_rejects_missing_title():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "rename_conversation", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.rename_conversation_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert tracker.call_args_list[0].args[1]["error"] == "title is required"


@pytest.mark.asyncio
async def test_rename_conversation_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "rename_conversation", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.rename_conversation_route(
            make_request({"conversation_id": "conv-1", "title": "New Title"})
        )

    assert response.status_code == 500
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /delete_all route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_all_conversations_deletes_every_conversation():
    conversations = [{"id": "conv-1"}, {"id": "conv-2"}]

    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(return_value=conversations)) as lister, \
            patch.object(history, "delete_conversation", AsyncMock(return_value=True)) as deleter, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_all_conversations(make_request())

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "message": "Successfully deleted all conversations for user user-1"
    }
    lister.assert_awaited_once_with("user-1", offset=0, limit=None)
    assert [call.args for call in deleter.await_args_list] == [
        ("user-1", "conv-1"),
        ("user-1", "conv-2"),
    ]
    assert event_names(tracker) == ["AllConversationsDeleted"]
    assert tracker.call_args.args[1]["deleted_count"] == 2


@pytest.mark.asyncio
async def test_delete_all_conversations_tracks_not_found_when_user_has_none():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(return_value=[])), \
            patch.object(history, "delete_conversation", AsyncMock()) as deleter, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_all_conversations(make_request())

    assert response.status_code == 500
    deleter.assert_not_awaited()
    assert event_names(tracker) == ["DeleteAllConversationsNotFound", "DeleteAllConversationsError"]


@pytest.mark.asyncio
async def test_delete_all_conversations_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "get_conversations", AsyncMock(return_value=[{"id": "conv-1"}])), \
            patch.object(history, "delete_conversation", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.delete_all_conversations(make_request())

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "An internal error has occurred!"}
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /clear route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_clear_messages_route_returns_success_payload():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "clear_messages", AsyncMock(return_value=True)) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.clear_messages_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 200
    assert json.loads(response.body) == {"message": "Successfully cleared messages"}
    handler.assert_awaited_once_with("user-1", "conv-1")
    assert event_names(tracker) == ["MessagesCleared"]


@pytest.mark.asyncio
async def test_clear_messages_route_rejects_missing_conversation_id():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "clear_messages", AsyncMock()) as handler, \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.clear_messages_route(make_request({}))

    assert response.status_code == 500
    handler.assert_not_awaited()
    assert event_names(tracker) == ["ClearMessagesValidationError", "ClearMessagesError"]


@pytest.mark.asyncio
async def test_clear_messages_route_tracks_failure_when_clear_returns_false():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "clear_messages", AsyncMock(return_value=False)), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.clear_messages_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 500
    assert event_names(tracker) == ["ClearMessagesFailed", "ClearMessagesError"]
    assert tracker.call_args.args[1]["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_clear_messages_route_returns_500_on_unexpected_error():
    with patch.object(history, "get_authenticated_user_details", return_value=USER), \
            patch.object(history, "clear_messages", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.clear_messages_route(
            make_request({"conversation_id": "conv-1"})
        )

    assert response.status_code == 500
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"


# --------------------------------------------------------------------------- #
# /history/ensure route
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_200_when_configured():
    with patch.object(history, "ensure_cosmos", AsyncMock(return_value=(True, "ok"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.ensure_cosmos_route()

    assert response.status_code == 200
    assert json.loads(response.body) == {"message": "CosmosDB is configured and working"}
    assert event_names(tracker) == ["CosmosDBEnsureSuccess"]


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_422_with_reported_error():
    with patch.object(history, "ensure_cosmos", AsyncMock(return_value=(False, "container missing"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.ensure_cosmos_route()

    assert response.status_code == 422
    assert json.loads(response.body) == {"error": "container missing"}
    assert event_names(tracker) == ["CosmosDBEnsureFailed"]
    assert tracker.call_args.args[1]["error"] == "container missing"


@pytest.mark.asyncio
async def test_ensure_cosmos_route_defaults_error_message_when_none_provided():
    with patch.object(history, "ensure_cosmos", AsyncMock(return_value=(False, None))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.ensure_cosmos_route()

    assert response.status_code == 422
    assert json.loads(response.body) == {"error": "Unknown error occurred"}
    assert tracker.call_args.args[1]["error"] == "Unknown error occurred"


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_401_for_invalid_credentials():
    with patch.object(history, "ensure_cosmos", AsyncMock(side_effect=ValueError("Invalid credentials"))), \
            patch.object(history, "track_event_if_configured") as tracker:
        response = await history.ensure_cosmos_route()

    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Invalid credentials"}
    assert event_names(tracker) == ["EnsureCosmosError"]


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_422_for_invalid_database_name():
    with patch.object(history, "ensure_cosmos", AsyncMock(side_effect=ValueError("Invalid CosmosDB database name"))), \
            patch.object(history, "track_event_if_configured"):
        response = await history.ensure_cosmos_route()

    assert response.status_code == 422
    assert json.loads(response.body) == {"error": "Invalid CosmosDB configuration"}


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_422_for_invalid_container_name():
    with patch.object(history, "ensure_cosmos", AsyncMock(side_effect=ValueError("Invalid CosmosDB container name"))), \
            patch.object(history, "track_event_if_configured"):
        response = await history.ensure_cosmos_route()

    assert response.status_code == 422
    assert json.loads(response.body) == {"error": "Invalid CosmosDB configuration"}


@pytest.mark.asyncio
async def test_ensure_cosmos_route_returns_500_for_other_errors():
    span = MagicMock()

    with patch.object(history, "ensure_cosmos", AsyncMock(side_effect=RuntimeError("network unreachable"))), \
            patch.object(history, "track_event_if_configured") as tracker, \
            patch.object(history.trace, "get_current_span", return_value=span):
        response = await history.ensure_cosmos_route()

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "CosmosDB is not configured or not working"}
    tracker.assert_called_once_with("EnsureCosmosError", ANY)
    assert tracker.call_args.args[1]["error_type"] == "RuntimeError"
    span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_cosmos_route_handles_missing_span():
    with patch.object(history, "ensure_cosmos", AsyncMock(side_effect=RuntimeError("boom"))), \
            patch.object(history, "track_event_if_configured") as tracker, \
            patch.object(history.trace, "get_current_span", return_value=None):
        response = await history.ensure_cosmos_route()

    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "CosmosDB is not configured or not working"}
    assert event_names(tracker) == ["EnsureCosmosError"]


# --------------------------------------------------------------------------- #
# Router registration
# --------------------------------------------------------------------------- #


def test_router_exposes_all_history_routes():
    registered = {(route.path, tuple(sorted(route.methods))) for route in history.router.routes}

    assert ("/generate", ("POST",)) in registered
    assert ("/update", ("POST",)) in registered
    assert ("/message_feedback", ("POST",)) in registered
    assert ("/delete", ("DELETE",)) in registered
    assert ("/list", ("GET",)) in registered
    assert ("/read", ("GET",)) in registered
    assert ("/rename", ("POST",)) in registered
    assert ("/delete_all", ("DELETE",)) in registered
    assert ("/clear", ("POST",)) in registered
    assert ("/history/ensure", ("GET",)) in registered
