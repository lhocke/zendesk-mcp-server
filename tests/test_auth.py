"""Tests for the zendesk-auth CLI."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from zendesk_mcp_server import auth, token_store


@pytest.fixture(autouse=True)
def short_callback_timeout(monkeypatch):
    """Keep tests fast even when no callback ever arrives."""
    monkeypatch.setattr(auth, "CALLBACK_TIMEOUT_SECONDS", 3)


# --- env validation ---

def test_missing_subdomain_exits_1(clean_env, capsys):
    rc = auth.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ZENDESK_SUBDOMAIN" in err


def test_missing_client_id_exits_1_with_readme_pointer(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    rc = auth.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ZENDESK_CLIENT_ID" in err
    assert "README" in err


def test_missing_client_secret_exits_1(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    # no ZENDESK_CLIENT_SECRET
    rc = auth.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ZENDESK_CLIENT_SECRET" in err


# --- subdomain regex ---

@pytest.mark.parametrize(
    "bad",
    [
        "https://x.zendesk.com",  # full URL
        "x.zendesk.com",  # has dot
        "foo/",  # trailing slash
        "-foo",  # leading hyphen
        "foo-",  # trailing hyphen
        "Foo",  # uppercase
        "x",  # single char (regex requires ≥2)
        "FOO BAR",  # space
    ],
)
def test_subdomain_regex_rejects_bad_inputs(bad, clean_env, monkeypatch, capsys):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", bad)
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    monkeypatch.setenv("ZENDESK_CLIENT_SECRET", "csec")
    rc = auth.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ZENDESK_SUBDOMAIN" in err
    assert auth.SUBDOMAIN_PATTERN_HUMAN in err


@pytest.mark.parametrize("good", ["a1", "acme", "acme-support", "x9z"])
def test_subdomain_regex_accepts_good_inputs(good):
    assert auth.SUBDOMAIN_RE.fullmatch(good) is not None


# --- --check subcommand ---

def test_check_with_valid_token_prints_subdomain_and_expiry(
    clean_env, monkeypatch, mock_token_file, capsys
):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    mock_token_file("example", {
        "subdomain": "example",
        "access_token": "tok",
        "refresh_token": "rfsh",
        "token_type": "Bearer",
        "expires_at": 1735689600,  # 2025-01-01 UTC
    })
    rc = auth.main(["--check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Subdomain: example" in out
    assert "2025-01-01" in out


def test_check_with_null_expiry_prints_no_expiry_message(
    clean_env, monkeypatch, mock_token_file, capsys
):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    mock_token_file("example", {
        "subdomain": "example",
        "access_token": "tok",
        "refresh_token": "rfsh",
        "token_type": "Bearer",
        "expires_at": None,
    })
    rc = auth.main(["--check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no expiry — refresh on 401 only" in out


def test_check_with_missing_token_file_exits_1(clean_env, monkeypatch, tmp_home, capsys):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    rc = auth.main(["--check"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "zendesk-auth" in err.lower()


# --- port-in-use error ---

def test_port_in_use_exits_1_with_prescribed_message(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    monkeypatch.setenv("ZENDESK_CLIENT_SECRET", "csec")

    # Bind a socket to a free port to simulate the "port already in use" case
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    port = blocker.getsockname()[1]
    blocker.listen(1)
    try:
        rc = auth.main([f"--port={port}"])
        assert rc == 1
        err = capsys.readouterr().err
        assert str(port) in err
        assert "redirect URI" in err  # "Make sure ... is registered as a redirect URI"
    finally:
        blocker.close()


# --- full happy-path flow ---

def _setup_oauth_env(monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "example")
    monkeypatch.setenv("ZENDESK_CLIENT_ID", "cid")
    monkeypatch.setenv("ZENDESK_CLIENT_SECRET", "csec")


def _mock_callback_server(mocker, *, code=None, exception=None):
    """Replace CallbackServer in auth.py with a mock that returns `code` from
    wait_for_code, or raises `exception`."""
    mock_cb = MagicMock()
    if exception is not None:
        mock_cb.wait_for_code.side_effect = exception
    else:
        mock_cb.wait_for_code.return_value = code
    mocker.patch.object(auth, "CallbackServer", return_value=mock_cb)
    return mock_cb


def _mock_token_exchange(mocker, *, token=None, exception=None):
    mock_session = MagicMock()
    if exception is not None:
        mock_session.fetch_token.side_effect = exception
    else:
        mock_session.fetch_token.return_value = token
    mocker.patch.object(auth, "OAuth2Session", return_value=mock_session)
    return mock_session


def test_happy_path_writes_token_and_prints_success_message(
    clean_env, monkeypatch, tmp_home, mocker, capsys
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="auth_code_xyz")
    _mock_token_exchange(mocker, token={
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "token_type": "Bearer",
        "scope": "read write",
        # Zendesk often omits expires_in — exercise that path
    })
    mocker.patch.object(auth, "webbrowser")

    rc = auth.main(["--no-browser"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Authenticated as example.zendesk.com" in out
    assert "Restart your MCP server" in out

    saved = token_store.load("example")
    assert saved["access_token"] == "new_access"
    assert saved["expires_at"] is None  # Zendesk didn't return expires_in
    assert saved["subdomain"] == "example"


def test_happy_path_with_expires_in_computes_expires_at(
    clean_env, monkeypatch, tmp_home, mocker
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="code")
    _mock_token_exchange(mocker, token={
        "access_token": "tok",
        "refresh_token": "r",
        "token_type": "Bearer",
        "expires_in": 3600,
    })
    mocker.patch.object(auth, "webbrowser")

    before = int(time.time())
    rc = auth.main(["--no-browser"])
    after = int(time.time())
    assert rc == 0

    saved = token_store.load("example")
    assert before + 3590 <= saved["expires_at"] <= after + 3610


def test_token_exchange_uses_correct_endpoint_and_pkce_args(
    clean_env, monkeypatch, tmp_home, mocker
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="auth_code_xyz")
    mock_session = _mock_token_exchange(mocker, token={
        "access_token": "tok",
        "refresh_token": "r",
        "token_type": "Bearer",
    })
    mocker.patch.object(auth, "webbrowser")

    auth.main(["--no-browser"])

    # Verify the token endpoint and that PKCE code_verifier was passed
    call_args = mock_session.fetch_token.call_args
    assert call_args.args[0] == "https://example.zendesk.com/oauth/tokens"
    assert call_args.kwargs["code"] == "auth_code_xyz"
    assert "code_verifier" in call_args.kwargs
    assert call_args.kwargs["redirect_uri"] == "http://127.0.0.1:47890/callback"


def test_no_browser_does_not_call_webbrowser_open(
    clean_env, monkeypatch, tmp_home, mocker
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="code")
    _mock_token_exchange(mocker, token={
        "access_token": "tok",
        "refresh_token": "r",
        "token_type": "Bearer",
    })
    mock_wb = mocker.patch.object(auth, "webbrowser")

    auth.main(["--no-browser"])
    mock_wb.open.assert_not_called()


def test_default_browser_open_is_called(
    clean_env, monkeypatch, tmp_home, mocker
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="code")
    _mock_token_exchange(mocker, token={
        "access_token": "tok",
        "refresh_token": "r",
        "token_type": "Bearer",
    })
    mock_wb = mocker.patch.object(auth, "webbrowser")

    auth.main([])
    assert mock_wb.open.call_count == 1
    url = mock_wb.open.call_args.args[0]
    assert url.startswith("https://example.zendesk.com/oauth/authorizations/new?")
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A47890%2Fcallback" in url


# --- error-path tests via mocked CallbackServer ---

def test_state_mismatch_exits_with_prescribed_message(
    clean_env, monkeypatch, tmp_home, mocker, capsys
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(
        mocker,
        exception=RuntimeError("state mismatch — possible CSRF or stale auth attempt"),
    )
    mocker.patch.object(auth, "webbrowser")

    rc = auth.main(["--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "state mismatch" in err


def test_callback_timeout_exits_1_with_prescribed_message(
    clean_env, monkeypatch, tmp_home, mocker, capsys
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, exception=TimeoutError("..."))
    mocker.patch.object(auth, "webbrowser")

    rc = auth.main(["--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "timed out waiting for callback" in err


def test_token_exchange_failure_exits_1(
    clean_env, monkeypatch, tmp_home, mocker, capsys
):
    _setup_oauth_env(monkeypatch)
    _mock_callback_server(mocker, code="code")
    _mock_token_exchange(mocker, exception=Exception("invalid_client"))
    mocker.patch.object(auth, "webbrowser")

    rc = auth.main(["--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "token exchange failed" in err
    assert "invalid_client" in err
