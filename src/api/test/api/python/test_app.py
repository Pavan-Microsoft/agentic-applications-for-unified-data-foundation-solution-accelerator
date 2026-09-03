"""Unit tests for src/api/python/app.py.

All import-time side effects are neutralised: ``configure_azure_monitor``
(Application Insights), ``load_dotenv`` (file system) and
``FastAPIInstrumentor.instrument_app`` (OpenTelemetry) are patched at their
source modules so that reloading ``app`` under different environment variables
never touches Azure, the network or the ``.env`` file. The OpenTelemetry span is
a ``MagicMock``, and the HTTP middleware is exercised both directly (with fake
request objects) and through Starlette's in-process ``TestClient``.
"""

import contextvars
import importlib
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

import app as app_module


# Logger names ``_configure_logging`` always suppresses.
SUPPRESSED_LOGGERS = (
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "azure.ai",
    "azure.monitor.opentelemetry",
    "opentelemetry",
    "urllib3",
    "httpx",
    "httpcore",
)

LOGGING_ENV_VARS = (
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
    "AZURE_BASIC_LOGGING_LEVEL",
    "AZURE_PACKAGE_LOGGING_LEVEL",
    "AZURE_LOGGING_PACKAGES",
)

CONNECTION_STRING = "InstrumentationKey=00000000-0000-0000-0000-000000000000"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class FakeRequest:
    """Minimal stand-in for ``starlette.requests.Request``."""

    def __init__(self, method="GET", headers=None, body=b"", body_error=None):
        self.method = method
        self.headers = headers or {}
        self._body = body
        self._body_error = body_error
        self.body_reads = 0

    async def body(self):
        self.body_reads += 1
        if self._body_error is not None:
            raise self._body_error
        return self._body


def make_span(recording=True):
    span = MagicMock()
    span.is_recording.return_value = recording
    return span


def attributes_of(span):
    return {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}


def get_http_middleware_dispatch(fastapi_app):
    """Return the ``attach_trace_attributes`` closure registered on *fastapi_app*."""
    for middleware in fastapi_app.user_middleware:
        dispatch = getattr(middleware, "kwargs", {}).get("dispatch")
        if dispatch is None:
            positional = getattr(middleware, "args", ())
            dispatch = positional[0] if positional else None
        if callable(dispatch) and getattr(dispatch, "__name__", "") == "attach_trace_attributes":
            return dispatch
    raise AssertionError("attach_trace_attributes middleware was not registered")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def preserve_logging_state():
    """Snapshot and restore the global logging state app.py mutates."""
    original_factory = logging.getLogRecordFactory()
    root = logging.getLogger()
    original_root_level = root.level
    original_levels = {name: logging.getLogger(name).level for name in SUPPRESSED_LOGGERS}

    yield

    logging.setLogRecordFactory(original_factory)
    root.setLevel(original_root_level)
    for name, level in original_levels.items():
        logging.getLogger(name).setLevel(level)


@pytest.fixture(autouse=True)
def reset_trace_context_vars():
    """Keep context-var leakage from bleeding between tests."""
    app_module.conversation_id_var.set("")
    app_module.user_id_var.set("")
    yield
    app_module.conversation_id_var.set("")
    app_module.user_id_var.set("")


@pytest.fixture
def reload_app(monkeypatch, preserve_logging_state):
    """Re-execute app.py's module body under a controlled environment."""

    def _reload(**env):
        for name in LOGGING_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)

        with patch("azure.monitor.opentelemetry.configure_azure_monitor") as monitor, patch(
            "dotenv.load_dotenv"
        ) as load_dotenv, patch.object(FastAPIInstrumentor, "instrument_app") as instrument:
            reloaded = importlib.reload(app_module)
            return reloaded, monitor, load_dotenv, instrument

    return _reload


@pytest.fixture
def built_app():
    """A freshly built FastAPI app plus the trace-enrichment middleware."""
    fastapi_app = app_module.build_app()
    return fastapi_app, get_http_middleware_dispatch(fastapi_app)


@pytest.fixture
def dispatch(built_app):
    return built_app[1]


def make_record(func="some_function", conversation_id="", user_id=""):
    """Build a LogRecord through the currently installed record factory."""
    app_module.conversation_id_var.set(conversation_id)
    app_module.user_id_var.set(user_id)
    factory = logging.getLogRecordFactory()
    return factory("test.logger", logging.INFO, __file__, 42, "message", None, None, func=func)


# --------------------------------------------------------------------------- #
# _configure_logging - Application Insights branch
# --------------------------------------------------------------------------- #


def test_configures_application_insights_when_a_connection_string_is_present(reload_app, caplog):
    # The root-level assertion stays inside the context manager: caplog.at_level
    # restores the pre-test root level on exit and would undo _configure_logging.
    with caplog.at_level(logging.DEBUG):
        _, monitor, _, _ = reload_app(APPLICATIONINSIGHTS_CONNECTION_STRING=CONNECTION_STRING)

        monitor.assert_called_once_with(connection_string=CONNECTION_STRING)
        assert "Application Insights configured" in [r.getMessage() for r in caplog.records]
        assert logging.getLogger().level == logging.INFO


def test_warns_and_skips_the_exporter_when_no_connection_string_is_present(reload_app, caplog):
    with caplog.at_level(logging.DEBUG):
        _, monitor, _, _ = reload_app()

    monitor.assert_not_called()
    messages = [r.getMessage() for r in caplog.records]
    assert "No Application Insights connection string found" in messages
    assert "Application Insights configured" not in messages


def test_an_empty_connection_string_is_treated_as_not_configured(reload_app):
    _, monitor, _, _ = reload_app(APPLICATIONINSIGHTS_CONNECTION_STRING="")

    monitor.assert_not_called()


def test_does_not_reach_the_network_or_dotenv_file_during_module_execution(reload_app):
    _, monitor, load_dotenv, instrument = reload_app(
        APPLICATIONINSIGHTS_CONNECTION_STRING=CONNECTION_STRING
    )

    assert load_dotenv.call_count == 1
    assert instrument.call_count == 1
    assert monitor.call_count == 1


def test_instruments_the_module_level_app_and_excludes_the_health_endpoint(reload_app):
    reloaded, _, _, instrument = reload_app()

    instrument.assert_called_once_with(reloaded.app, excluded_urls="health")


# --------------------------------------------------------------------------- #
# _configure_logging - levels
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("DEBUG", logging.DEBUG), ("debug", logging.DEBUG), ("ERROR", logging.ERROR)],
)
def test_basic_logging_level_env_var_sets_the_root_level(configured, expected, reload_app):
    reload_app(
        APPLICATIONINSIGHTS_CONNECTION_STRING=CONNECTION_STRING,
        AZURE_BASIC_LOGGING_LEVEL=configured,
    )

    assert logging.getLogger().level == expected


def test_unknown_basic_logging_level_falls_back_to_info(reload_app):
    reload_app(
        APPLICATIONINSIGHTS_CONNECTION_STRING=CONNECTION_STRING,
        AZURE_BASIC_LOGGING_LEVEL="NOT_A_LEVEL",
    )

    assert logging.getLogger().level == logging.INFO


def test_package_logging_level_env_var_suppresses_the_noisy_azure_loggers(reload_app):
    reload_app(AZURE_PACKAGE_LOGGING_LEVEL="ERROR")

    for name in SUPPRESSED_LOGGERS:
        assert logging.getLogger(name).level == logging.ERROR, name


def test_unknown_package_logging_level_falls_back_to_warning(reload_app):
    reload_app(AZURE_PACKAGE_LOGGING_LEVEL="LOUD")

    assert logging.getLogger("azure.identity").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING


def test_default_package_level_is_warning_when_the_env_var_is_absent(reload_app):
    reload_app()

    assert logging.getLogger("opentelemetry").level == logging.WARNING


def test_extra_packages_from_the_env_var_are_suppressed_alongside_the_defaults(reload_app):
    reload_app(
        AZURE_PACKAGE_LOGGING_LEVEL="CRITICAL",
        AZURE_LOGGING_PACKAGES="my_pkg.alpha, my_pkg.beta",
    )

    assert logging.getLogger("my_pkg.alpha").level == logging.CRITICAL
    assert logging.getLogger("my_pkg.beta").level == logging.CRITICAL
    assert logging.getLogger("azure.identity").level == logging.CRITICAL


def test_blank_entries_in_the_extra_packages_env_var_are_ignored(reload_app):
    before = logging.getLogger().level

    reload_app(AZURE_PACKAGE_LOGGING_LEVEL="ERROR", AZURE_LOGGING_PACKAGES=" , ,   ,")

    # A blank name would resolve to the root logger and clobber the root level.
    assert logging.getLogger().level == before
    assert logging.getLogger("httpx").level == logging.ERROR


def test_empty_extra_packages_env_var_leaves_only_the_default_suppression_list(reload_app):
    reload_app(AZURE_PACKAGE_LOGGING_LEVEL="ERROR", AZURE_LOGGING_PACKAGES="")

    assert logging.getLogger("httpcore").level == logging.ERROR


# --------------------------------------------------------------------------- #
# _configure_logging - record factory enrichment
# --------------------------------------------------------------------------- #


def test_record_factory_adds_both_context_ids_to_a_normal_record(reload_app):
    reload_app()

    record = make_record(conversation_id="conv-1", user_id="user-1")

    assert record.conversation_id == "conv-1"
    assert record.user_id == "user-1"
    assert record.getMessage() == "message"


def test_record_factory_returns_track_event_records_unenriched(reload_app):
    reload_app()

    record = make_record(func="track_event", conversation_id="conv-1", user_id="user-1")

    assert not hasattr(record, "conversation_id")
    assert not hasattr(record, "user_id")
    assert record.funcName == "track_event"


def test_record_factory_adds_only_the_conversation_id_when_no_user_is_set(reload_app):
    reload_app()

    record = make_record(conversation_id="conv-only")

    assert record.conversation_id == "conv-only"
    assert not hasattr(record, "user_id")


def test_record_factory_adds_only_the_user_id_when_no_conversation_is_set(reload_app):
    reload_app()

    record = make_record(user_id="user-only")

    assert record.user_id == "user-only"
    assert not hasattr(record, "conversation_id")


def test_record_factory_adds_nothing_when_neither_context_var_is_set(reload_app):
    reload_app()

    record = make_record()

    assert not hasattr(record, "conversation_id")
    assert not hasattr(record, "user_id")
    assert record.levelno == logging.INFO


def test_record_factory_preserves_the_arguments_of_the_wrapped_factory(reload_app):
    reload_app()

    record = make_record(conversation_id="conv-1")

    assert record.name == "test.logger"
    assert record.lineno == 42
    assert record.funcName == "some_function"


def test_record_factory_is_installed_globally_so_library_logs_are_enriched(reload_app, caplog):
    reload_app()
    app_module.conversation_id_var.set("conv-global")
    app_module.user_id_var.set("user-global")

    with caplog.at_level(logging.INFO, logger="some.third.party"):
        logging.getLogger("some.third.party").info("hello")

    record = next(r for r in caplog.records if r.getMessage() == "hello")
    assert record.conversation_id == "conv-global"
    assert record.user_id == "user-global"


# --------------------------------------------------------------------------- #
# build_app - composition
# --------------------------------------------------------------------------- #


def test_build_app_returns_a_titled_and_versioned_fastapi_instance():
    fastapi_app = app_module.build_app()

    assert fastapi_app.title == (
        "Agentic Applications for Unified Data Foundation Solution Accelerator"
    )
    assert fastapi_app.version == "1.0.0"


def test_build_app_registers_a_permissive_cors_middleware():
    fastapi_app = app_module.build_app()

    cors = next(
        m for m in fastapi_app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )

    assert cors.kwargs["allow_origins"] == ["*"]
    assert cors.kwargs["allow_credentials"] is True
    assert cors.kwargs["allow_methods"] == ["*"]
    assert cors.kwargs["allow_headers"] == ["*"]


def test_build_app_mounts_the_chat_and_history_routers_under_their_prefixes():
    paths = {route.path for route in app_module.build_app().routes}

    assert "/api/chat" in paths
    assert "/history/list" in paths
    assert "/health" in paths


def test_build_app_returns_a_new_instance_on_every_call():
    first = app_module.build_app()
    second = app_module.build_app()

    assert first is not second
    assert {r.path for r in first.routes} == {r.path for r in second.routes}


def test_module_level_app_is_the_instance_produced_by_build_app():
    assert app_module.app.title == (
        "Agentic Applications for Unified Data Foundation Solution Accelerator"
    )
    assert "/health" in {route.path for route in app_module.app.routes}


# --------------------------------------------------------------------------- #
# build_app - HTTP behaviour through the ASGI stack
# --------------------------------------------------------------------------- #


def test_health_endpoint_reports_healthy():
    with TestClient(app_module.build_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_endpoint_answers_cors_preflight_with_credentials_allowed():
    with TestClient(app_module.build_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "https://client.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] in ("*", "https://client.example.com")
    assert "GET" in response.headers["access-control-allow-methods"]


def test_the_middleware_lets_a_request_with_trace_headers_reach_the_endpoint():
    fastapi_app = app_module.build_app()
    span = make_span()

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        with TestClient(fastapi_app) as client:
            response = client.get("/health", headers={"x-ms-client-principal-id": "user-http"})

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert attributes_of(span)["user_id"] == "user-http"


# --------------------------------------------------------------------------- #
# attach_trace_attributes - user id
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_middleware_records_the_user_id_header_on_the_span_and_context(dispatch):
    span = make_span()
    call_next = AsyncMock(return_value="downstream-response")
    request = FakeRequest(headers={"x-ms-client-principal-id": "user-42"})

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        response = await dispatch(request, call_next)

    assert response == "downstream-response"
    assert app_module.user_id_var.get("") == "user-42"
    assert attributes_of(span) == {"user_id": "user-42"}
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_middleware_leaves_the_user_context_untouched_without_the_header(dispatch):
    app_module.user_id_var.set("")
    span = make_span()
    call_next = AsyncMock(return_value="downstream-response")

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(FakeRequest(), call_next)

    assert app_module.user_id_var.get("") == ""
    span.set_attribute.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_ignores_an_empty_user_id_header(dispatch):
    app_module.user_id_var.set("")
    span = make_span()

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(
            FakeRequest(headers={"x-ms-client-principal-id": ""}), AsyncMock(return_value=None)
        )

    assert app_module.user_id_var.get("") == ""
    span.set_attribute.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_sets_the_context_var_even_when_the_span_is_not_recording(dispatch):
    span = make_span(recording=False)

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(
            FakeRequest(
                method="POST",
                headers={"x-ms-client-principal-id": "user-99"},
                body=b'{"conversation_id": "conv-99"}',
            ),
            AsyncMock(return_value=None),
        )

    assert app_module.user_id_var.get("") == "user-99"
    assert app_module.conversation_id_var.get("") == "conv-99"
    span.set_attribute.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_tolerates_a_missing_span(dispatch):
    call_next = AsyncMock(return_value="downstream-response")

    with patch.object(app_module.trace, "get_current_span", return_value=None):
        response = await dispatch(
            FakeRequest(
                method="POST",
                headers={"x-ms-client-principal-id": "user-7"},
                body=b'{"conversation_id": "conv-7"}',
            ),
            call_next,
        )

    assert response == "downstream-response"
    assert app_module.user_id_var.get("") == "user-7"
    assert app_module.conversation_id_var.get("") == "conv-7"


# --------------------------------------------------------------------------- #
# attach_trace_attributes - conversation id
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.asyncio
async def test_middleware_extracts_the_conversation_id_from_mutating_requests(method, dispatch):
    span = make_span()
    request = FakeRequest(method=method, body=json.dumps({"conversation_id": "conv-5"}).encode())

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(request, AsyncMock(return_value=None))

    assert app_module.conversation_id_var.get("") == "conv-5"
    assert attributes_of(span) == {"conversation_id": "conv-5"}
    assert request.body_reads == 1


@pytest.mark.parametrize("method", ["GET", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.asyncio
async def test_middleware_never_reads_the_body_of_non_mutating_requests(method, dispatch):
    app_module.conversation_id_var.set("")
    request = FakeRequest(method=method, body=b'{"conversation_id": "conv-ignored"}')

    with patch.object(app_module.trace, "get_current_span", return_value=make_span()):
        await dispatch(request, AsyncMock(return_value=None))

    assert request.body_reads == 0
    assert app_module.conversation_id_var.get("") == ""


@pytest.mark.asyncio
async def test_middleware_sets_both_attributes_when_user_and_conversation_are_present(dispatch):
    span = make_span()
    request = FakeRequest(
        method="POST",
        headers={"x-ms-client-principal-id": "user-1"},
        body=b'{"conversation_id": "conv-1", "messages": []}',
    )

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(request, AsyncMock(return_value=None))

    assert attributes_of(span) == {"user_id": "user-1", "conversation_id": "conv-1"}
    assert app_module.user_id_var.get("") == "user-1"
    assert app_module.conversation_id_var.get("") == "conv-1"


@pytest.mark.parametrize(
    "body",
    [
        b'{"messages": [{"role": "user"}]}',
        b'{"conversation_id": ""}',
        b'{"conversation_id": null}',
    ],
)
@pytest.mark.asyncio
async def test_middleware_records_no_conversation_id_when_the_body_lacks_a_usable_one(
    body, dispatch
):
    app_module.conversation_id_var.set("")
    span = make_span()

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(
            FakeRequest(method="POST", body=body), AsyncMock(return_value=None)
        )

    assert app_module.conversation_id_var.get("") == ""
    assert "conversation_id" not in attributes_of(span)


@pytest.mark.asyncio
async def test_middleware_skips_parsing_when_the_request_body_is_empty(dispatch, caplog):
    app_module.conversation_id_var.set("")
    span = make_span()
    request = FakeRequest(method="POST", body=b"")

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        with caplog.at_level(logging.DEBUG):
            await dispatch(request, AsyncMock(return_value=None))

    assert request.body_reads == 1
    assert app_module.conversation_id_var.get("") == ""
    span.set_attribute.assert_not_called()
    # An empty body must short-circuit, not fall into the JSON-decode failure path.
    assert not any(
        "Failed to parse request body" in record.getMessage() for record in caplog.records
    )


# --------------------------------------------------------------------------- #
# attach_trace_attributes - fail-open error handling
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_middleware_fails_open_and_still_calls_downstream_on_malformed_json(
    dispatch, caplog
):
    app_module.conversation_id_var.set("")
    call_next = AsyncMock(return_value="downstream-response")
    span = make_span()

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        with caplog.at_level(logging.DEBUG):
            response = await dispatch(
                FakeRequest(method="POST", body=b"{not-json"), call_next
            )

    assert response == "downstream-response"
    assert app_module.conversation_id_var.get("") == ""
    assert "conversation_id" not in attributes_of(span)
    call_next.assert_awaited_once()
    failures = [
        record
        for record in caplog.records
        if "Failed to parse request body for trace attribute enrichment." in record.getMessage()
    ]
    assert len(failures) == 1
    assert failures[0].levelno == logging.DEBUG
    assert failures[0].exc_info is not None


@pytest.mark.asyncio
async def test_middleware_keeps_the_user_id_attribute_when_body_parsing_fails(dispatch):
    span = make_span()
    request = FakeRequest(
        method="POST", headers={"x-ms-client-principal-id": "user-3"}, body=b"<html>"
    )

    with patch.object(app_module.trace, "get_current_span", return_value=span):
        await dispatch(request, AsyncMock(return_value=None))

    assert attributes_of(span) == {"user_id": "user-3"}
    assert app_module.user_id_var.get("") == "user-3"


@pytest.mark.asyncio
async def test_middleware_fails_open_when_reading_the_body_raises(dispatch):
    call_next = AsyncMock(return_value="downstream-response")
    request = FakeRequest(method="POST", body_error=RuntimeError("stream already consumed"))

    with patch.object(app_module.trace, "get_current_span", return_value=make_span()):
        response = await dispatch(request, call_next)

    assert response == "downstream-response"
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_middleware_fails_open_when_the_body_is_a_json_scalar(dispatch):
    app_module.conversation_id_var.set("")
    call_next = AsyncMock(return_value="downstream-response")

    with patch.object(app_module.trace, "get_current_span", return_value=make_span()):
        response = await dispatch(FakeRequest(method="POST", body=b'"a string"'), call_next)

    assert response == "downstream-response"
    assert app_module.conversation_id_var.get("") == ""


@pytest.mark.asyncio
async def test_middleware_propagates_downstream_exceptions_instead_of_swallowing_them(dispatch):
    call_next = AsyncMock(side_effect=RuntimeError("endpoint blew up"))

    with patch.object(app_module.trace, "get_current_span", return_value=make_span()):
        with pytest.raises(RuntimeError, match="endpoint blew up"):
            await dispatch(FakeRequest(method="POST", body=b"{}"), call_next)


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_context_vars_default_to_empty_strings():
    fresh_context = contextvars.Context()

    assert fresh_context.run(app_module.conversation_id_var.get) == ""
    assert fresh_context.run(app_module.user_id_var.get) == ""
    assert app_module.conversation_id_var.name == "conversation_id"
    assert app_module.user_id_var.name == "user_id"


def test_importing_the_module_never_starts_the_uvicorn_server(reload_app):
    """The uvicorn.run(...) call is guarded by __name__ == "__main__"."""
    with patch.object(app_module.uvicorn, "run") as run:
        reloaded, _, _, _ = reload_app()

    run.assert_not_called()
    assert reloaded.__name__ == "app"
