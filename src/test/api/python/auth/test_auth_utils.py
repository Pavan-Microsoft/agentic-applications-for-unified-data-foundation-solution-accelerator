"""Unit tests for src/api/python/auth/auth_utils.py.

The module is pure header/JSON parsing, so the only "external" dependencies are
the request-header mapping and the ``sample_user`` development fixture, both of
which are supplied directly by the tests. No network, Azure or file-system
access occurs.
"""

import base64
import json
import logging

import pytest

from auth import auth_utils


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


PRINCIPAL_ID = "11111111-2222-3333-4444-555555555555"


def easyauth_headers(**overrides):
    """Canonical EasyAuth header set, with per-test overrides."""
    headers = {
        "x-ms-client-principal-id": PRINCIPAL_ID,
        "x-ms-client-principal-name": "ada@contoso.com",
        "x-ms-client-principal-idp": "aad",
        "x-ms-client-principal": "eyJ0aWQiOiAidGVuYW50In0=",
        "x-ms-token-aad-id-token": "id-token-value",
    }
    headers.update(overrides)
    return {key: value for key, value in headers.items() if value is not None}


def b64_principal(payload):
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")


# --------------------------------------------------------------------------- #
# get_authenticated_user_details - identity mapping
# --------------------------------------------------------------------------- #


def test_maps_every_easyauth_header_to_its_user_object_field():
    user = auth_utils.get_authenticated_user_details(easyauth_headers())

    assert user["user_principal_id"] == PRINCIPAL_ID
    assert user["user_name"] == "ada@contoso.com"
    assert user["auth_provider"] == "aad"
    assert user["auth_token"] == "id-token-value"
    assert user["aad_id_token"] == "id-token-value"
    assert user["client_principal_b64"] == "eyJ0aWQiOiAidGVuYW50In0="


def test_returns_exactly_the_seven_documented_user_object_keys():
    user = auth_utils.get_authenticated_user_details(easyauth_headers())

    assert set(user) == {
        "user_principal_id",
        "user_name",
        "auth_provider",
        "auth_token",
        "client_principal_b64",
        "aad_id_token",
        "aad_access_token",
    }


def test_normalizes_mixed_case_header_names_before_lookup():
    headers = {
        "X-MS-CLIENT-PRINCIPAL-ID": PRINCIPAL_ID,
        "X-Ms-Client-Principal-Name": "grace@contoso.com",
        "X-Ms-Client-Principal-Idp": "github",
        "X-Ms-Token-Aad-Id-Token": "mixed-case-id-token",
    }

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["user_principal_id"] == PRINCIPAL_ID
    assert user["user_name"] == "grace@contoso.com"
    assert user["auth_provider"] == "github"
    assert user["aad_id_token"] == "mixed-case-id-token"


def test_optional_headers_missing_yields_none_without_dropping_the_principal_id():
    user = auth_utils.get_authenticated_user_details({"x-ms-client-principal-id": PRINCIPAL_ID})

    assert user["user_principal_id"] == PRINCIPAL_ID
    assert user["user_name"] is None
    assert user["auth_provider"] is None
    assert user["auth_token"] is None
    assert user["aad_id_token"] is None
    assert user["client_principal_b64"] is None


# --------------------------------------------------------------------------- #
# get_authenticated_user_details - development fallback
# --------------------------------------------------------------------------- #


def test_falls_back_to_the_sample_user_when_the_principal_header_is_absent():
    user = auth_utils.get_authenticated_user_details({"host": "localhost:8000"})

    assert user["user_principal_id"] == "00000000-0000-0000-0000-000000000000"
    assert user["user_name"] == "testusername@constoso.com"
    assert user["auth_provider"] == "aad"
    assert user["aad_id_token"] == "your_aad_id_token"


def test_fallback_ignores_unrelated_headers_instead_of_mixing_them_in():
    user = auth_utils.get_authenticated_user_details(
        {"x-ms-client-principal-name": "spoofed@contoso.com"}
    )

    assert user["user_name"] == "testusername@constoso.com"
    assert user["user_principal_id"] == "00000000-0000-0000-0000-000000000000"


def test_fallback_identity_still_honors_a_real_bearer_access_token():
    user = auth_utils.get_authenticated_user_details({"authorization": "Bearer dev-obo-token"})

    assert user["user_principal_id"] == "00000000-0000-0000-0000-000000000000"
    assert user["aad_access_token"] == "dev-obo-token"


def test_an_empty_header_mapping_uses_the_fallback_and_has_no_access_token():
    user = auth_utils.get_authenticated_user_details({})

    assert user["user_principal_id"] == "00000000-0000-0000-0000-000000000000"
    assert user["aad_access_token"] is None


# --------------------------------------------------------------------------- #
# get_authenticated_user_details - access-token precedence chain
# --------------------------------------------------------------------------- #


def test_easyauth_access_token_wins_over_zumo_and_bearer():
    headers = easyauth_headers(
        **{
            "x-ms-token-aad-access-token": "easyauth-token",
            "x-zumo-auth": "zumo-token",
            "authorization": "Bearer bearer-token",
        }
    )

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "easyauth-token"


def test_zumo_token_wins_over_bearer_when_easyauth_token_is_absent():
    headers = easyauth_headers(
        **{"x-zumo-auth": "zumo-token", "authorization": "Bearer bearer-token"}
    )

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "zumo-token"


def test_bearer_token_is_used_when_it_is_the_only_source():
    headers = easyauth_headers(**{"authorization": "Bearer bearer-token"})

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "bearer-token"


def test_bearer_token_is_stripped_of_surrounding_whitespace():
    headers = easyauth_headers(**{"authorization": "Bearer   padded-token   "})

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "padded-token"


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
def test_bearer_scheme_is_matched_case_insensitively(scheme):
    headers = easyauth_headers(**{"authorization": f"{scheme} case-token"})

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "case-token"


def test_authorization_header_is_found_even_when_its_name_is_capitalized():
    headers = easyauth_headers()
    headers["Authorization"] = "Bearer capitalized-header-token"

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "capitalized-header-token"


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic dXNlcjpwYXNz",
        "Negotiate abcdef",
        "bearertoken-without-space",
    ],
)
def test_non_bearer_authorization_schemes_produce_no_access_token(authorization):
    headers = easyauth_headers(**{"authorization": authorization})

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] is None


@pytest.mark.parametrize("authorization", ["Bearer", "Bearer ", "Bearer    "])
def test_bearer_scheme_without_a_token_produces_no_access_token(authorization):
    headers = easyauth_headers(**{"authorization": authorization})

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] is None


def test_missing_authorization_header_produces_no_access_token():
    user = auth_utils.get_authenticated_user_details(easyauth_headers())

    assert user["aad_access_token"] is None
    assert user["user_principal_id"] == PRINCIPAL_ID


@pytest.mark.parametrize("empty_value", ["", None])
def test_empty_easyauth_access_token_falls_through_to_the_zumo_header(empty_value):
    headers = easyauth_headers()
    if empty_value is not None:
        headers["x-ms-token-aad-access-token"] = empty_value
    headers["x-zumo-auth"] = "zumo-token"

    user = auth_utils.get_authenticated_user_details(headers)

    assert user["aad_access_token"] == "zumo-token"


# --------------------------------------------------------------------------- #
# get_tenantid
# --------------------------------------------------------------------------- #


def test_extracts_the_tenant_id_from_a_base64_encoded_client_principal():
    encoded = b64_principal({"tid": "tenant-abc", "oid": "object-123"})

    assert auth_utils.get_tenantid(encoded) == "tenant-abc"


def test_returns_none_when_the_decoded_principal_has_no_tid_claim():
    encoded = b64_principal({"oid": "object-123"})

    assert auth_utils.get_tenantid(encoded) is None


def test_returns_empty_string_and_logs_when_the_value_is_not_valid_base64(caplog):
    with caplog.at_level(logging.ERROR):
        tenant_id = auth_utils.get_tenantid("!!!not-base64!!!")

    assert tenant_id == ""
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_returns_empty_string_and_logs_when_the_decoded_payload_is_not_json(caplog):
    encoded = base64.b64encode(b"plain text, not json").decode("utf-8")

    with caplog.at_level(logging.ERROR):
        tenant_id = auth_utils.get_tenantid(encoded)

    assert tenant_id == ""
    assert any("JSON" in record.getMessage() or record.exc_info for record in caplog.records)


def test_returns_empty_string_and_logs_when_the_payload_is_not_utf8(caplog):
    encoded = base64.b64encode(b"\xff\xfe\xfa\xfb").decode("utf-8")

    with caplog.at_level(logging.ERROR):
        tenant_id = auth_utils.get_tenantid(encoded)

    assert tenant_id == ""
    assert len(caplog.records) == 1


def test_returns_empty_string_when_the_decoded_principal_is_a_json_list(caplog):
    encoded = base64.b64encode(b'["tid"]').decode("utf-8")

    with caplog.at_level(logging.ERROR):
        tenant_id = auth_utils.get_tenantid(encoded)

    assert tenant_id == ""
    assert len(caplog.records) == 1


@pytest.mark.parametrize("falsy", ["", None, 0])
def test_falsy_client_principal_short_circuits_without_logging(falsy, caplog):
    with caplog.at_level(logging.DEBUG):
        tenant_id = auth_utils.get_tenantid(falsy)

    assert tenant_id == ""
    assert caplog.records == []


def test_tenant_id_round_trips_from_the_header_produced_by_get_authenticated_user_details():
    encoded = b64_principal({"tid": "tenant-from-header"})
    user = auth_utils.get_authenticated_user_details(
        easyauth_headers(**{"x-ms-client-principal": encoded})
    )

    assert auth_utils.get_tenantid(user["client_principal_b64"]) == "tenant-from-header"
