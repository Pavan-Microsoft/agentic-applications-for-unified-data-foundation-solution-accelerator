"""Unit tests for src/api/python/auth/azure_credential_utils.py.

Every Azure Identity credential class is patched in the module namespace, so no
real credential object is constructed and no token endpoint is contacted.
Environment variables are stubbed with ``monkeypatch``.
"""

import logging
from unittest.mock import patch

import pytest

from auth import azure_credential_utils


LOGGER_NAME = "auth.azure_credential_utils"

OBO_ENV = {
    "OBO_CLIENT_ID": "obo-client",
    "OBO_CLIENT_SECRET": "obo-secret",
    "OBO_TENANT_ID": "obo-tenant",
}


@pytest.fixture(autouse=True)
def clean_credential_env(monkeypatch):
    """Start every test from an unset environment."""
    for name in ("APP_ENV", *OBO_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def async_credentials():
    """Patch all three async credential classes used by the module."""
    with patch.object(azure_credential_utils, "AioOnBehalfOfCredential") as obo, patch.object(
        azure_credential_utils, "AioDefaultAzureCredential"
    ) as default, patch.object(
        azure_credential_utils, "AioManagedIdentityCredential"
    ) as managed:
        yield {"obo": obo, "default": default, "managed": managed}


@pytest.fixture
def sync_credentials():
    """Patch both synchronous credential classes used by the module."""
    with patch.object(azure_credential_utils, "DefaultAzureCredential") as default, patch.object(
        azure_credential_utils, "ManagedIdentityCredential"
    ) as managed:
        yield {"default": default, "managed": managed}


# --------------------------------------------------------------------------- #
# get_azure_credential_async - On-Behalf-Of branch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_async_uses_obo_credential_when_assertion_and_full_obo_config_present(
    monkeypatch, async_credentials
):
    for name, value in OBO_ENV.items():
        monkeypatch.setenv(name, value)

    credential = await azure_credential_utils.get_azure_credential_async(
        client_id="mi-client", user_assertion="user-token"
    )

    assert credential is async_credentials["obo"].return_value
    async_credentials["obo"].assert_called_once_with(
        tenant_id="obo-tenant",
        client_id="obo-client",
        client_secret="obo-secret",
        user_assertion="user-token",
    )
    async_credentials["managed"].assert_not_called()
    async_credentials["default"].assert_not_called()


@pytest.mark.asyncio
async def test_async_obo_branch_logs_that_it_is_using_on_behalf_of(
    monkeypatch, async_credentials, caplog
):
    for name, value in OBO_ENV.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await azure_credential_utils.get_azure_credential_async(user_assertion="user-token")

    messages = [record.getMessage() for record in caplog.records]
    assert "Using On-Behalf-Of Credential for user assertion" in messages
    assert async_credentials["obo"].call_count == 1


@pytest.mark.parametrize("missing", sorted(OBO_ENV))
@pytest.mark.asyncio
async def test_async_falls_back_to_managed_identity_when_an_obo_setting_is_missing(
    missing, monkeypatch, async_credentials, caplog
):
    for name, value in OBO_ENV.items():
        if name != missing:
            monkeypatch.setenv(name, value)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        credential = await azure_credential_utils.get_azure_credential_async(
            client_id="mi-client", user_assertion="user-token"
        )

    assert credential is async_credentials["managed"].return_value
    async_credentials["obo"].assert_not_called()
    async_credentials["managed"].assert_called_once_with(client_id="mi-client")
    assert any(
        "OBO requested but OBO_CLIENT_ID, OBO_CLIENT_SECRET, or OBO_TENANT_ID not configured"
        == record.getMessage()
        and record.levelno == logging.WARNING
        for record in caplog.records
    )


@pytest.mark.parametrize("empty_var", sorted(OBO_ENV))
@pytest.mark.asyncio
async def test_async_treats_an_empty_string_obo_setting_as_unconfigured(
    empty_var, monkeypatch, async_credentials
):
    for name, value in OBO_ENV.items():
        monkeypatch.setenv(name, "" if name == empty_var else value)

    credential = await azure_credential_utils.get_azure_credential_async(
        user_assertion="user-token"
    )

    assert credential is async_credentials["managed"].return_value
    async_credentials["obo"].assert_not_called()


@pytest.mark.asyncio
async def test_async_does_not_trim_obo_settings_so_whitespace_still_counts_as_configured(
    monkeypatch, async_credentials
):
    monkeypatch.setenv("OBO_CLIENT_ID", "obo-client")
    monkeypatch.setenv("OBO_TENANT_ID", "obo-tenant")
    monkeypatch.setenv("OBO_CLIENT_SECRET", "   ")

    credential = await azure_credential_utils.get_azure_credential_async(
        user_assertion="user-token"
    )

    assert credential is async_credentials["obo"].return_value
    async_credentials["obo"].assert_called_once_with(
        tenant_id="obo-tenant",
        client_id="obo-client",
        client_secret="   ",
        user_assertion="user-token",
    )


@pytest.mark.asyncio
async def test_async_ignores_obo_configuration_when_no_user_assertion_is_supplied(
    monkeypatch, async_credentials, caplog
):
    for name, value in OBO_ENV.items():
        monkeypatch.setenv(name, value)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        credential = await azure_credential_utils.get_azure_credential_async(
            client_id="mi-client"
        )

    assert credential is async_credentials["managed"].return_value
    async_credentials["obo"].assert_not_called()
    assert caplog.records == []


@pytest.mark.parametrize("assertion", ["", None])
@pytest.mark.asyncio
async def test_async_empty_user_assertion_skips_the_obo_branch_entirely(
    assertion, monkeypatch, async_credentials
):
    for name, value in OBO_ENV.items():
        monkeypatch.setenv(name, value)

    credential = await azure_credential_utils.get_azure_credential_async(
        user_assertion=assertion
    )

    assert credential is async_credentials["managed"].return_value
    async_credentials["obo"].assert_not_called()


@pytest.mark.asyncio
async def test_async_obo_fallback_in_dev_uses_the_default_credential(
    monkeypatch, async_credentials
):
    monkeypatch.setenv("APP_ENV", "dev")

    credential = await azure_credential_utils.get_azure_credential_async(
        user_assertion="user-token"
    )

    assert credential is async_credentials["default"].return_value
    async_credentials["obo"].assert_not_called()
    async_credentials["managed"].assert_not_called()


# --------------------------------------------------------------------------- #
# get_azure_credential_async - environment branch
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("app_env", ["dev", "DEV", "Dev", "dEv"])
@pytest.mark.asyncio
async def test_async_dev_environment_uses_default_azure_credential(
    app_env, monkeypatch, async_credentials
):
    monkeypatch.setenv("APP_ENV", app_env)

    credential = await azure_credential_utils.get_azure_credential_async(client_id="mi-client")

    assert credential is async_credentials["default"].return_value
    async_credentials["default"].assert_called_once_with()
    async_credentials["managed"].assert_not_called()


@pytest.mark.asyncio
async def test_async_unset_app_env_defaults_to_managed_identity(async_credentials):
    credential = await azure_credential_utils.get_azure_credential_async()

    assert credential is async_credentials["managed"].return_value
    async_credentials["managed"].assert_called_once_with(client_id=None)
    async_credentials["default"].assert_not_called()


@pytest.mark.parametrize("app_env", ["prod", "PROD", "production", "development", "staging"])
@pytest.mark.asyncio
async def test_async_non_dev_environments_use_managed_identity(
    app_env, monkeypatch, async_credentials
):
    monkeypatch.setenv("APP_ENV", app_env)

    credential = await azure_credential_utils.get_azure_credential_async(client_id="mi-client")

    assert credential is async_credentials["managed"].return_value
    async_credentials["managed"].assert_called_once_with(client_id="mi-client")
    async_credentials["default"].assert_not_called()


# --------------------------------------------------------------------------- #
# get_azure_credential (synchronous)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("app_env", ["dev", "DEV", "Dev"])
def test_sync_dev_environment_uses_default_azure_credential(
    app_env, monkeypatch, sync_credentials
):
    monkeypatch.setenv("APP_ENV", app_env)

    credential = azure_credential_utils.get_azure_credential(client_id="mi-client")

    assert credential is sync_credentials["default"].return_value
    sync_credentials["default"].assert_called_once_with()
    sync_credentials["managed"].assert_not_called()


def test_sync_unset_app_env_defaults_to_managed_identity(sync_credentials):
    credential = azure_credential_utils.get_azure_credential()

    assert credential is sync_credentials["managed"].return_value
    sync_credentials["managed"].assert_called_once_with(client_id=None)
    sync_credentials["default"].assert_not_called()


@pytest.mark.parametrize("app_env", ["prod", "production", "PROD", "test"])
def test_sync_non_dev_environments_use_managed_identity_with_the_given_client_id(
    app_env, monkeypatch, sync_credentials
):
    monkeypatch.setenv("APP_ENV", app_env)

    credential = azure_credential_utils.get_azure_credential(client_id="mi-client")

    assert credential is sync_credentials["managed"].return_value
    sync_credentials["managed"].assert_called_once_with(client_id="mi-client")
    sync_credentials["default"].assert_not_called()


def test_sync_and_async_paths_use_distinct_credential_classes(
    monkeypatch, sync_credentials, async_credentials
):
    """The sync helper must never return an aio credential (and vice versa)."""
    monkeypatch.setenv("APP_ENV", "prod")

    sync_credential = azure_credential_utils.get_azure_credential(client_id="mi-client")

    assert sync_credential is sync_credentials["managed"].return_value
    assert sync_credential is not async_credentials["managed"].return_value
    async_credentials["managed"].assert_not_called()


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_logger_is_named_after_the_module():
    assert azure_credential_utils.logger.name == LOGGER_NAME


def test_get_azure_credential_async_is_a_coroutine_function():
    import inspect

    assert inspect.iscoroutinefunction(azure_credential_utils.get_azure_credential_async)
    assert not inspect.iscoroutinefunction(azure_credential_utils.get_azure_credential)
