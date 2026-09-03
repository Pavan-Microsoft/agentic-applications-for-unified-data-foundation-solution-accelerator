"""Unit tests for src/api/python/auth/sample_user.py.

``sample_user`` is the development-mode header fixture that
``auth.auth_utils.get_authenticated_user_details`` falls back to when the
EasyAuth principal header is absent. These tests pin the concrete values and
the key contract that fallback depends on. No external dependency is touched.
"""

import base64
import binascii
import json

from auth import auth_utils
from auth.sample_user import sample_user


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_sample_user_is_a_non_empty_mapping_of_header_strings():
    assert isinstance(sample_user, dict)
    assert len(sample_user) == 37
    assert all(isinstance(key, str) for key in sample_user)
    assert all(isinstance(value, str) for value in sample_user.values())


def test_sample_user_header_names_are_unique_when_normalized_to_lowercase():
    lowered = [key.lower() for key in sample_user]

    assert len(set(lowered)) == len(lowered)


# --------------------------------------------------------------------------- #
# Identity values consumed by auth_utils
# --------------------------------------------------------------------------- #


def test_sample_user_exposes_the_easyauth_principal_identity_values():
    assert sample_user["X-Ms-Client-Principal-Id"] == "00000000-0000-0000-0000-000000000000"
    assert sample_user["X-Ms-Client-Principal-Name"] == "testusername@constoso.com"
    assert sample_user["X-Ms-Client-Principal-Idp"] == "aad"
    assert sample_user["X-Ms-Token-Aad-Id-Token"] == "your_aad_id_token"
    assert sample_user["X-Ms-Client-Principal"] == "your_base_64_encoded_token"


def test_sample_user_supplies_every_key_auth_utils_reads_after_lowercasing():
    lowered = {key.lower() for key in sample_user}

    required = {
        "x-ms-client-principal-id",
        "x-ms-client-principal-name",
        "x-ms-client-principal-idp",
        "x-ms-token-aad-id-token",
        "x-ms-client-principal",
    }

    assert required.issubset(lowered)


def test_sample_user_drives_the_dev_fallback_to_the_expected_user_object():
    user = auth_utils.get_authenticated_user_details({})

    assert user["user_principal_id"] == "00000000-0000-0000-0000-000000000000"
    assert user["user_name"] == "testusername@constoso.com"
    assert user["auth_provider"] == "aad"
    assert user["aad_id_token"] == "your_aad_id_token"
    assert user["client_principal_b64"] == "your_base_64_encoded_token"


# --------------------------------------------------------------------------- #
# Absent-by-design headers
# --------------------------------------------------------------------------- #


def test_sample_user_carries_no_access_token_header_so_obo_stays_disabled():
    lowered = {key.lower() for key in sample_user}

    assert "x-ms-token-aad-access-token" not in lowered
    assert "x-zumo-auth" not in lowered
    assert "authorization" not in lowered
    assert auth_utils.get_authenticated_user_details({})["aad_access_token"] is None


def test_sample_user_client_principal_is_a_placeholder_that_yields_no_tenant_id():
    placeholder = sample_user["X-Ms-Client-Principal"]

    try:
        decoded = base64.b64decode(placeholder, validate=True)
        json.loads(decoded.decode("utf-8"))
        decodes_to_a_principal = True
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decodes_to_a_principal = False

    assert decodes_to_a_principal is False
    assert auth_utils.get_tenantid(placeholder) == ""


def test_sample_user_hostnames_are_placeholders_not_real_endpoints():
    assert sample_user["Host"] == "your_app_service.azurewebsites.net"
    assert sample_user["Disguised-Host"] == "your_app_service.azurewebsites.net"
    assert sample_user["Origin"] == "https://your_app_service.azurewebsites.net"
