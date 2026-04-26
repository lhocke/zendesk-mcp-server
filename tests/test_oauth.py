import time
from unittest.mock import MagicMock

import pytest
from authlib.integrations.base_client import OAuthError

from zendesk_mcp_server import oauth, token_store


def _token(**overrides):
    base = {
        "subdomain": "example",
        "access_token": "old_access",
        "refresh_token": "old_refresh",
        "token_type": "Bearer",
        "expires_at": int(time.time()) + 3600,
        "scope": "read write",
    }
    base.update(overrides)
    return base


def _make_manager(token, mocker):
    """Construct an OAuthTokenManager backed by a fixture token; mock OAuth2Session
    so we don't make network calls."""
    mocker.patch.object(token_store, "load", return_value=token)
    mock_session = MagicMock()
    mocker.patch("zendesk_mcp_server.oauth.OAuth2Session", return_value=mock_session)
    mgr = oauth.OAuthTokenManager("example", "client_id", "client_secret")
    return mgr, mock_session


# --- OAuthTokenManager.__init__ ---

def test_init_propagates_filenotfounderror_on_missing_token_file(tmp_home, clean_env):
    with pytest.raises(FileNotFoundError):
        oauth.OAuthTokenManager("example", "cid", "csec")


# --- get_valid_token: proactive refresh ---

def test_get_valid_token_returns_current_when_expiry_far_in_future(mocker):
    token = _token(expires_at=int(time.time()) + 3600)
    mgr, _ = _make_manager(token, mocker)
    refresh_spy = mocker.patch.object(mgr, "refresh")
    assert mgr.get_valid_token() == "old_access"
    refresh_spy.assert_not_called()


def test_get_valid_token_with_expires_at_none_does_not_refresh(mocker):
    token = _token(expires_at=None)
    mgr, _ = _make_manager(token, mocker)
    refresh_spy = mocker.patch.object(mgr, "refresh")
    assert mgr.get_valid_token() == "old_access"
    refresh_spy.assert_not_called()


def test_get_valid_token_refreshes_when_inside_30s_margin(mocker):
    """expires_at = now + 20 → refresh fires."""
    token = _token(expires_at=int(time.time()) + 20)
    mgr, _ = _make_manager(token, mocker)
    refresh_spy = mocker.patch.object(mgr, "refresh")
    mgr.get_valid_token()
    refresh_spy.assert_called_once()


def test_get_valid_token_does_not_refresh_just_outside_30s_margin(mocker):
    """expires_at = now + 31 → no refresh (boundary test)."""
    token = _token(expires_at=int(time.time()) + 31)
    mgr, _ = _make_manager(token, mocker)
    refresh_spy = mocker.patch.object(mgr, "refresh")
    mgr.get_valid_token()
    refresh_spy.assert_not_called()


def test_get_valid_token_refreshes_at_29s_margin(mocker):
    """expires_at = now + 29 → refresh fires (other boundary)."""
    token = _token(expires_at=int(time.time()) + 29)
    mgr, _ = _make_manager(token, mocker)
    refresh_spy = mocker.patch.object(mgr, "refresh")
    mgr.get_valid_token()
    refresh_spy.assert_called_once()


def test_two_consecutive_calls_only_refresh_once(mocker):
    """After proactive refresh on call 1, the new expires_at should put us
    outside the margin so call 2 does not refresh again."""
    token = _token(expires_at=int(time.time()) + 20)
    mgr, _ = _make_manager(token, mocker)

    def fake_refresh():
        mgr._token = _token(
            access_token="new_access",
            expires_at=int(time.time()) + 3600,
        )

    refresh_spy = mocker.patch.object(mgr, "refresh", side_effect=fake_refresh)
    mgr.get_valid_token()
    mgr.get_valid_token()
    assert refresh_spy.call_count == 1


# --- update_token callback wiring ---

def test_update_token_persists_via_token_store_save(mocker):
    token = _token()
    mgr, _ = _make_manager(token, mocker)
    save_spy = mocker.patch.object(token_store, "save")

    new_token = _token(access_token="new_access", refresh_token="new_refresh")
    mgr._on_token_updated(new_token, refresh_token="old_refresh")

    save_spy.assert_called_once_with("example", new_token)
    assert mgr._token == new_token


def test_update_token_invokes_post_refresh_hooks(mocker):
    token = _token()
    mgr, _ = _make_manager(token, mocker)
    mocker.patch.object(token_store, "save")

    hook = MagicMock()
    mgr.register_post_refresh_hook(hook)
    new_token = _token(access_token="new_access")
    mgr._on_token_updated(new_token, refresh_token="old_refresh")
    hook.assert_called_once_with("new_access")


# --- refresh error paths ---

def test_refresh_invalid_grant_raises_with_actionable_message(mocker):
    token = _token()
    mgr, mock_session = _make_manager(token, mocker)
    err = OAuthError(error="invalid_grant", description="bad")
    mock_session.refresh_token.side_effect = err

    with pytest.raises(oauth.OAuthRefreshError, match="Run zendesk-auth to re-authenticate"):
        mgr.refresh()


def test_refresh_network_error_raises_oauth_refresh_error(mocker):
    token = _token()
    mgr, mock_session = _make_manager(token, mocker)
    mock_session.refresh_token.side_effect = ConnectionError("network down")

    with pytest.raises(oauth.OAuthRefreshError, match="network down"):
        mgr.refresh()


# --- @retry_on_401 decorator ---

class _FakeUrllibHTTPError(Exception):
    """Mimics urllib.error.HTTPError shape."""
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeRequestsHTTPError(Exception):
    """Mimics requests.HTTPError / zenpy APIException shape."""
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResponse(status_code)


class _Client:
    """Test stub mimicking ZendeskClient: has _token_manager attribute."""
    def __init__(self, token_manager=None):
        self._token_manager = token_manager
        self.calls = 0


def test_decorator_passes_through_on_success():
    client = _Client(token_manager=MagicMock())

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        return "ok"

    assert method(client) == "ok"
    assert client.calls == 1
    client._token_manager.refresh.assert_not_called()


def test_decorator_refreshes_and_retries_on_401_in_oauth_mode():
    tm = MagicMock()
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        if self.calls == 1:
            raise _FakeUrllibHTTPError(401)
        return "ok"

    assert method(client) == "ok"
    assert client.calls == 2
    tm.refresh.assert_called_once()


def test_decorator_is_noop_in_api_token_mode():
    """No _token_manager → 401 propagates without refresh attempt."""
    client = _Client(token_manager=None)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        raise _FakeUrllibHTTPError(401)

    with pytest.raises(_FakeUrllibHTTPError):
        method(client)
    assert client.calls == 1


def test_decorator_propagates_after_two_401s():
    tm = MagicMock()
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        raise _FakeUrllibHTTPError(401)

    with pytest.raises(_FakeUrllibHTTPError):
        method(client)
    assert client.calls == 2
    tm.refresh.assert_called_once()


def test_decorator_does_not_refresh_on_non_401():
    tm = MagicMock()
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        raise _FakeUrllibHTTPError(500)

    with pytest.raises(_FakeUrllibHTTPError):
        method(client)
    assert client.calls == 1
    tm.refresh.assert_not_called()


def test_decorator_detects_401_through_requests_response_attribute():
    tm = MagicMock()
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        if self.calls == 1:
            raise _FakeRequestsHTTPError(401)
        return "ok"

    assert method(client) == "ok"
    tm.refresh.assert_called_once()


def test_decorator_walks_exception_chain_to_find_401():
    """Existing zendesk_client.py methods wrap underlying HTTPError in
    `raise Exception(...)` without `from`, which sets __context__. The
    decorator must walk the chain to find the underlying 401."""
    tm = MagicMock()
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        if self.calls == 1:
            try:
                raise _FakeUrllibHTTPError(401)
            except Exception as e:
                raise Exception(f"Failed to do thing: {e}")
        return "ok"

    assert method(client) == "ok"
    tm.refresh.assert_called_once()


def test_decorator_propagates_oauth_refresh_error_as_user_readable():
    """When refresh itself fails with invalid_grant during the retry path, the
    OAuthRefreshError surfaces with its actionable message."""
    tm = MagicMock()
    tm.refresh.side_effect = oauth.OAuthRefreshError(
        "Refresh token rejected by Zendesk. Run zendesk-auth to re-authenticate."
    )
    client = _Client(token_manager=tm)

    @oauth.retry_on_401
    def method(self):
        self.calls += 1
        raise _FakeUrllibHTTPError(401)

    with pytest.raises(oauth.OAuthRefreshError, match="Run zendesk-auth to re-authenticate"):
        method(client)
