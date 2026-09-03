"""Unit tests for src/api/python/chat.py.

Every external dependency (Azure credentials, AIProjectClient, FoundryAgent,
Application Insights, ``requests``, FastAPI request objects and environment
variables) is mocked; no network or Azure calls are made.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import chat


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class FakeTimer:
    """Deterministic monotonic clock for TTLCache."""

    def __init__(self, value: float = 0.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def __enter__(self) -> float:
        return self.value

    def __exit__(self, *exc):
        return False


class FakeAsyncCM:
    """Minimal async context manager returning a fixed value."""

    def __init__(self, value, aexit_result=False):
        self.value = value
        self.aexit_result = aexit_result

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return self.aexit_result


class FakeChunk:
    """Stand-in for an agent_framework streaming chunk."""

    def __init__(self, text="", contents=None):
        self.text = text
        self.contents = contents or []


def make_credential():
    credential = MagicMock()
    credential.close = AsyncMock()
    return credential


def make_openai_client(conversation_id="conv-created"):
    openai_client = MagicMock()
    openai_client.conversations.create = AsyncMock(
        return_value=MagicMock(id=conversation_id)
    )
    openai_client.conversations.delete = AsyncMock()
    openai_client.close = AsyncMock()
    return openai_client


def make_project_client(openai_client=None):
    project_client = MagicMock()
    project_client.get_openai_client = MagicMock(
        return_value=openai_client or make_openai_client()
    )
    return project_client


def make_agent(chunks=None, error=None):
    """Build a FoundryAgent double whose ``run`` yields *chunks* or raises."""
    agent = MagicMock()

    async def _run(query, stream=False, options=None):
        agent.run_calls.append((query, stream, options))
        if error is not None:
            raise error
        for chunk in chunks or []:
            yield chunk

    agent.run_calls = []
    agent.run = _run
    return agent


async def collect(async_iterable):
    return [item async for item in async_iterable]


def body_of(response):
    """Decode a starlette JSONResponse body into a dict."""
    return json.loads(response.body.decode("utf-8"))


@pytest.fixture(autouse=True)
def reset_thread_cache():
    """Isolate the module-level thread cache between tests."""
    chat.thread_cache = None
    yield
    chat.thread_cache = None


@pytest.fixture
def stream_env(monkeypatch):
    """Environment used by the streaming tests."""
    monkeypatch.setenv("AZURE_AI_AGENT_ENDPOINT", "https://ai.example.com")
    monkeypatch.setenv("AGENT_NAME_CHAT", "test-agent")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_AI_SEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_SEARCH_INDEX", raising=False)


# --------------------------------------------------------------------------- #
# track_event_if_configured
# --------------------------------------------------------------------------- #


def test_track_event_if_configured_sends_when_connection_string_present(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    with patch.object(chat, "track_event") as track:
        chat.track_event_if_configured("EventA", {"k": "v"})
    track.assert_called_once_with("EventA", {"k": "v"})


def test_track_event_if_configured_skips_and_warns_when_not_configured(monkeypatch, caplog):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    with patch.object(chat, "track_event") as track, caplog.at_level("WARNING"):
        chat.track_event_if_configured("EventB", {"k": "v"})
    track.assert_not_called()
    assert "EventB" in caplog.text


# --------------------------------------------------------------------------- #
# get_thread_cache
# --------------------------------------------------------------------------- #


def test_get_thread_cache_creates_configured_cache_once():
    first = chat.get_thread_cache()
    second = chat.get_thread_cache()

    assert first is second
    assert isinstance(first, chat.ExpCache)
    assert first.maxsize == 1000
    assert first.ttl == 3600.0
    assert chat.thread_cache is first


# --------------------------------------------------------------------------- #
# ExpCache.expire / popitem
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_expire_returns_items_and_schedules_thread_deletion():
    timer = FakeTimer()
    cache = chat.ExpCache(maxsize=10, ttl=5, timer=timer)
    cache["session-1"] = "thread-1"
    timer.value = 100.0

    with patch.object(chat.ExpCache, "_delete_thread_async", new=AsyncMock()) as deleter:
        expired = cache.expire()
        await asyncio.sleep(0)

    assert expired == [("session-1", "thread-1")]
    assert "session-1" not in cache
    deleter.assert_awaited_once_with("thread-1")


@pytest.mark.asyncio
async def test_expire_logs_and_still_returns_items_when_scheduling_fails(caplog):
    timer = FakeTimer()
    cache = chat.ExpCache(maxsize=10, ttl=5, timer=timer)
    cache["session-2"] = "thread-2"
    timer.value = 100.0

    with patch.object(chat.ExpCache, "_delete_thread_async", MagicMock(return_value=None)), \
            patch.object(chat.asyncio, "create_task", side_effect=RuntimeError("no loop")), \
            caplog.at_level("ERROR"):
        expired = cache.expire()

    assert expired == [("session-2", "thread-2")]
    assert "Failed to schedule thread deletion for key session-2" in caplog.text


@pytest.mark.asyncio
async def test_popitem_evicts_lru_entry_and_schedules_deletion():
    cache = chat.ExpCache(maxsize=10, ttl=3600, timer=FakeTimer())
    cache["session-3"] = "thread-3"

    with patch.object(chat.ExpCache, "_delete_thread_async", new=AsyncMock()) as deleter:
        key, value = cache.popitem()
        await asyncio.sleep(0)

    assert (key, value) == ("session-3", "thread-3")
    assert len(cache) == 0
    deleter.assert_awaited_once_with("thread-3")


@pytest.mark.asyncio
async def test_popitem_logs_when_scheduling_fails_but_still_evicts(caplog):
    cache = chat.ExpCache(maxsize=10, ttl=3600, timer=FakeTimer())
    cache["session-4"] = "thread-4"

    with patch.object(chat.ExpCache, "_delete_thread_async", MagicMock(return_value=None)), \
            patch.object(chat.asyncio, "create_task", side_effect=RuntimeError("no loop")), \
            caplog.at_level("ERROR"):
        key, value = cache.popitem()

    assert (key, value) == ("session-4", "thread-4")
    assert len(cache) == 0
    assert "LRU evict" in caplog.text


# --------------------------------------------------------------------------- #
# ExpCache._delete_thread_async
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delete_thread_async_deletes_conversation_and_closes_clients(monkeypatch):
    monkeypatch.setenv("AZURE_AI_AGENT_ENDPOINT", "https://ai.example.com")
    cache = chat.ExpCache(maxsize=1, ttl=1, timer=FakeTimer())
    credential = make_credential()
    openai_client = make_openai_client()
    project_client = make_project_client(openai_client)
    project_ctor = MagicMock(return_value=FakeAsyncCM(project_client))

    with patch.object(chat, "get_azure_credential_async", new=AsyncMock(return_value=credential)), \
            patch.object(chat, "AIProjectClient", project_ctor):
        await cache._delete_thread_async("conv_abc")

    project_ctor.assert_called_once_with(
        endpoint="https://ai.example.com", credential=credential
    )
    openai_client.conversations.delete.assert_awaited_once_with(conversation_id="conv_abc")
    openai_client.close.assert_awaited_once()
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_thread_async_skips_response_ids():
    cache = chat.ExpCache(maxsize=1, ttl=1, timer=FakeTimer())
    credential_factory = AsyncMock()

    with patch.object(chat, "get_azure_credential_async", credential_factory), \
            patch.object(chat, "AIProjectClient") as project_ctor:
        await cache._delete_thread_async("resp_12345")

    credential_factory.assert_not_awaited()
    project_ctor.assert_not_called()


@pytest.mark.asyncio
async def test_delete_thread_async_ignores_empty_identifier():
    cache = chat.ExpCache(maxsize=1, ttl=1, timer=FakeTimer())
    credential_factory = AsyncMock()

    with patch.object(chat, "get_azure_credential_async", credential_factory), \
            patch.object(chat, "AIProjectClient") as project_ctor:
        await cache._delete_thread_async("")

    credential_factory.assert_not_awaited()
    project_ctor.assert_not_called()


@pytest.mark.asyncio
async def test_delete_thread_async_swallows_failures_and_closes_credential(caplog):
    cache = chat.ExpCache(maxsize=1, ttl=1, timer=FakeTimer())
    credential = make_credential()
    openai_client = make_openai_client()
    openai_client.conversations.delete = AsyncMock(side_effect=RuntimeError("boom"))
    project_client = make_project_client(openai_client)

    with patch.object(chat, "get_azure_credential_async", new=AsyncMock(return_value=credential)), \
            patch.object(chat, "AIProjectClient", MagicMock(return_value=FakeAsyncCM(project_client))), \
            caplog.at_level("ERROR"):
        await cache._delete_thread_async("conv_bad")

    assert "Failed to delete thread conv_bad" in caplog.text
    openai_client.close.assert_awaited_once()
    credential.close.assert_awaited_once()


# --------------------------------------------------------------------------- #
# _parse_mcp_docs
# --------------------------------------------------------------------------- #


def test_parse_mcp_docs_indexes_documents_by_section():
    docs = {}
    chat._parse_mcp_docs(
        'intro【4:1†a.pdf】{"id": "doc-1", "source": "a.pdf"} '
        'tail【4:2†b.pdf】{"id": "doc-2", "source": "b.pdf"}',
        docs,
    )

    assert docs == {
        "1": {"id": "doc-1", "source": "a.pdf"},
        "2": {"id": "doc-2", "source": "b.pdf"},
    }


def test_parse_mcp_docs_ignores_malformed_json_fragments():
    docs = {}
    chat._parse_mcp_docs('【4:1†a.pdf】{"id": "doc-1" oops}', docs)

    assert docs == {}


def test_parse_mcp_docs_ignores_sections_without_json():
    docs = {}
    chat._parse_mcp_docs("【4:1†a.pdf】plain narrative text", docs)

    assert docs == {}


def test_parse_mcp_docs_ignores_text_without_markers():
    docs = {}
    chat._parse_mcp_docs('{"id": "doc-1", "source": "a.pdf"}', docs)

    assert docs == {}


# --------------------------------------------------------------------------- #
# _extract_mcp_from_raw
# --------------------------------------------------------------------------- #


def test_extract_mcp_from_raw_reads_direct_string_output():
    docs = {}
    raw = MagicMock(spec=["output"])
    raw.output = '【4:3†c.pdf】{"id": "doc-3", "source": "c.pdf"}'

    chat._extract_mcp_from_raw(raw, docs)

    assert docs == {"3": {"id": "doc-3", "source": "c.pdf"}}


def test_extract_mcp_from_raw_traverses_response_output_items():
    docs = {}
    item = MagicMock(spec=["output"])
    item.output = '【4:4†d.pdf】{"id": "doc-4", "source": "d.pdf"}'
    silent_item = MagicMock(spec=["output"])
    silent_item.output = None
    raw = MagicMock(spec=["output", "response"])
    raw.output = None
    raw.response = MagicMock(spec=["output"])
    raw.response.output = [silent_item, item]

    chat._extract_mcp_from_raw(raw, docs)

    assert docs == {"4": {"id": "doc-4", "source": "d.pdf"}}


def test_extract_mcp_from_raw_ignores_non_string_direct_output():
    docs = {}
    raw = MagicMock(spec=["output", "response"])
    raw.output = {"not": "a string"}
    raw.response = MagicMock(spec=["output"])
    raw.response.output = None

    chat._extract_mcp_from_raw(raw, docs)

    assert docs == {}


def test_extract_mcp_from_raw_ignores_object_without_output_or_response():
    docs = {}
    raw = MagicMock(spec=[])

    chat._extract_mcp_from_raw(raw, docs)

    assert docs == {}


# --------------------------------------------------------------------------- #
# stream_openai_text
# --------------------------------------------------------------------------- #


def patched_stream(agent, project_client=None, credential=None):
    """Context managers patching every external dependency of the stream."""
    project_client = project_client or make_project_client()
    credential = credential or make_credential()
    return (
        patch.object(chat, "get_azure_credential_async", new=AsyncMock(return_value=credential)),
        patch.object(chat, "AIProjectClient", MagicMock(return_value=FakeAsyncCM(project_client))),
        patch.object(chat, "FoundryAgent", MagicMock(return_value=agent)),
    )


@pytest.mark.asyncio
async def test_stream_openai_text_creates_conversation_and_yields_plain_text(stream_env):
    agent = make_agent([FakeChunk("Hello "), FakeChunk(""), FakeChunk("world")])
    openai_client = make_openai_client("conv-created")
    project_client = make_project_client(openai_client)
    credential = make_credential()
    cred_patch, proj_patch, agent_patch = patched_stream(agent, project_client, credential)

    with cred_patch, proj_patch as project_ctor, agent_patch as agent_ctor:
        result = await collect(chat.stream_openai_text("session-a", "hi", user_id="u1"))

    assert result == [("assistant", "Hello "), ("assistant", "world"), ("tool", "[]")]
    openai_client.conversations.create.assert_awaited_once()
    assert chat.get_thread_cache()["session-a"] == "conv-created"
    assert agent.run_calls == [("hi", True, {"conversation_id": "conv-created"})]
    agent_ctor.assert_called_once_with(project_client=project_client, agent_name="test-agent")
    project_ctor.assert_called_once_with(
        endpoint="https://ai.example.com", credential=credential
    )
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_openai_text_reuses_cached_conversation(stream_env):
    chat.get_thread_cache()["session-b"] = "conv-cached"
    agent = make_agent([FakeChunk("text")])
    openai_client = make_openai_client()
    project_client = make_project_client(openai_client)
    cred_patch, proj_patch, agent_patch = patched_stream(agent, project_client)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-b", "hi"))

    assert ("assistant", "text") in result
    openai_client.conversations.create.assert_not_awaited()
    assert agent.run_calls == [("hi", True, {"conversation_id": "conv-cached"})]


@pytest.mark.asyncio
async def test_stream_openai_text_substitutes_placeholder_for_empty_query(stream_env):
    agent = make_agent([FakeChunk("ok")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        await collect(chat.stream_openai_text("session-c", ""))

    assert agent.run_calls[0][0] == "Please provide a query."


@pytest.mark.asyncio
async def test_stream_openai_text_uses_obo_assertion_only_when_feature_enabled(stream_env):
    agent = make_agent([FakeChunk("ok")])
    credential_factory = AsyncMock(return_value=make_credential())
    project_client = make_project_client()

    with patch.object(chat, "USE_USER_ACCESS_TOKEN", True), \
            patch.object(chat, "get_azure_credential_async", credential_factory), \
            patch.object(chat, "AIProjectClient", MagicMock(return_value=FakeAsyncCM(project_client))), \
            patch.object(chat, "FoundryAgent", MagicMock(return_value=agent)):
        await collect(chat.stream_openai_text("session-d", "hi", user_assertion="user-token"))

    credential_factory.assert_awaited_once_with(user_assertion="user-token")


@pytest.mark.asyncio
async def test_stream_openai_text_drops_user_assertion_when_feature_disabled(stream_env):
    agent = make_agent([FakeChunk("ok")])
    credential_factory = AsyncMock(return_value=make_credential())
    project_client = make_project_client()

    with patch.object(chat, "USE_USER_ACCESS_TOKEN", False), \
            patch.object(chat, "get_azure_credential_async", credential_factory), \
            patch.object(chat, "AIProjectClient", MagicMock(return_value=FakeAsyncCM(project_client))), \
            patch.object(chat, "FoundryAgent", MagicMock(return_value=agent)):
        await collect(chat.stream_openai_text("session-e", "hi", user_assertion="user-token"))

    credential_factory.assert_awaited_once_with(user_assertion=None)


@pytest.mark.asyncio
async def test_stream_openai_text_replaces_markers_with_numbered_citations(stream_env):
    agent = make_agent([FakeChunk("Ref【4:1†doc.pdf】end")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-f", "q"))

    assert result[:3] == [("assistant", "Ref"), ("assistant", "[1]"), ("assistant", "end")]
    citations = json.loads(result[-1][1])
    assert citations == [{"url": "", "source": "doc.pdf", "id": ""}]


@pytest.mark.asyncio
async def test_stream_openai_text_drops_section_zero_markers(stream_env):
    agent = make_agent([FakeChunk("A【4:0†sys】B")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-g", "q"))

    assert result == [("assistant", "A"), ("assistant", "B"), ("tool", "[]")]


@pytest.mark.asyncio
async def test_stream_openai_text_reassembles_marker_split_across_chunks(stream_env):
    agent = make_agent([FakeChunk("Text【4:1†do"), FakeChunk("c.pdf】more")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-h", "q"))

    assert result[:3] == [("assistant", "Text"), ("assistant", "[1]"), ("assistant", "more")]


@pytest.mark.asyncio
async def test_stream_openai_text_flushes_trailing_incomplete_marker(stream_env):
    agent = make_agent([FakeChunk("【4:1†unfinis")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-i", "q"))

    assert result == [("assistant", "【4:1†unfinis"), ("tool", "[]")]


@pytest.mark.asyncio
async def test_stream_openai_text_deduplicates_identical_markers(stream_env):
    agent = make_agent([FakeChunk("x【4:1†a.pdf】y【4:1†a.pdf】z【4:2†b.pdf】")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-j", "q"))

    emitted = [content for role, content in result if role == "assistant"]
    assert emitted == ["x", "[1]", "y", "[1]", "z", "[2]"]
    citations = json.loads(result[-1][1])
    assert [c["source"] for c in citations] == ["a.pdf", "b.pdf"]


@pytest.mark.asyncio
async def test_stream_openai_text_keys_citations_on_full_marker_not_section_index(stream_env):
    # Same section index, different source: these are distinct citations.
    agent = make_agent([FakeChunk("x【4:1†a.pdf】y【9:1†b.pdf】")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-j2", "q"))

    emitted = [content for role, content in result if role == "assistant"]
    assert emitted == ["x", "[1]", "y", "[2]"]
    citations = json.loads(result[-1][1])
    assert [c["source"] for c in citations] == ["a.pdf", "b.pdf"]


@pytest.mark.asyncio
async def test_stream_openai_text_builds_search_urls_from_mcp_documents(stream_env, monkeypatch):
    monkeypatch.setenv("AZURE_AI_SEARCH_ENDPOINT", "https://search.example.com/")
    monkeypatch.setenv("AZURE_AI_SEARCH_INDEX", "idx")
    raw = MagicMock(spec=["output"])
    raw.output = '【4:1†a.pdf】{"id": "doc a/1", "source": "resolved.pdf"}'
    content = MagicMock(spec=["raw_representation"])
    content.raw_representation = raw
    agent = make_agent([
        FakeChunk("", contents=[content]),
        FakeChunk("answer【4:1†a.pdf】"),
    ])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-k", "q"))

    citations = json.loads(result[-1][1])
    assert citations == [{
        "url": (
            "https://search.example.com/indexes/idx/docs/doc%20a%2F1"
            "?api-version=2024-07-01&$select=id,chunk_id,content,source"
        ),
        "source": "resolved.pdf",
        "id": "doc a/1",
    }]


@pytest.mark.asyncio
async def test_stream_openai_text_omits_url_when_document_id_is_unknown(stream_env, monkeypatch):
    monkeypatch.setenv("AZURE_AI_SEARCH_ENDPOINT", "https://search.example.com")
    monkeypatch.setenv("AZURE_AI_SEARCH_INDEX", "idx")
    agent = make_agent([FakeChunk("answer【4:1†a.pdf】")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-k2", "q"))

    citations = json.loads(result[-1][1])
    assert citations == [{"url": "", "source": "a.pdf", "id": ""}]


@pytest.mark.asyncio
async def test_stream_openai_text_falls_back_to_synthetic_source_label(stream_env):
    agent = make_agent([FakeChunk("answer【4:7†】")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-l", "q"))

    citations = json.loads(result[-1][1])
    assert citations == [{"url": "", "source": "source_7", "id": ""}]


@pytest.mark.asyncio
async def test_stream_openai_text_skips_content_without_raw_representation(stream_env):
    content = MagicMock(spec=["raw_representation"])
    content.raw_representation = None
    agent = make_agent([FakeChunk("plain", contents=[content])])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-m", "q"))

    assert result == [("assistant", "plain"), ("tool", "[]")]


@pytest.mark.asyncio
async def test_stream_openai_text_emits_fallback_message_when_model_returns_nothing(stream_env):
    agent = make_agent([])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch:
        result = await collect(chat.stream_openai_text("session-n", "q"))

    assert result == [
        ("tool", "[]"),
        (
            "assistant",
            "I cannot answer this question with the current data. "
            "Please rephrase or add more details.",
        ),
    ]


@pytest.mark.asyncio
async def test_stream_openai_text_emits_telemetry_when_app_insights_configured(stream_env, monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    agent = make_agent([FakeChunk("hello【4:1†a.pdf】")])
    cred_patch, proj_patch, agent_patch = patched_stream(agent)

    with cred_patch, proj_patch, agent_patch, patch.object(chat, "track_event") as track:
        await collect(chat.stream_openai_text("session-o", "q", user_id="u9"))

    track.assert_called_once_with(
        "ChatResponseCompleted",
        {
            "conversation_id": "session-o",
            "user_id": "u9",
            "response_length": "16",
            "citation_count": "1",
        },
    )


@pytest.mark.asyncio
async def test_stream_openai_text_quarantines_conversation_on_failure(stream_env):
    chat.get_thread_cache()["session-p"] = "conv-broken"
    agent = make_agent(error=RuntimeError("agent exploded"))
    credential = make_credential()
    cred_patch, proj_patch, agent_patch = patched_stream(agent, credential=credential)

    with cred_patch, proj_patch, agent_patch:
        with pytest.raises(chat.HTTPException) as excinfo:
            await collect(chat.stream_openai_text("session-p", "q"))

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail == "Error streaming OpenAI text"
    cache = chat.get_thread_cache()
    assert "session-p" not in cache
    quarantined = [k for k in cache if k.startswith("session-p_corrupt_")]
    assert len(quarantined) == 1
    assert cache[quarantined[0]] == "conv-broken"
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_openai_text_failure_without_cached_conversation_adds_no_quarantine(stream_env):
    agent = make_agent(error=RuntimeError("agent exploded"))
    openai_client = make_openai_client()
    openai_client.conversations.create = AsyncMock(side_effect=RuntimeError("create failed"))
    project_client = make_project_client(openai_client)
    cred_patch, proj_patch, agent_patch = patched_stream(agent, project_client)

    with cred_patch, proj_patch, agent_patch:
        with pytest.raises(chat.HTTPException):
            await collect(chat.stream_openai_text("session-q", "q"))

    assert list(chat.get_thread_cache().keys()) == []


# --------------------------------------------------------------------------- #
# stream_chat_request
# --------------------------------------------------------------------------- #


def fake_stream(items=None, error=None):
    async def _stream(conversation_id, query, user_id="", user_assertion=None):
        for item in items or []:
            yield item
        if error is not None:
            raise error

    return _stream


@pytest.mark.asyncio
async def test_stream_chat_request_wraps_fragments_in_delta_envelopes():
    stream = fake_stream([
        ("assistant", "Hél"),
        ("assistant", ""),
        ("assistant", "lo"),
        ("tool", "[]"),
    ])

    with patch.object(chat, "stream_openai_text", stream):
        generator = await chat.stream_chat_request("c1", "q", user_id="u1")
        lines = await collect(generator)

    payloads = [json.loads(line) for line in lines]
    assert payloads == [
        {"choices": [{"delta": {"role": "assistant", "content": "Hél"}}]},
        {"choices": [{"delta": {"role": "assistant", "content": "lo"}}]},
        {"choices": [{"delta": {"role": "tool", "content": "[]"}}]},
    ]
    # Fragments are newline-delimited (single \n) and kept as raw UTF-8.
    assert lines == [json.dumps(p, ensure_ascii=False) + "\n" for p in payloads]
    assert "Hél" in lines[0]


@pytest.mark.asyncio
async def test_stream_chat_request_forwards_identity_arguments():
    seen = {}

    async def _stream(conversation_id, query, user_id="", user_assertion=None):
        seen.update(
            conversation_id=conversation_id,
            query=query,
            user_id=user_id,
            user_assertion=user_assertion,
        )
        yield ("assistant", "ok")

    with patch.object(chat, "stream_openai_text", _stream):
        generator = await chat.stream_chat_request("c2", "hello", user_id="u2", user_assertion="tok")
        await collect(generator)

    assert seen == {
        "conversation_id": "c2",
        "query": "hello",
        "user_id": "u2",
        "user_assertion": "tok",
    }


@pytest.mark.asyncio
async def test_stream_chat_request_reports_rate_limit_retry_delay():
    error = chat.HTTPException(
        status_code=500,
        detail="Rate limit is exceeded. Try again in 42 seconds.",
    )

    with patch.object(chat, "stream_openai_text", fake_stream([("assistant", "x")], error)):
        generator = await chat.stream_chat_request("c3", "q")
        lines = await collect(generator)

    assert json.loads(lines[-1]) == {
        "error": "Rate limit is exceeded. Try again in 42 seconds."
    }


@pytest.mark.asyncio
async def test_stream_chat_request_uses_placeholder_delay_when_none_reported():
    error = chat.HTTPException(status_code=429, detail="Too many requests")

    with patch.object(chat, "stream_openai_text", fake_stream(error=error)):
        generator = await chat.stream_chat_request("c4", "q")
        lines = await collect(generator)

    assert json.loads(lines[0]) == {
        "error": "Rate limit is exceeded. Try again in sometime."
    }


@pytest.mark.asyncio
async def test_stream_chat_request_masks_non_rate_limit_http_errors():
    error = chat.HTTPException(status_code=503, detail="upstream unavailable")

    with patch.object(chat, "stream_openai_text", fake_stream(error=error)):
        generator = await chat.stream_chat_request("c5", "q")
        lines = await collect(generator)

    assert json.loads(lines[0]) == {"error": "An error occurred. Please try again later."}


@pytest.mark.asyncio
async def test_stream_chat_request_masks_unexpected_errors():
    with patch.object(chat, "stream_openai_text", fake_stream(error=ValueError("kaboom"))):
        generator = await chat.stream_chat_request("c6", "q")
        lines = await collect(generator)

    assert json.loads(lines[0]) == {
        "error": "An error occurred while processing the request."
    }


# --------------------------------------------------------------------------- #
# fetch_azure_search_content
# --------------------------------------------------------------------------- #


SEARCH_URL = (
    "https://search.example.com/indexes/idx/docs/doc%201"
    "?api-version=2024-07-01&$select=id,chunk_id,content,source"
)


def make_request(payload, headers=None, json_error=None):
    request = MagicMock()
    request.json = AsyncMock(
        side_effect=json_error) if json_error else AsyncMock(return_value=payload)
    request.headers = headers if headers is not None else {}
    return request


def patch_search_credential(token="tok-123"):
    credential = make_credential()
    credential.get_token = AsyncMock(return_value=MagicMock(token=token))
    return credential, patch.object(
        chat, "get_azure_credential_async", new=AsyncMock(return_value=credential)
    )


@pytest.mark.asyncio
async def test_fetch_azure_search_content_rejects_missing_url():
    response = await chat.fetch_azure_search_content(make_request({}))

    assert response.status_code == 400
    assert body_of(response) == {"error": "URL is required"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_requires_configured_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_SEARCH_ENDPOINT", raising=False)

    response = await chat.fetch_azure_search_content(make_request({"url": SEARCH_URL}))

    assert response.status_code == 500
    assert body_of(response) == {"error": "Search endpoint not configured"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_blocks_foreign_hosts(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")

    response = await chat.fetch_azure_search_content(
        make_request({"url": "https://evil.example.net/indexes/idx/docs/doc1"})
    )

    assert response.status_code == 403
    assert body_of(response) == {"error": "URL host not allowed"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_rejects_url_without_document_id(monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_AI_SEARCH_ENDPOINT", "https://search.example.com")

    response = await chat.fetch_azure_search_content(
        make_request({"url": "https://search.example.com/indexes/idx/docs"})
    )

    assert response.status_code == 400
    assert body_of(response) == {"error": "Could not parse document ID from URL"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_returns_document_via_key_lookup(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    credential, credential_patch = patch_search_credential()
    http_response = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"content": "body text", "source": "a.pdf"}),
    )

    with credential_patch, patch("requests.get", return_value=http_response) as http_get:
        response = await chat.fetch_azure_search_content(
            make_request({"url": SEARCH_URL, "source": "fallback.pdf"})
        )

    assert response.status_code == 200
    assert body_of(response) == {"content": "body text", "title": "a.pdf"}
    called_url, called_kwargs = http_get.call_args[0][0], http_get.call_args[1]
    assert called_url == (
        "https://search.example.com/indexes/idx/docs('doc%201')?api-version=2024-07-01"
    )
    assert called_kwargs["headers"]["Authorization"] == "Bearer tok-123"
    assert called_kwargs["timeout"] == 10
    credential.get_token.assert_awaited_once_with("https://search.azure.com/.default")
    credential.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_azure_search_content_uses_title_fallback_and_default_api_version(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    _credential, credential_patch = patch_search_credential()
    http_response = MagicMock(status_code=200, json=MagicMock(return_value={}))

    with credential_patch, patch("requests.get", return_value=http_response) as http_get:
        response = await chat.fetch_azure_search_content(
            make_request(
                {
                    "url": "https://search.example.com/indexes/idx/docs/doc9",
                    "title": "Titled Doc",
                }
            )
        )

    assert body_of(response) == {"content": "", "title": "Titled Doc"}
    assert http_get.call_args[0][0] == (
        "https://search.example.com/indexes/idx/docs('doc9')?api-version=2024-07-01"
    )


@pytest.mark.asyncio
async def test_fetch_azure_search_content_preserves_requested_api_version(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    _credential, credential_patch = patch_search_credential()
    http_response = MagicMock(status_code=200, json=MagicMock(return_value={}))

    with credential_patch, patch("requests.get", return_value=http_response) as http_get:
        await chat.fetch_azure_search_content(
            make_request(
                {
                    "url": "https://search.example.com/indexes/idx/docs/doc9"
                            "?api-version=2023-11-01"
                }
            )
        )

    assert http_get.call_args[0][0] == (
        "https://search.example.com/indexes/idx/docs('doc9')?api-version=2023-11-01"
    )


@pytest.mark.asyncio
async def test_fetch_azure_search_content_labels_document_with_request_source(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    _credential, credential_patch = patch_search_credential()
    http_response = MagicMock(
        status_code=200, json=MagicMock(return_value={"content": "body text"})
    )

    with credential_patch, patch("requests.get", return_value=http_response):
        response = await chat.fetch_azure_search_content(
            make_request(
                {"url": SEARCH_URL, "source": "fallback.pdf", "title": "Titled Doc"}
            )
        )

    assert body_of(response) == {"content": "body text", "title": "fallback.pdf"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_surfaces_upstream_status_codes(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    _credential, credential_patch = patch_search_credential()
    http_response = MagicMock(status_code=404, text="not found")

    with credential_patch, patch("requests.get", return_value=http_response):
        response = await chat.fetch_azure_search_content(make_request({"url": SEARCH_URL}))

    assert body_of(response) == {"error": "HTTP 404"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_masks_transport_failures(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example.com")
    _credential, credential_patch = patch_search_credential()

    with credential_patch, patch("requests.get", side_effect=OSError("connection reset")):
        response = await chat.fetch_azure_search_content(make_request({"url": SEARCH_URL}))

    assert body_of(response) == {"error": "Unable to fetch content"}


@pytest.mark.asyncio
async def test_fetch_azure_search_content_returns_500_on_unexpected_error():
    request = make_request(None, json_error=ValueError("bad payload"))

    response = await chat.fetch_azure_search_content(request)

    assert response.status_code == 500
    assert body_of(response) == {"error": "Internal server error"}


# --------------------------------------------------------------------------- #
# conversation endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_conversation_rejects_missing_query():
    with patch.object(
        chat, "get_authenticated_user_details", return_value={"user_principal_id": "u1"}
    ):
        response = await chat.conversation(make_request({"conversation_id": "c1"}))

    assert response.status_code == 400
    assert body_of(response) == {"error": "Query is required"}


@pytest.mark.asyncio
async def test_conversation_rejects_missing_conversation_id():
    with patch.object(
        chat, "get_authenticated_user_details", return_value={"user_principal_id": "u1"}
    ):
        response = await chat.conversation(make_request({"query": "hello"}))

    assert response.status_code == 400
    assert body_of(response) == {"error": "Conversation ID is required"}


@pytest.mark.asyncio
async def test_conversation_streams_response_and_tracks_events(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")

    async def _generate():
        yield "chunk-1"

    request = make_request(
        {"conversation_id": "c7", "query": "hello"}, headers={"x-auth": "1"}
    )
    identity = {"user_principal_id": "u7", "aad_access_token": "user-token"}

    with patch.object(chat, "get_authenticated_user_details", return_value=identity) as auth, \
            patch.object(chat, "stream_chat_request", new=AsyncMock(return_value=_generate())) as streamer, \
            patch.object(chat, "track_event") as track:
        response = await chat.conversation(request)

    assert isinstance(response, chat.StreamingResponse)
    assert response.media_type == "application/json-lines"
    auth.assert_called_once_with(request_headers=request.headers)
    streamer.assert_awaited_once_with(
        "c7", "hello", user_id="u7", user_assertion="user-token"
    )
    assert [call.args[0] for call in track.call_args_list] == [
        "ChatRequestReceived",
        "ChatStreamSuccess",
    ]
    assert track.call_args_list[1].args[1] == {
        "conversation_id": "c7",
        "user_id": "u7",
        "query": "hello",
    }


@pytest.mark.asyncio
async def test_conversation_returns_500_and_records_span_exception(monkeypatch):
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=abc")
    request = make_request({"conversation_id": "c8", "query": "hello"})
    span = MagicMock()

    with patch.object(chat, "get_authenticated_user_details", return_value={"user_principal_id": "u8"}), \
            patch.object(chat, "stream_chat_request", new=AsyncMock(side_effect=RuntimeError("stream down"))), \
            patch.object(chat.trace, "get_current_span", return_value=span), \
            patch.object(chat, "track_event") as track:
        response = await chat.conversation(request)

    assert response.status_code == 500
    assert body_of(response) == {
        "error": "An internal error occurred while processing the conversation."
    }
    span.record_exception.assert_called_once()
    span.set_status.assert_called_once()
    error_event = track.call_args_list[-1].args
    assert error_event[0] == "ChatRequestError"
    assert error_event[1]["conversation_id"] == "c8"
    assert error_event[1]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_conversation_handles_unreadable_payload_without_span():
    request = make_request(None, json_error=ValueError("bad payload"))

    with patch.object(chat.trace, "get_current_span", return_value=None), \
            patch.object(chat, "track_event_if_configured") as track:
        response = await chat.conversation(request)

    assert response.status_code == 500
    assert body_of(response) == {
        "error": "An internal error occurred while processing the conversation."
    }
    error_event = track.call_args_list[-1].args
    assert error_event[0] == "ChatRequestError"
    assert error_event[1]["conversation_id"] == ""
    assert error_event[1]["user_id"] == ""
    assert error_event[1]["error_type"] == "ValueError"
