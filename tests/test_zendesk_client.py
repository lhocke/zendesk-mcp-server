import base64
from unittest.mock import MagicMock

import pytest

from zendesk_mcp_server.zendesk_client import ZendeskClient


# --- factory construction ---

def test_old_init_signature_raises_typeerror():
    with pytest.raises(TypeError, match="from_api_token|from_oauth"):
        ZendeskClient(subdomain="example", email="a@b.com", token="tok")


def test_from_api_token_constructs():
    client = ZendeskClient.from_api_token("example", "a@b.com", "tok")
    assert client.subdomain == "example"
    assert client.base_url == "https://example.zendesk.com/api/v2"
    assert client._token_manager is None


def test_from_oauth_constructs():
    mgr = MagicMock()
    mgr.get_valid_token.return_value = "initial_token"
    client = ZendeskClient.from_oauth("example", mgr)
    assert client.subdomain == "example"
    assert client._token_manager is mgr
    mgr.register_post_refresh_hook.assert_called_once_with(client._on_token_refreshed)


# --- auth_header property ---

def test_from_api_token_auth_header_is_correct_basic():
    client = ZendeskClient.from_api_token("example", "a@b.com", "tok")
    expected_creds = "a@b.com/token:tok"
    expected = f"Basic {base64.b64encode(expected_creds.encode()).decode('ascii')}"
    assert client.auth_header == expected


def test_from_api_token_auth_header_byte_for_byte_regression():
    """Locks the API-token Basic-auth format so the factory refactor doesn't
    silently break the legacy auth path."""
    client = ZendeskClient.from_api_token("acme", "support@acme.com", "abcd1234")
    creds = "support@acme.com/token:abcd1234"
    encoded = base64.b64encode(creds.encode()).decode("ascii")
    assert client.auth_header == f"Basic {encoded}"


def test_from_oauth_auth_header_returns_bearer():
    mgr = MagicMock()
    # from_oauth consumes one get_valid_token at construction
    mgr.get_valid_token.side_effect = ["init", "current_token"]
    client = ZendeskClient.from_oauth("example", mgr)
    assert client.auth_header == "Bearer current_token"


def test_from_oauth_auth_header_is_live_not_cached():
    """Each access of auth_header must call get_valid_token. If cached at
    construction time, refresh updates would never propagate."""
    mgr = MagicMock()
    mgr.get_valid_token.side_effect = ["init", "first", "second"]
    client = ZendeskClient.from_oauth("example", mgr)
    assert client.auth_header == "Bearer first"
    assert client.auth_header == "Bearer second"


# --- post-refresh hook (zenpy session header rewrite) ---

def test_on_token_refreshed_updates_zenpy_session_header():
    mgr = MagicMock()
    mgr.get_valid_token.return_value = "initial"
    client = ZendeskClient.from_oauth("example", mgr)
    # Initial header set by Zenpy.__init__
    assert client.client.tickets.session.headers["Authorization"] == "Bearer initial"
    # Simulate a refresh hook firing
    client._on_token_refreshed("refreshed_token")
    assert client.client.tickets.session.headers["Authorization"] == "Bearer refreshed_token"


def test_zenpy_session_header_propagates_across_api_helpers():
    """Sanity check on the spike's S2 finding: rewriting the header on
    .tickets.session also affects .users / .organizations / etc."""
    mgr = MagicMock()
    mgr.get_valid_token.return_value = "initial"
    client = ZendeskClient.from_oauth("example", mgr)
    client._on_token_refreshed("new_token")
    assert client.client.users.session.headers["Authorization"] == "Bearer new_token"
    assert client.client.organizations.session.headers["Authorization"] == "Bearer new_token"


# --- decorator policy: which methods are wrapped, which aren't ---

# Methods that MUST carry @retry_on_401 (24 total per oauth-implementation-plan-lean.md M4)
_DECORATED_METHODS = [
    "get_ticket", "get_ticket_comments", "get_ticket_attachment",
    "get_tickets", "get_all_articles", "create_ticket",
    "search_tickets", "get_organization", "search_users",
    "get_group_users", "get_groups", "list_custom_statuses",
    "get_jira_links", "get_zendesk_tickets_for_jira_issue",
    "list_ticket_fields", "list_macros", "preview_macro",
    "get_view", "list_views", "get_view_tickets",
    "add_tag", "remove_tag", "delete_jira_link", "update_ticket",
]

# Methods that MUST NOT carry @retry_on_401 (3 total — non-idempotent writes)
_EXCLUDED_METHODS = ["post_comment", "apply_macro", "create_jira_link"]


@pytest.mark.parametrize("method_name", _DECORATED_METHODS)
def test_method_is_decorated_with_retry_on_401(method_name):
    method = getattr(ZendeskClient, method_name)
    assert hasattr(method, "__wrapped__"), (
        f"{method_name} is missing @retry_on_401 — decorator was dropped or "
        f"never added."
    )


@pytest.mark.parametrize("method_name", _EXCLUDED_METHODS)
def test_method_is_NOT_decorated_with_retry_on_401(method_name):
    """Excluded methods (post_comment, apply_macro, create_jira_link) must NOT
    be wrapped — a retry would replay non-idempotent side effects (duplicate
    comment, replayed macro actions, duplicate Jira link)."""
    method = getattr(ZendeskClient, method_name)
    assert not hasattr(method, "__wrapped__"), (
        f"{method_name} is decorated with @retry_on_401 but MUST NOT be — "
        f"a retry would replay a non-idempotent side effect."
    )


def test_post_comment_401_propagates_without_refresh_in_oauth_mode():
    """Behavioral check on the post_comment exclusion: in OAuth mode, a 401
    from post_comment must propagate immediately without invoking refresh."""
    mgr = MagicMock()
    mgr.get_valid_token.return_value = "initial"
    client = ZendeskClient.from_oauth("example", mgr)

    # Simulate a 401 from zenpy: client.tickets(id=...) raises Exception with
    # an underlying urllib.error.HTTPError-like 401 in __context__.
    class FakeUrllibHTTPError(Exception):
        def __init__(self):
            super().__init__("HTTP 401")
            self.code = 401

    def fake_call(**kwargs):
        try:
            raise FakeUrllibHTTPError()
        except Exception as inner:
            raise Exception("Failed to load ticket: HTTP 401 - Unauthorized")

    client.client.tickets = MagicMock(side_effect=fake_call)

    with pytest.raises(Exception, match="Failed to post comment"):
        client.post_comment(123, "hello")

    # Critical: refresh must NOT have been called
    mgr.refresh.assert_not_called()
