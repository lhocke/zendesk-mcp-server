# Test Strategy — OAuth Spec (Lean)

Merged output of two parallel `spec-reviewer-test-strategy` runs against `oauth-spec-lean.md`. Where the two instances disagreed, the resolution is noted inline in *italics*. Test approach (unit / integration / manual) is given for each item. Calibrated to: 6 internal users, months-long shelf life before ServiceNow migration, "re-run zendesk-auth" as the universal recovery path.

---

## Auth Modes

### Happy path

- **API-token mode selected when `ZENDESK_CLIENT_ID` is unset.** Existing users must keep working. **Unit** — mock env, assert factory takes the `from_api_token` path.
- **OAuth mode selected when `ZENDESK_CLIENT_ID` is set and token file exists.** Primary post-migration path; if the branch is wrong, the entire OAuth path is bypassed. **Unit** — mock env + token file, assert factory takes the `from_oauth` path.

### Error paths

- **OAuth mode + token file missing → server exits non-zero with the "run zendesk-auth" message.** Hard-fail invariant; without it, a misconfigured user could silently use a stale API token. **Unit** — mock `token_store.load` to raise FileNotFoundError, assert raised exception message contains "zendesk-auth".
- **API-token mode + `ZENDESK_EMAIL` or `ZENDESK_API_KEY` missing → clear error.** Without this, downstream calls fail with cryptic AttributeError. **Unit** — one parametrized case per missing var.
- **`ZENDESK_SUBDOMAIN` missing in either mode → clear error before either path is attempted.** Subdomain is required everywhere and easy to forget. **Unit**.

### Edge cases

- **`ZENDESK_CLIENT_ID` set to empty string.** Spec says "if set" — an empty string is falsy in Python. Verify it does NOT trigger OAuth mode. **Unit**. *(Both reviewers flagged this — keep as a coverage gap until the implementer confirms the truthy-check semantic in code.)*

---

## CLI Entry Point: `zendesk-auth`

### Happy path

- **`zendesk-auth` (no flags) completes the full flow, writes a token file, exits 0, prints the spec-prescribed success message.** Primary user action; success message wording is prescribed verbatim in the spec — wrong message misleads users about state. **Integration** — mock browser open and Zendesk endpoints; drive the callback server with a synthetic redirect; capture stdout to assert message wording.
- **`zendesk-auth --check` with a valid token file: prints subdomain + expiry, exits 0.** Only operator status command. **Unit** — pre-written token file fixture.
- **`zendesk-auth --check` with `expires_at: null`: prints "no expiry — refresh on 401 only", exits 0.** This is the normal Zendesk configuration; wrong message confuses users about token state. **Unit** — null-expires-at fixture.
- **`zendesk-auth --port N`: callback server binds to N; auth URL and success message reference port N.** Required path for users with conflicts. **Integration** — start server on explicit port, confirm bind; assert URL plumbing.
- **`zendesk-auth --no-browser`: prints URL, does not call `webbrowser.open`, callback server still accepts the redirect.** Headless / CI environments depend on this. **Unit** — mock `webbrowser.open`, assert not called; assert URL printed; **Integration** for the callback-still-works leg.

### Error paths

- **Missing `ZENDESK_CLIENT_ID`: exit 1, message points to README.** Most common misconfiguration. **Unit**.
- **Subdomain regex fails: exit 1, prints the regex.** Catches full-URL typos. **Unit** — parametrize: full URL (`https://x.zendesk.com`), trailing slash, leading hyphen, trailing hyphen, uppercase, single character.
- **Port 47890 in use: exit 1 with the spec-prescribed message** (including the port number and the redirect-URI reminder). Without exact wording, the user can't recover. **Integration** — bind a socket to 47890 first; assert exit 1 and exact message text.
- **Zendesk redirects with `?error=access_denied`: exit 1, prints the error.** User denial is common; wrong handling leaves the callback server hung. **Integration** — drive callback handler with the error query string.
- **State mismatch on callback: exit 1 with "state mismatch — possible CSRF or stale auth attempt".** CSRF guard correctness. **Unit** — inject wrong state.
- **Token exchange HTTP error: exit 1, prints Zendesk's error response body.** Most likely production failure mode. **Integration** — mock token endpoint returning 4xx.
- **Token file write failure: exit 1, prints OS error, no partial file remains.** Partial file would corrupt next read. **Unit** — mock `os.replace` to raise OSError, assert tmp file is cleaned up and target path absent.
- **5-minute wall-clock timeout with no callback: exit 1 with "timed out waiting for callback".** Without this the CLI hangs. **Unit** — short injectable timeout.

### Edge cases

- **Single-character subdomain rejected** by the regex (which requires ≥2 chars per `[a-z0-9][a-z0-9-]*[a-z0-9]$`). Verify intentional. **Unit**.
- **`--port 0` or `--port 99999` validation.** Spec doesn't prescribe validation; flag as **coverage gap** below. *(Inst1 caught this; Inst2 missed.)*

---

## Local Callback Server

### Happy path

- **`GET /callback?code=X&state=Y` with matching state: stores code, returns the prescribed HTML, sets the threading.Event.** Critical hand-off point. **Unit**.
- **Server bound to `127.0.0.1`** (not `0.0.0.0`, not `localhost`, not `::1`). Loopback-only is required so the redirect URI matches Zendesk's registered value and the server is unreachable from other hosts. **Unit** — assert socket bound address.
- **Server shuts down after one valid callback.** A persistent server holds the port and confuses re-runs. **Unit** — assert `server_close()` is called after event fires.

### Error paths

- **Missing `code` query param: returns 400.** Zendesk may redirect without a code on some error paths; handler must not crash. **Unit**.
- **`?error=access_denied` in callback: returns 400, surfaces error to CLI thread.** **Unit**.
- **State mismatch: returns 400, does not store code, does not signal success event.** **Unit**.
- **Request to a path other than `/callback`: returns 400 (or 404 — clarify with implementer).** *(Both flagged; spec says "400 on invalid requests" but doesn't explicitly cover wrong-path; treat as 400 unless the implementer chooses otherwise.)* **Unit**.

### Edge cases

- **Two requests arrive between valid callback and shutdown** (e.g., browser prefetches favicon). Second request must not overwrite the stored code or re-fire the event. **Unit** — send two requests; assert state preserved.
- **Late callback arrives after the 5-min timeout has fired.** Server is shutting down or shut down; the late callback must not crash or update state. **Unit**.
- **Query string with extra parameters** (e.g., Zendesk appends `&session_state=...`): handler parses only `code` and `state`, ignores extras. **Unit**.

---

## Token Storage

### Happy path

- **`token_store.save(...)` writes valid JSON at `~/.config/zendesk-mcp/{subdomain}.json` atomically.** Atomic write is the spec's correctness guarantee. **Unit** — call save, read back, assert contents; assert tmp file does not remain.
- **Directory created with `0o700` on first write.** Holds credential files. **Unit** — patch `Path.home()` to a tmp dir, call save, assert dir mode.
- **File permissions `0o600`.** Prevents other local users reading tokens. **Unit** — `stat().st_mode & 0o777 == 0o600`.
- **Per-subdomain filename isolation: `example.json` and `sandbox.json` are independent.** Multi-instance support; collision would overwrite. **Unit** — save two subdomains, assert both files present.
- **`load()` returns a token dict for a well-formed file.** **Unit**.
- **`expires_at: null` round-trips as Python `None`** (not string `"null"`). The `is None` check in `get_valid_token()` depends on this. **Unit**.

### Error paths

- **`load()` on missing file: raises a caller-interpretable signal** (FileNotFoundError or custom — pick one and stick to it). **Unit**.
- **`load()` on invalid JSON: raises with message containing "Run zendesk-auth to re-authenticate".** Without this UX, users see a raw JSON parse error. **Unit** — write `{bad json`.
- **`load()` on valid JSON missing a required key (e.g. no `access_token`): raises the same actionable corruption message.** Catches truncated/manually-edited files at load time, not as AttributeError later. **Unit** — fixture with `access_token` omitted.
- **`save()` mid-write failure (e.g., `os.replace` raises): raises, target path absent, tmp path cleaned up.** Spec mandates "do not leave a partial file." **Unit** — mock `os.replace` to raise.

### Edge cases

- **Directory pre-exists with permissions wider than `0o700`: save succeeds without chmod.** Spec explicitly forbids re-chmod of an existing directory. **Unit** — pre-create with `0o755`, assert mode unchanged after save.
- **Temp file name includes PID** (`{subdomain}.json.tmp.{pid}`). If two processes write simultaneously without PID-uniqueness, one silently overwrites the other's tmp. **Unit** — assert temp path includes `os.getpid()`. *(Inst1's catch — verify a spec detail.)*

---

## Runtime Token Management

### Happy path

- **`get_valid_token()` returns the current access token when `expires_at` is well in the future.** Baseline. **Unit** — `expires_at = now + 3600`, assert no refresh.
- **`get_valid_token()` triggers proactive refresh when `expires_at` is within 30s of now.** 30s margin is a spec invariant. **Unit** — `expires_at = now + 20`.
- **`get_valid_token()` with `expires_at is None` returns current token without refreshing.** Zendesk-specific; otherwise every request triggers an unneeded refresh. **Unit**.
- **`update_token` callback persists refreshed token via `token_store.save(...)`.** Only persistence path after refresh. **Unit** — mock Authlib session, simulate refresh, assert `save` called with new token.
- **After refresh, zenpy's `client._session.headers["Authorization"]` is rewritten** to `Bearer {new_token}`. Without this update zenpy continues using the stale token in-process. **Unit** — assert header update on mocked zenpy client.

### Error paths

- **Refresh fails with network error: raises `OAuthRefreshError`.** Caller decides what to do. **Unit**.
- **Refresh fails with `invalid_grant`: raises `OAuthRefreshError` whose message contains "Run zendesk-auth to re-authenticate".** This is the token-revoked / refresh-token-expired UX; `@retry_on_401` must NOT swallow this. **Unit** — mock Authlib raising `invalid_grant`.
- **`OAuthTokenManager.__init__` with missing token file: raises immediately.** Server startup hard-fail. **Unit**.

### Edge cases

- **Boundary of the 30s margin** — `expires_at = now + 29` triggers refresh; `expires_at = now + 31` does not. **Unit** — both sides of the boundary. *(Inst1's catch.)*
- **Two consecutive `get_valid_token()` calls when proactive refresh fired on the first.** The second call must not refresh again (the `update_token` callback already updated `expires_at`). **Unit** — assert refresh called exactly once. *(Inst2's catch — guards against refresh-loop.)*

---

## `@retry_on_401` Decorator

### Happy path

- **Decorated method succeeds first call: no refresh, no retry.** Common case. **Unit**.
- **Decorated method 401s, refresh succeeds, retry succeeds: method called twice, refresh called once, second result returned.** Reactive refresh path. **Unit**.
- **In API-token mode: decorator is a no-op** — calling `OAuthTokenManager.refresh()` without a manager would crash. **Unit** — construct via `from_api_token`, force a 401, assert no refresh attempt.

### Error paths

- **Second call also 401s: error propagates to caller.** Without this, infinite loop on persistent 401. **Unit** — both calls 401, assert exception propagates after exactly two attempts.
- **Refresh raises `OAuthRefreshError(invalid_grant)` during the retry path: error propagates as a user-readable string to the MCP tool caller, not as an unhandled exception/stack trace.** **Unit**.

### Edge cases — correctness invariants

- **`post_comment` is NOT decorated with `@retry_on_401`.** A retry would post a duplicate comment if the first call's failure was a network glitch *after* Zendesk accepted the comment. Verify by inspecting the method (no `__wrapped__` attribute, or no decorator marker) AND by behaviorally asserting that a 401 from `post_comment` propagates immediately without a refresh call. **Unit** — both checks together.
- *(Future-method risk — see Coverage Gaps.)*

---

## Changes to `ZendeskClient`

### Happy path

- **`from_api_token(subdomain, email, token)` produces an instance whose `auth_header` returns `"Basic ..."`** with the base64 of `"{email}/token:{token}"`. **Unit**.
- **`from_oauth(subdomain, token_manager)` produces an instance whose `auth_header` calls `token_manager.get_valid_token()` and returns `"Bearer {token}"`.** The property must be live (not cached at construction). **Unit** — mock `get_valid_token`, read property, assert `Bearer ...`.
- **`auth_header` reflects refreshed tokens on the next read.** Property must call `get_valid_token()` each access; caching would defeat refresh. **Unit** — change mock return value between two reads, assert both reads return the current value.
- **`get_ticket_attachment` sets `Authorization` from `auth_header` on the initial request.** The CDN-redirect strip behavior is `requests` library behavior and not under test; verify only the initial header set. **Unit**.

### Error paths

- **The pre-OAuth `__init__(subdomain, email, token)` constructor is removed (or raises clearly if retained).** If callers can bypass the factory, OAuth wiring breaks silently. **Unit** — assert calling the old signature fails or doesn't exist. *(Inst1's catch.)*

### Edge cases

- **In OAuth mode, `auth_header` accessed by all direct API-call paths (`get_tickets`, `search_tickets`, `get_organization`, etc.).** Implicitly covered by the live-property test above; no separate test per method.

---

## Server Startup (`server.py`)

### Happy path

- **`build_zendesk_client()` in OAuth mode** with valid env + token file returns `ZendeskClient.from_oauth(...)`. **Unit**.
- **`build_zendesk_client()` in API-token mode** with all three vars set returns `ZendeskClient.from_api_token(...)`. **Unit**.

### Error paths

- **Missing `ZENDESK_SUBDOMAIN` (either mode): raises before either branch.** **Unit**.
- **OAuth mode + missing token file: raises with hard-fail message containing "zendesk-auth".** **Unit**.
- **API-token mode + missing `ZENDESK_EMAIL` or `ZENDESK_API_KEY`: raises with clear message.** **Unit** — one case per missing var.

### Edge cases

- **Module-import failure surfaces as a non-zero process exit, not a degraded server.** `build_zendesk_client()` is called at import time per the spec. *(Reviewer disagreement — Inst1 said smoke test, Inst2 said manual or subprocess. Resolve to **Integration**: launch the server via subprocess with bad env, assert non-zero exit code. This is automatable; "manual" is too weak.)*

---

## Coverage Gaps

Things that matter but cannot be (or should not be) covered by the automated test suite. Each lists a mitigation.

1. **End-to-end OAuth round-trip against a real Zendesk tenant.** Authlib's PKCE generation, Zendesk's token endpoint, and the exact shape of Zendesk's token response (including absent `expires_in`) can only be verified end-to-end. **Mitigation:** one-time manual smoke test on first deployment per tenant; repeat if Zendesk changes OAuth client config.

2. **Authlib's `update_token` callback signature.** The spec lists this as an open assumption (item 1). Until verified against the installed Authlib version, the callback wiring cannot be unit-tested with confidence. **Mitigation:** verify the signature in Authlib source before writing the callback; the unit test should assert the callback receives a dict with at least `access_token` and `refresh_token`.

3. **Zenpy's `_session` attribute stability.** Spec open assumption (item 2). If `client._session` is renamed or restructured, in-place header updates after refresh silently stop working. **Mitigation:** pin zenpy version in `pyproject.toml`; manual smoke test after any zenpy upgrade — refresh a token and confirm the next zenpy call succeeds without a second 401.

4. **Browser launch behavior** (`webbrowser.open`). On headless machines it can silently fail or open the wrong thing. **Mitigation:** unit test asserts `webbrowser.open` is called with the correct URL and that `--no-browser` suppresses the call. Real-browser behavior is verified manually by one team member on first install.

5. **Redirect URI byte-for-byte match against Zendesk's registered value.** Cannot be asserted in tests; only Zendesk's response can confirm. **Mitigation:** unit test asserts URL is constructed as `http://127.0.0.1:{port}/callback`; manual smoke on first OAuth client registration.

6. **5-minute wall-clock timeout under real time.** Unit tests use mocked / injected timeouts. **Mitigation:** ensure the timeout is an injectable parameter so the unit test isn't lying about the production code path. The mock-based test is sufficient at this scale.

7. **Atomic write POSIX guarantee.** `os.replace` atomicity is a kernel guarantee; not testable from userspace. **Mitigation:** rely on POSIX guarantee; document macOS/Linux-only scope in the module.

8. **File permission race window between `open` and `chmod 0o600`.** The file is briefly more permissive than 0o600 between write and chmod. Acceptable per spec scope (6 internal users on personal machines). **Mitigation:** none — known and accepted.

9. **`ZENDESK_CLIENT_ID = ""` (empty string) behavior.** Spec doesn't explicitly address; depends on the implementer's truthy check. **Mitigation:** implementer chooses semantic and adds an explicit unit test for it.

10. **`--port 0` and `--port 99999` (and other invalid port values).** Spec doesn't prescribe validation. **Mitigation:** decide at implementation time — either delegate to Python's socket layer (which will fail with a clear error on bad ports) or add explicit validation. Either way, document the chosen behavior.

11. **Port 47890 conflict with team tooling.** Spec open assumption (item 4). **Mitigation:** each team member runs `lsof -i :47890` before first use; document `--port` as the override path.

12. **Future non-idempotent methods inadvertently decorated with `@retry_on_401`.** No test can guard against this without a registry of excluded methods. **Mitigation:** add a module-level comment to `zendesk_client.py` listing methods that must NOT be decorated and why; include an entry in the code-review checklist for new write-path methods.

---

## Skips

Areas explicitly out of scope for the automated test suite, with rationale.

- **Lock files / `fcntl` / multi-process coordination.** Dropped from spec. Last-write-wins is the specified behavior; testing it works correctly is testing the OS.
- **`.bak` recovery file behavior.** Dropped from spec. Recovery path is "re-run `zendesk-auth`."
- **`--revoke` subcommand.** Doesn't exist in this spec.
- **Port auto-retry / interactive picker.** Dropped from spec. Only fixed-port + error-message path is tested.
- **Subdomain length cap / `\A`/`\Z` regex anchoring.** Dropped from spec scope. Regex happy-path + bad-value cases are sufficient.
- **Exception-wrapper stripping in `zendesk_client.py`.** Dropped from spec — was only required by the prior spec's complex retry layer. Authlib raises clean exceptions.
- **`fcntl` cross-platform / Windows compatibility.** No `fcntl` is used; Windows is not a target.
- **`$XDG_CONFIG_HOME` support.** Spec explicitly does not respect this env var.
- **Authlib's PKCE generation / authorization URL parameter ordering / HTTP semantics.** Authlib is itself tested; this implementation tests only that Authlib is *configured* correctly (right endpoint URLs, right `update_token` wiring).
- **Zendesk admin UI flows** (registering OAuth client, enabling refresh tokens). Outside the code boundary entirely.

---

## Test Sequencing Recommendation (for the implementer)

The implementation planners will set sequencing, but as a default:

1. `token_store` unit tests first — pure module, no dependencies, safest to lock in.
2. `OAuthTokenManager` unit tests with Authlib mocked — locks in the refresh + update_token wiring before zendesk_client integration.
3. `@retry_on_401` decorator unit tests — including the `post_comment` exclusion invariant.
4. `ZendeskClient` factory + `auth_header` property unit tests.
5. `build_zendesk_client()` unit tests — full mode-selection matrix.
6. `callback_server` unit tests — handler in isolation.
7. `auth.py` integration tests — full CLI flow with mocked Zendesk endpoints.
8. End-to-end manual smoke against a real Zendesk tenant (single team member, single time, before broader rollout).
