# OAuth Spec — Zendesk MCP Server

## Goal

Replace per-user `ZENDESK_EMAIL` + `ZENDESK_API_KEY` configuration with an OAuth Authorization Code flow. Each user who runs the MCP server authenticates once via browser and gets a personal access token tied to their Zendesk identity, so public comments are attributed correctly.

API token auth is preserved as a fallback so existing deployments are not broken.

---

## Background Constraints

- Zendesk required all OAuth integrations to adopt the `refresh_token` grant type by September 2025. Refresh token rotation must be implemented from day one — not added later.
- When a refresh token is used, Zendesk invalidates both the old access token and the old refresh token and issues new ones. The token file must always be rewritten in full on refresh.
- Zenpy (our current Zendesk library) supports OAuth via an `oauth_token` parameter — no library replacement needed.
- Direct API calls in `zendesk_client.py` use `self.auth_header`; switching to Bearer is a one-line change per call site.

---

## Auth Modes

The server supports two auth modes, selected automatically based on which environment variables are present.

| Mode | Required env vars | How it authenticates |
|---|---|---|
| OAuth (preferred) | `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`, `ZENDESK_SUBDOMAIN` | Bearer token from local token file |
| API token (fallback) | `ZENDESK_EMAIL`, `ZENDESK_API_KEY`, `ZENDESK_SUBDOMAIN` | Basic auth (unchanged) |

If both sets of env vars are present, OAuth takes precedence. If neither set is complete, the server exits with a clear error message listing what is missing.

---

## New Entry Point: `zendesk-auth`

A new CLI command added alongside the existing `zendesk` MCP server command. Runs the one-time browser auth flow and writes the token file.

```
zendesk-auth [--no-browser] [--port PORT] [--check] [--revoke]
```

| Flag | Behavior |
|---|---|
| *(none)* | Opens authorization URL in the default browser, starts callback server |
| `--no-browser` | Prints the authorization URL instead of opening it (for headless/Docker environments) |
| `--port PORT` | Override the default callback port (default: 8085) |
| `--check` | Verify the current token is valid; print token owner and expiry; do not open browser |
| `--revoke` | Revoke the current token via the Zendesk API and delete the local token file |

### Auth flow steps

1. Generate a random `state` string (CSRF protection).
2. Construct the Zendesk authorization URL:
   ```
   https://{subdomain}.zendesk.com/oauth/authorizations/new
     ?response_type=code
     &client_id={ZENDESK_CLIENT_ID}
     &redirect_uri=http://localhost:{port}/callback
     &scope=read%20write
     &state={state}
   ```
3. Open browser or print URL (depending on `--no-browser`).
4. Start a temporary HTTP server on `localhost:{port}`.
5. Wait for the redirect. On receipt:
   - Validate the `state` parameter matches.
   - Extract the `code` parameter.
   - Respond to the browser with a plain success message so the tab can be closed.
   - Shut down the HTTP server.
6. Exchange the code for tokens via `POST /oauth/tokens` (see Token Exchange below).
7. Write the token file (see Token Storage below).
8. Print confirmation: authenticated user name/email and token expiry.

### Port conflict handling

Zendesk validates the redirect URI exactly — if the port used at runtime doesn't match the URI registered in the OAuth client, the auth will fail. For this reason there is no automatic port fallback. If port 8085 is busy, the command exits with:

```
Port 8085 is already in use. Free the port or re-run with --port <number>,
then ensure the matching redirect URI (http://localhost:<number>/callback)
is registered in your Zendesk OAuth client.
```

The `--port` flag is the intended escape hatch for persistent conflicts.

---

## Token Exchange

### Authorization code → tokens

```
POST https://{subdomain}.zendesk.com/oauth/tokens
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={code}
&client_id={ZENDESK_CLIENT_ID}
&client_secret={ZENDESK_CLIENT_SECRET}
&redirect_uri=http://localhost:{port}/callback
&scope=read%20write
```

Request token lifetimes in the payload:
```
&expires_in=172800          # 2 days (maximum allowed)
&refresh_token_expires_in=7776000  # 90 days (maximum allowed)
```

Response fields used: `access_token`, `refresh_token`, `token_type`, `scope`, `expires_in`, `refresh_token_expires_in`.

Compute and store absolute expiry timestamps (`now + expires_in`, `now + refresh_token_expires_in`) rather than the relative `expires_in` values.

### Refresh token → new tokens

```
POST https://{subdomain}.zendesk.com/oauth/tokens
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&refresh_token={refresh_token}
&client_id={ZENDESK_CLIENT_ID}
&client_secret={ZENDESK_CLIENT_SECRET}
```

Both `access_token` and `refresh_token` in the response are new. The previous pair is immediately invalidated. Always rewrite the entire token file.

---

## Token Storage

**Location:** `~/.zendesk_mcp/{subdomain}.json`

Multiple subdomain accounts are supported naturally — one file per subdomain.

**File format:**
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "scope": "read write",
  "expires_at": "2026-04-26T10:00:00Z",
  "refresh_token_expires_at": "2026-07-23T10:00:00Z"
}
```

**File permissions:** Set to `0o600` (owner read/write only) immediately after writing. Fail with a clear error if the file cannot be created with those permissions.

**Directory permissions:** `~/.zendesk_mcp/` created with `0o700`.

---

## Runtime Token Management

Handled in a new `OAuthTokenManager` class, used by `ZendeskClient` when in OAuth mode.

### On startup

1. Load token file. If missing → exit with message: `"No OAuth token found. Run 'zendesk-auth' to authenticate."`
2. If `refresh_token_expires_at` is in the past → exit with message: `"OAuth refresh token expired. Run 'zendesk-auth' to re-authenticate."`
3. If `expires_at` is within 5 minutes or already past → attempt silent refresh before proceeding.
4. Otherwise → proceed with current access token.

### On 401 response

1. Attempt one silent token refresh.
2. Retry the original request with the new token.
3. If refresh fails or the retry also returns 401 → raise with message: `"Authentication failed. Run 'zendesk-auth' to re-authenticate."`

### Thread safety

Token refresh must use a lock to prevent concurrent requests from triggering simultaneous refresh calls. Only one refresh attempt runs at a time; other threads wait and use the resulting token.

---

## Changes to `ZendeskClient`

### Constructor signature

Python doesn't support method overloading, so both modes are handled via optional kwargs with a runtime guard:

```python
class ZendeskClient:
    def __init__(
        self,
        subdomain: str,
        email: str | None = None,
        token: str | None = None,
        oauth_token: str | None = None,
        token_manager: OAuthTokenManager | None = None,
    ): ...
```

Exactly one of (`email` + `token`) or (`oauth_token` + `token_manager`) must be provided; the constructor raises `ValueError` if the combination is invalid.

A factory function in `server.py` selects the appropriate set of arguments based on env vars.

### zenpy initialization

OAuth mode:
```python
self.client = Zenpy(subdomain=subdomain, oauth_token=access_token)
```

### `self.auth_header`

OAuth mode: `f"Bearer {access_token}"`
API token mode: unchanged (`f"Basic {base64(email/token:token)}"`)

All direct API call sites (`urllib.request.Request`) already use `self.auth_header` — no other changes needed at those call sites.

### Token refresh integration

`ZendeskClient` calls `token_manager.get_valid_token()` at the start of each method (or wraps calls in a retry-on-401 decorator) to ensure it always uses a current token.

---

## Changes to `server.py`

Replace direct `ZendeskClient` construction with a factory:

```python
def build_zendesk_client() -> ZendeskClient:
    subdomain = os.getenv("ZENDESK_SUBDOMAIN")
    client_id = os.getenv("ZENDESK_CLIENT_ID")
    client_secret = os.getenv("ZENDESK_CLIENT_SECRET")
    email = os.getenv("ZENDESK_EMAIL")
    api_key = os.getenv("ZENDESK_API_KEY")

    if client_id and client_secret:
        manager = OAuthTokenManager(subdomain, client_id, client_secret)
        manager.load()  # raises with actionable message if token file is missing/expired
        return ZendeskClient(subdomain=subdomain, oauth_token=manager.access_token, token_manager=manager)
    elif email and api_key:
        return ZendeskClient(subdomain=subdomain, email=email, token=api_key)
    else:
        raise EnvironmentError(
            "Missing credentials. Set either:\n"
            "  OAuth: ZENDESK_CLIENT_ID, ZENDESK_CLIENT_SECRET, ZENDESK_SUBDOMAIN\n"
            "  API token: ZENDESK_EMAIL, ZENDESK_API_KEY, ZENDESK_SUBDOMAIN"
        )
```

---

## Changes to `pyproject.toml`

Add the auth command entry point:
```toml
[project.scripts]
zendesk = "zendesk_mcp_server:main"
zendesk-auth = "zendesk_mcp_server.auth:main"
```

Add dependencies:
```toml
"requests>=2.32",    # already used indirectly; pin explicitly for token exchange
```

(`requests` is already in the environment via zenpy; making it an explicit dependency is cleaner.)

---

## Docker Considerations

The auth flow requires a browser. Docker containers running headlessly cannot complete the Authorization Code flow.

**Recommended Docker workflow:**

1. Run `zendesk-auth` on the host machine to generate `~/.zendesk_mcp/{subdomain}.json`.
2. Mount the token directory into the container read-write so the server can persist refreshed tokens:
   ```bash
   docker run --rm -i \
     -v ~/.zendesk_mcp:/home/zendesk/.zendesk_mcp \
     --env-file .env \
     zendesk-mcp-server
   ```
3. The server reads the token file at startup and writes updated tokens back on refresh. Without a read-write mount, a refreshed token is lost when the container exits and the next run will fail.

Document this in the README. The `.env` file for Docker no longer needs `ZENDESK_EMAIL` or `ZENDESK_API_KEY` when using OAuth.

---

## Scopes

Register the OAuth client with scope `read write`. This covers all current MCP tools:

| Scope | Tools |
|---|---|
| `read` | `get_ticket`, `get_tickets`, `get_ticket_comments`, `get_ticket_attachment`, `search_tickets`, `get_organization`, `search_users`, `get_groups`, `get_group_users`, `list_custom_statuses` |
| `write` | `create_ticket`, `create_ticket_comment`, `update_ticket` |

---

## Files Changed / Created

| File | Change |
|---|---|
| `src/zendesk_mcp_server/auth.py` | New — `zendesk-auth` CLI command and OAuth flow |
| `src/zendesk_mcp_server/token_manager.py` | New — `OAuthTokenManager` class |
| `src/zendesk_mcp_server/zendesk_client.py` | Add OAuth constructor path; switch `auth_header` to Bearer in OAuth mode |
| `src/zendesk_mcp_server/server.py` | Replace direct client construction with `build_zendesk_client()` factory |
| `src/zendesk_mcp_server/__init__.py` | Export `auth.main` for entry point |
| `pyproject.toml` | Add `zendesk-auth` entry point; add `requests` as explicit dependency |
| `README.md` | Document OAuth setup, `zendesk-auth` command, Docker token mounting |
| `.env.example` | Add `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`; mark old vars as API-token-only fallback |

---

## Out of Scope

- Client credentials grant (machine-to-machine): carries app identity, not user identity — same attribution problem as a shared API token. Not implemented.
- Token encryption at rest: deferred. The `0o600` file permission is the security boundary for now.
- Multi-account support in a single running server instance: deferred.
