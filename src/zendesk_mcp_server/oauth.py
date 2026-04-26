"""OAuth runtime token management.

Wraps Authlib's OAuth2Session with Zendesk-specific configuration and the
token_store persistence layer. Provides @retry_on_401 for ZendeskClient methods.
"""


class OAuthRefreshError(Exception):
    pass


class OAuthTokenManager:
    def __init__(self, subdomain: str, client_id: str, client_secret: str):
        raise NotImplementedError

    def get_valid_token(self) -> str:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError


def retry_on_401(method):
    raise NotImplementedError
