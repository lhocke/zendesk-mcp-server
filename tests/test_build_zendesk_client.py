"""Tests for build_zendesk_client (the env-driven mode-selection factory).

Tests import build_zendesk_client directly from zendesk_client.py rather than
from server.py — server.py calls build_zendesk_client at module-import time, so
importing it would either trigger a real call or require pre-setting env vars
across the entire test process. Keeping the factory in zendesk_client.py and
testing it there avoids that coupling.
"""
from unittest.mock import MagicMock

import pytest

from zendesk_mcp_server import zendesk_client as zc_module
from zendesk_mcp_server.zendesk_client import ZendeskClient, build_zendesk_client


def test_oauth_mode_selected_when_client_id_set(clean_env, monkeypatch, mock_token_file, mocker):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    monkeypatch.setenv("ZENDESK_CLIENT_SECRET", "csec")
    mock_token_file("example", {
        "subdomain": "example",
        "access_token": "tok",
        "refresh_token": "rfsh",
        "token_type": "Bearer",
        "expires_at": None,
    })
    # Stub OAuth2Session so OAuthTokenManager init doesn't try to construct anything weird
    mocker.patch("zendesk_mcp_server.oauth.OAuth2Session")

    client = build_zendesk_client()
    assert isinstance(client, ZendeskClient)
    assert client._token_manager is not None


def test_api_token_mode_selected_when_no_client_id(clean_env, monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_EMAIL", "a@b.com")
    monkeypatch.setenv("ZENDESK_API_KEY", "tok")

    client = build_zendesk_client()
    assert isinstance(client, ZendeskClient)
    assert client._token_manager is None
    assert client.subdomain == "example"


def test_empty_string_client_id_does_not_trigger_oauth_mode(clean_env, monkeypatch):
    """Truthy check on ZENDESK_CLIENT_ID — empty string falls through to API-token."""
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "")  # explicitly empty
    monkeypatch.setenv("ZENDESK_EMAIL", "a@b.com")
    monkeypatch.setenv("ZENDESK_API_KEY", "tok")

    client = build_zendesk_client()
    assert client._token_manager is None  # API-token mode


def test_missing_subdomain_raises_clearly(clean_env):
    with pytest.raises(EnvironmentError, match="ZENDESK_SUBDOMAIN"):
        build_zendesk_client()


def test_oauth_mode_missing_token_file_raises_with_actionable_message(
    clean_env, tmp_home, monkeypatch, mocker
):
    """Hard-fail invariant: no silent fallback to API-token mode if OAuth env
    is set but the token file is missing."""
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    monkeypatch.setenv("ZENDESK_CLIENT_SECRET", "csec")
    # No token file written → OAuthTokenManager.__init__ raises FileNotFoundError
    mocker.patch("zendesk_mcp_server.oauth.OAuth2Session")

    with pytest.raises(EnvironmentError, match="zendesk-auth"):
        build_zendesk_client()


def test_oauth_mode_missing_client_secret_raises(clean_env, monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    # ZENDESK_CLIENT_SECRET intentionally not set
    with pytest.raises(EnvironmentError, match="ZENDESK_CLIENT_SECRET"):
        build_zendesk_client()


def test_api_token_mode_missing_email_raises(clean_env, monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_API_KEY", "tok")
    # ZENDESK_EMAIL not set
    with pytest.raises(EnvironmentError, match="ZENDESK_EMAIL"):
        build_zendesk_client()


def test_api_token_mode_missing_api_key_raises(clean_env, monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_EMAIL", "a@b.com")
    # ZENDESK_API_KEY not set
    with pytest.raises(EnvironmentError, match="ZENDESK_API_KEY"):
        build_zendesk_client()
