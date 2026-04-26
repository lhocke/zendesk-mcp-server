"""OAuth runtime token management.

Wraps Authlib's OAuth2Session with Zendesk-specific configuration and the
token_store persistence layer. Provides @retry_on_401 for ZendeskClient methods.
"""
import time
from functools import wraps
from typing import Callable, List

from authlib.integrations.base_client import OAuthError
from authlib.integrations.requests_client import OAuth2Session

from zendesk_mcp_server import token_store

PROACTIVE_REFRESH_MARGIN_SECONDS = 30
_REFRESH_ERROR_MSG = (
    "Refresh token rejected by Zendesk. Run zendesk-auth to re-authenticate."
)


class OAuthRefreshError(Exception):
    pass


class OAuthTokenManager:
    def __init__(self, subdomain: str, client_id: str, client_secret: str):
        self.subdomain = subdomain
        self._token = token_store.load(subdomain)  # FileNotFoundError propagates
        self._token_endpoint = f"https://{subdomain}.zendesk.com/oauth/tokens"
        self._post_refresh_hooks: List[Callable[[str], None]] = []
        self._session = OAuth2Session(
            client_id,
            client_secret=client_secret,
            token=self._token,
            update_token=self._on_token_updated,
        )

    def get_valid_token(self) -> str:
        expires_at = self._token.get("expires_at")
        if (
            expires_at is not None
            and time.time() > expires_at - PROACTIVE_REFRESH_MARGIN_SECONDS
        ):
            self.refresh()
        return self._token["access_token"]

    def refresh(self) -> None:
        try:
            self._session.refresh_token(
                self._token_endpoint,
                refresh_token=self._token["refresh_token"],
            )
        except OAuthError as e:
            if getattr(e, "error", None) == "invalid_grant":
                raise OAuthRefreshError(_REFRESH_ERROR_MSG) from e
            raise OAuthRefreshError(str(e)) from e
        except Exception as e:
            raise OAuthRefreshError(str(e)) from e

    def register_post_refresh_hook(self, hook: Callable[[str], None]) -> None:
        """ZendeskClient.from_oauth registers a hook here to rewrite zenpy's session
        Authorization header in place after a refresh. Called with the new access_token
        as the only argument."""
        self._post_refresh_hooks.append(hook)

    def _on_token_updated(self, token, refresh_token=None, access_token=None):
        # Authlib invokes this callback after fetch_token (with access_token=) and after
        # refresh_token (with refresh_token=). Both deliver the full new token dict as
        # the first positional arg. See authlib/oauth2/client.py lines 315 and 460.
        token_store.save(self.subdomain, token)
        self._token = token
        for hook in self._post_refresh_hooks:
            hook(token["access_token"])


def retry_on_401(method):
    """On 401, refresh the OAuth token and retry once. No-op in API-token mode
    (when self._token_manager is None).

    DO NOT apply to methods with non-idempotent side effects (post_comment,
    apply_macro, create_jira_link) — a retry would replay the side effect.
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            token_manager = getattr(self, "_token_manager", None)
            if token_manager is None or not _is_401(e):
                raise
            token_manager.refresh()
            return method(self, *args, **kwargs)  # second 401 propagates

    return wrapper


def _is_401(exc: BaseException) -> bool:
    """Walk the exception chain (__cause__ then __context__) looking for a 401
    from any HTTP layer (urllib.error.HTTPError exposes .code; requests/zenpy
    APIException expose .response.status_code)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "code", None) == 401:
            return True
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) == 401:
            return True
        exc = exc.__cause__ or exc.__context__
    return False
