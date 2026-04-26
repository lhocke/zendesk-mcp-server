# OAuth Spec — Lean (Zendesk MCP Server)

## Goal

Replace per-user Zendesk API tokens with OAuth Authorization Code + PKCE for a small internal team, scoped tightly to ship quickly with a months-long shelf life before the team migrates off Zendesk to ServiceNow.

## Scope Justification

Decisions in this spec are deliberately calibrated to:

- **Team size:** 6 internal users on personal/work machines.
- **Lifetime:** months, not years (Zendesk → ServiceNow migration in flight).
- **Failure-mode cost:** if any token operation fails, the user re-runs `zendesk-auth`. ~30 seconds. No data loss, no security incident.

This spec replaces an earlier 3000-line design (`oauth-spec.md`). Items dropped here that lived in the old spec are intentional, not oversights — see "Out of Scope (and why)" at the bottom.

---

## Auth Modes

The server supports two mutually exclusive auth modes, selected by env vars at startup:

| Mode | Required env vars | Token source |
|---|---|---|
| **API token** (legacy) | `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, `ZENDESK_API_KEY` | Static token from env |
| **OAuth** | `ZENDESK_SUBDOMAIN`, `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET` | Token file written by `zendesk-auth` |

**Mode selection rule:** if `ZENDESK_CLIENT_ID` is set, run in OAuth mode. Otherwise run in API-token mode.

**Hard-fail rule:** if OAuth mode is selected (i.e. `ZENDESK_CLIENT_ID` is set) but the token file is missing or unreadable, the server exits non-zero with a message instructing the user to run `zendesk-auth`. **No silent fallback to API-token mode.** This prevents a confusing state where a misconfigured user thinks they're on OAuth but is silently using a legacy token.

### Migration for existing API-token users

Existing API-token users keep working with no action required as long as `ZENDESK_CLIENT_ID` stays unset. To switch:

1. Register an OAuth client in Zendesk admin with redirect URI `http://127.0.0.1:{port}/callback` (default port: see CLI section).
2. Set `ZENDESK_CLIENT_ID` and `ZENDESK_CLIENT_SECRET` in `.env`. Optionally remove `ZENDESK_EMAIL` and `ZENDESK_API_KEY`.
3. Run `zendesk-auth`. Browser opens, user authorizes, token file is written.
4. Restart MCP server.

---

## Dependencies (new)

Add to `pyproject.toml`:

- `authlib>=1.7.0` — handles PKCE, authorization URL construction, code→token exchange, refresh-token exchange, and the `update_token` callback hook.

Existing deps remain (`mcp`, `python-dotenv`, `zenpy`).

---

## CLI Entry Point: `zendesk-auth`

New script entry in `pyproject.toml`:

```toml
[project.scripts]
zendesk = "zendesk_mcp_server:main"
zendesk-auth = "zendesk_mcp_server.auth:main"
```

### Subcommands

| Invocation | Behavior |
|---|---|
| `zendesk-auth` | Run the OAuth flow. Opens browser, listens for callback, writes token file. Exits 0 on success, non-zero on failure. |
| `zendesk-auth --check` | Load the token file, print subdomain + token expiry (or "no expiry — refresh on 401 only" if Zendesk returned no `expires_in`). Exit 0 if token loadable, non-zero otherwise. Does not refresh. |
| `zendesk-auth --port N` | Use port N for the local callback server instead of the default. |
| `zendesk-auth --no-browser` | Print the authorization URL instead of launching a browser. User opens it manually. The callback server still runs and waits for the redirect. |

**Default port:** `47890` (chosen to be high, fixed, and easy to register in Zendesk's redirect URI). If port is in use, fail with a clear message: `"Port 47890 in use. Pass --port N to use a different port. Make sure http://127.0.0.1:N/callback is registered as a redirect URI in your Zendesk OAuth client."` No retry loop, no auto-pick.

**No `--revoke` subcommand.** Revocation is done in Zendesk admin UI. Justification: revocation is rare, the UI is one click, and the API call adds non-trivial spec surface for marginal value.

### Required env vars

`zendesk-auth` reads the same env vars as the server (`ZENDESK_SUBDOMAIN`, `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`). If `ZENDESK_CLIENT_ID` is unset, fail with a message pointing the user at the README.

### Flow

1. Validate env vars present.
2. Validate subdomain matches `^[a-z0-9][a-z0-9-]*[a-z0-9]$` (Zendesk subdomain rules; reject obvious typos like full URLs or trailing slashes). Single regex, no length cap.
3. Generate PKCE pair via Authlib (`code_verifier`, `code_challenge`, method `S256`).
4. Generate random `state` (Authlib's `OAuth2Session` does this).
5. Build authorization URL: `https://{subdomain}.zendesk.com/oauth/authorizations/new?...` with `response_type=code`, `client_id`, `redirect_uri=http://127.0.0.1:{port}/callback`, `scope=read write`, `state`, `code_challenge`, `code_challenge_method=S256`.
6. Start local callback server (see next section).
7. Open browser with `webbrowser.open(url)` (skip if `--no-browser`; print the URL instead).
8. Wait for callback server to receive code and verify state.
9. Exchange code for tokens via Authlib `session.fetch_token(...)`. Token endpoint: `https://{subdomain}.zendesk.com/oauth/tokens`.
10. Write token file (see Token Storage). On any failure during write, print the error and exit non-zero.
11. Print success message: `"Authenticated as {subdomain}.zendesk.com. Token saved to {path}. Restart your MCP server."`

### Failure modes (what to surface to the user)

| Condition | Behavior |
|---|---|
| Env vars missing | Print which vars are missing, exit 1. |
| Subdomain regex fails | Print the regex, exit 1. |
| Port in use | Print message above, exit 1. |
| User denies authorization (Zendesk redirects with `?error=...`) | Print the error, exit 1. |
| State mismatch on callback | Print "state mismatch — possible CSRF or stale auth attempt", exit 1. |
| Token exchange fails (HTTP error from Zendesk) | Print Zendesk's error response, exit 1. |
| Token file write fails | Print the OS error, exit 1. Do not leave a partial file (atomic write — see Token Storage). |
| User closes browser without completing | After 5 min wall-clock timeout, print "timed out waiting for callback", exit 1. |

---

## Local Callback Server

A single-request HTTP server that captures the authorization code and hands it back to the CLI.

### Requirements

- Bound to `127.0.0.1` only. Not `localhost` (which can resolve to IPv6 on some systems and break the redirect URI match), not `::1`.
- Single port (default 47890, configurable via `--port`).
- Uses `http.server.HTTPServer` from the stdlib. No new dependency.
- Single handler for `GET /callback`:
  - Parses `code` and `state` from query string.
  - Validates `state` against the value generated in step 4 of the flow.
  - Stores the code in a thread-safe slot the CLI reads from.
  - Returns a small HTML page: `<h1>Authentication complete</h1><p>You can close this tab.</p>`.
- Returns `400` with a brief HTML body on invalid requests (missing code, state mismatch, error param).
- Server shuts down after handling one valid callback OR after the 5-minute timeout.

### Threading model

The HTTP server runs on a background thread (or via `serve_forever()` on a thread). The main CLI thread waits on a `threading.Event` (set by the handler when a valid callback arrives) with a 5-minute timeout. After event fires or timeout, the main thread shuts down the server and proceeds.

---

## Token Storage

### File path

`~/.config/zendesk-mcp/{subdomain}.json` on macOS/Linux. (Use `Path.home()`; do not respect `$XDG_CONFIG_HOME` — extra surface for marginal value at this scale.)

Per-subdomain filename allows a user to authenticate against multiple Zendesk instances if needed (e.g., sandbox + prod) without overwriting.

### Permissions

- Directory: `0o700` on creation. If the directory already exists with looser permissions, do not chmod it (avoid surprising the user). If file write succeeds, that's enough.
- File: `0o600` on creation. Set explicitly after write.

### File format

```json
{
  "subdomain": "example",
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_at": 1735689600,
  "scope": "read write"
}
```

`expires_at` is a Unix timestamp computed at token-issue time as `now + expires_in`. If Zendesk did not return `expires_in`, store `expires_at: null` (see Zendesk-specific notes).

### Write semantics

- **Atomic via `os.replace`:** write to a temp file in the same directory (e.g., `{subdomain}.json.tmp.{pid}`), then `os.replace(tmp, final)`. This is atomic on POSIX.
- **No lock file.** No `.bak` recovery file. No multi-process coordination. If two writes race (the MCP server is refreshing while `zendesk-auth` is being re-run), the last write wins. The losing party's refresh result is discarded; on next request it will refresh again or hit a 401 and refresh.

### Read semantics

- Open and `json.load`. If file is missing → caller decides (CLI: this is fine, we're about to write; server: hard-fail per "Auth Modes").
- If file is corrupt (invalid JSON or missing required keys), raise a clear error: `"Token file at {path} is corrupt. Run zendesk-auth to re-authenticate."`

---

## Runtime Token Management

### `OAuthTokenManager` (new module: `zendesk_mcp_server/oauth.py`)

Wraps Authlib's `OAuth2Session` with Zendesk-specific configuration and the file-based persistence layer.

#### Responsibilities

1. **Load token from file at startup.** If file is missing → raise (caller hard-fails).
2. **Hand requests an access token** (`get_valid_token() -> str`):
   - If `expires_at` is set and now is past `expires_at - 30s` (30s safety margin), refresh proactively before returning.
   - If `expires_at` is `None`, return the current access token unchanged. Refresh will be triggered reactively by `@retry_on_401`.
3. **Refresh tokens** via `session.refresh_token(token_endpoint, refresh_token=...)`. On success, persist to file via the `update_token` callback. On failure, raise.
4. **`update_token` callback** wires Authlib's refresh result into `token_store.save(...)`. This is the only refresh-integration point — Authlib calls this after every successful refresh.

#### Refresh failure modes

| Cause | Behavior |
|---|---|
| Network error / Zendesk 5xx | Raise `OAuthRefreshError`. Caller (`@retry_on_401` or proactive refresh) decides whether to retry the original API call. |
| `invalid_grant` (refresh token expired or revoked) | Raise `OAuthRefreshError` with message `"Refresh token rejected by Zendesk. Run zendesk-auth to re-authenticate."`. The `@retry_on_401` decorator does NOT catch this — it propagates to the MCP tool caller as an error string. |

### `@retry_on_401` decorator

Wraps `ZendeskClient` methods that make API calls. On a 401:

1. Force a refresh via `OAuthTokenManager.refresh()`.
2. Retry the original call once.
3. If the second call also 401s, propagate the error.

**Excluded methods:** `post_comment` (and any future method with non-idempotent side effects). A retry would post a duplicate comment if the first call's failure was a network glitch after the comment was actually accepted.

In API-token mode, the decorator is a no-op.

### Proactive vs reactive refresh

- **Proactive:** check `expires_at` before each request; refresh if within 30s of expiry.
- **Reactive:** `@retry_on_401` handles tokens that expired between the check and the request, or any unexpected revocation.

Both are needed because Zendesk does not always return `expires_in` (see notes).

---

## Changes to `ZendeskClient`

### Constructor signature

The current signature `ZendeskClient(subdomain, email, token)` is replaced with two factory paths, both producing a `ZendeskClient` instance:

```python
ZendeskClient.from_api_token(subdomain: str, email: str, token: str) -> ZendeskClient
ZendeskClient.from_oauth(subdomain: str, token_manager: OAuthTokenManager) -> ZendeskClient
```

Internally, `ZendeskClient` stores either:
- `(email, token)` for API-token mode (used to build basic-auth header), OR
- `token_manager` for OAuth mode (calls `token_manager.get_valid_token()` per request to build bearer-auth header).

The `auth_header` attribute becomes a property that returns the correct header based on which mode was constructed.

### zenpy initialization

Zenpy supports both API-token and OAuth via its constructor:

- API token: `Zenpy(subdomain=..., email=..., token=...)`
- OAuth: `Zenpy(subdomain=..., oauth_token=...)` — passes a static token. **Limitation:** zenpy does not natively refresh; the static token can stale.

To handle refresh, after a refresh in `OAuthTokenManager`, call `self.client._session.headers["Authorization"] = f"Bearer {new_token}"` to update zenpy's underlying requests session in place. The same update is applied to the basic-auth-equivalent flow for direct `_requests.get(...)` calls (which already use `self.auth_header` — the property update covers them automatically).

### Direct API call paths

Direct `urllib.request` calls (e.g., `get_tickets`, `search_tickets`, `get_organization`) currently set `req.add_header('Authorization', self.auth_header)`. With OAuth, `self.auth_header` reads the live token from `token_manager`, so these continue to work without further changes.

### `get_ticket_attachment`

This method uses `_requests.get` with `headers={'Authorization': self.auth_header}`. The `auth_header` property returns the live token. **Important:** this method intentionally allows requests to follow Zendesk's CDN redirect, where requests strips the Authorization header — that behavior is unchanged.

---

## Server Startup (`server.py`)

### Hard-fail check at module import

Replace the current module-level construction:

```python
zendesk_client = ZendeskClient(
    subdomain=os.getenv("ZENDESK_SUBDOMAIN"),
    email=os.getenv("ZENDESK_EMAIL"),
    token=os.getenv("ZENDESK_API_KEY")
)
```

with:

```python
zendesk_client = build_zendesk_client()
```

Where `build_zendesk_client()`:

1. Reads `ZENDESK_SUBDOMAIN` (required in both modes — fail if missing).
2. If `ZENDESK_CLIENT_ID` is set:
   - Construct `OAuthTokenManager(subdomain, client_id, client_secret)`. This calls `token_store.load()`. If the file is missing, raise with the hard-fail message.
   - Return `ZendeskClient.from_oauth(subdomain, token_manager)`.
3. Else:
   - Read `ZENDESK_EMAIL` and `ZENDESK_API_KEY`. If either is missing, raise with a clear message.
   - Return `ZendeskClient.from_api_token(subdomain, email, token)`.

### Where `build_zendesk_client()` lives

In `server.py`. Called at module-import time (matches existing pattern). If it raises, the server fails to start with a clear stderr message.

---

## Out of Scope (and why)

These items existed in the prior 3000-line spec and are intentionally dropped:

| Dropped item | Why it's safe to drop |
|---|---|
| Lock file / `fcntl` advisory locking across processes | At 6 users, the realistic concurrent-process scenario is "MCP server is running and the user re-runs `zendesk-auth`". Last-write-wins is acceptable; the loser refreshes again or hits a 401 next request. |
| `.bak` recovery pattern after refresh write failure | A failed refresh write means the next request 401s and the user re-runs `zendesk-auth`. ~30 seconds. |
| Subdomain length cap + `\A`/`\Z` anchoring against env-var attackers | Threat model is six teammates with shell access; if they can edit env vars they can already do worse. |
| Concurrent `zendesk-auth` invocation handling | Don't run it twice at once. If you do, last write wins. |
| Port-conflict auto-retry / interactive picker | Single fixed port + `--port` override is sufficient. |
| `--revoke` subcommand | One click in Zendesk admin UI. |
| Exception-wrapper stripping in `zendesk_client.py` | Was only required by the complex retry layer in the prior spec. Authlib's session raises clean exceptions. |
| `fcntl` import guard for Windows compatibility | No `fcntl` is used in this spec. |
| 5-minute clock-skew adjustment window | The 30s proactive-refresh margin handles realistic skew; reactive 401 retry handles the rest. |

If any of these turns out to actually matter in practice, it can be added incrementally — but starting lean.

---

## Zendesk-Specific Notes

1. **`expires_in` may be absent.** Zendesk leaves `expires_in` unset by default unless the OAuth client is explicitly configured for token expirations via API. The implementation MUST tolerate a missing `expires_in`:
   - Store `expires_at: null` in the token file.
   - Skip proactive refresh when `expires_at is None`.
   - Rely on `@retry_on_401` for reactive refresh.
   Source: https://developer.zendesk.com/documentation/api-basics/authentication/refresh-token/

2. **Refresh-token grant is required.** As of Sept 30, 2025, Zendesk requires the refresh-token grant for OAuth clients. The OAuth client registration in Zendesk admin must enable refresh tokens, or `session.refresh_token(...)` will fail with an error.

3. **Redirect URI must be exact match.** Zendesk requires the redirect URI in the auth request to byte-for-byte match the URI registered in admin. Use `http://127.0.0.1:{port}/callback` consistently — never `localhost`, never with a trailing slash mismatch.

4. **Zenpy does not natively manage OAuth refresh.** Confirmed via https://github.com/facetoe/zenpy/issues/678. The `OAuthTokenManager` wrapper is required.

---

## Open Assumptions to Verify Before Coding

The implementation planner / first implementer should verify these:

1. **Authlib's `update_token` callback signature** — confirm exact parameters Authlib passes (token dict, refresh_token kwarg, etc.) so the callback writes the right shape.
2. **Zenpy's `_session` access** — confirm `self.client._session` is the right attribute on the installed Zenpy version (>=2.0.56) for in-place header updates after refresh. If zenpy's internal API differs, consider replacing zenpy's session with a custom `requests.Session` whose `Authorization` header is rewritten dynamically.
3. **Zendesk's authorization endpoint URL** — confirm `https://{subdomain}.zendesk.com/oauth/authorizations/new` and token endpoint `https://{subdomain}.zendesk.com/oauth/tokens` match the team's tenant. Some Zendesk regions use different hostnames.
4. **Default port `47890`** — confirm no conflict with anything else the team runs locally. If conflict, pick another high port and document.

---

## Estimated Implementation Size

| Module | New | Modified | LOC estimate |
|---|---|---|---|
| `zendesk_mcp_server/auth.py` | ✓ | | ~120 |
| `zendesk_mcp_server/oauth.py` (TokenManager + retry decorator) | ✓ | | ~100 |
| `zendesk_mcp_server/token_store.py` | ✓ | | ~50 |
| `zendesk_mcp_server/callback_server.py` | ✓ | | ~60 |
| `zendesk_mcp_server/zendesk_client.py` | | ✓ | +40 (factory methods, auth_header property, decorator application) |
| `zendesk_mcp_server/server.py` | | ✓ | +20 (build_zendesk_client) |
| `pyproject.toml` | | ✓ | +2 |
| `.env.example` | | ✓ | +2 |
| `README.md` | | ✓ | +30 (OAuth setup section) |
| **Total new code** | | | **~400 LOC** |

(vs. the prior spec's ~3000 LOC across more modules.)
