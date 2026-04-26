# OAuth Implementation Plan (Lean)

Merged output of three parallel planners (risk-first, bottom-up, test-driven). Where the planners disagreed with consequence, the resolution is noted inline in *italics*. Where one planner caught something the other two missed, attribution is given so it's clear the catch is not a triple-redundancy.

**Reads:** `oauth-spec-lean.md` + `oauth-test-strategy-lean.md` + existing code in `src/zendesk_mcp_server/`.

---

## Pre-Implementation Cleanup (Before Writing Any Code)

These three items came from the planners' reads of the actual repo state, not from the spec. They must be done before milestone work begins; otherwise milestones will collide with stale artifacts.

1. **Update `CLAUDE.md`.** Four "Key Design Decisions (Do Not Reverse Without Dylan's Approval)" entries are now contradicted by the lean spec:
   - Lock file as stable sibling — lean spec drops it
   - `fcntl` import guard at `OAuthTokenManager.__init__` — no `fcntl` in lean spec
   - `.bak` recovery pattern — dropped
   - `build_zendesk_client()` placement (CLAUDE.md says inside `server.main()`; lean spec says module-import time, "matches existing pattern")

   Each must be either removed from `CLAUDE.md` or updated to reflect the lean-spec design. The `build_zendesk_client()` placement specifically needs Dylan's decision — see "Open Questions for Dylan" at the bottom.

2. **Archive or delete the old `implementation-plan.md`** in repo root. It was written against the prior 3000-line spec and contains references to dropped components (flock, `.bak`, `--revoke`, Pattern A/B/C exception BFS, `_durable_dir_sync`, three-attempt retry with `Retry-After`). Leaving it next to `oauth-implementation-plan-lean.md` will confuse the next reader. Recommend `git mv implementation-plan.md implementation-plan.archived-2026-04-26.md` with a one-line header note explaining it's superseded.

3. **Add `pytest` to CI** *(separate pre-step PR per Dylan, not bundled into the OAuth PR).* Current `.github/workflows/ci.yml` only runs `uv build`. The test suite this plan produces will be advisory, not blocking, until CI runs `uv run pytest`. Ship this as a small standalone PR before starting M1 so OAuth implementation isn't blocked on unrelated CI issues.

There is also one housekeeping fix for `pyproject.toml`: **`cachetools` is used in `server.py` but not declared as a dependency** — it's only present transitively in `requirements.lock`. *(Bottom-up's catch.)* Add it explicitly when M1 touches `pyproject.toml`.

---

## Spike Phase (Day 1, ~2–3 hours, no commits)

Four assumptions from the lean spec's "Open Assumptions to Verify Before Coding" section. All three planners agreed the first two are critical pre-work; one planner (bottom-up) compressed the URL/port checks into milestone-time, but the consensus is to do all four upfront — they're cheap and any wrong answer changes the plan.

| # | Spike item | Method | What it invalidates if wrong |
|---|---|---|---|
| S1 | Authlib `update_token` callback signature | REPL with `authlib>=1.7.0`; inspect `OAuth2Session.fetch_token` / `refresh_token`; confirm whether callback receives `(token, refresh_token=...)` or `(new_token,)` or `(token, old_token)` | M2's `update_token` wiring; if wrong, refresh callback fails silently and tokens never persist after refresh |
| S2 | Zenpy `_session` attribute on `zenpy>=2.0.56` | REPL: `Zenpy(subdomain="x", oauth_token="y")._session`; confirm it is a `requests.Session` whose `headers["Authorization"]` is what subsequent zenpy calls use | M3's in-place header rewrite after refresh; if wrong, every zenpy call after a token refresh 401s. Fallback: replace zenpy's session with a custom `requests.Session` (architectural change to `ZendeskClient`) |
| S3 | Zendesk authorization + token endpoint URLs | Manual check against `developer.zendesk.com` docs and the team's actual tenant URL; confirm `https://{subdomain}.zendesk.com/oauth/authorizations/new` and `/oauth/tokens` resolve | M6's URL constants; if Zendesk region uses different hostname, all auth attempts fail |
| S4 | Default port 47890 free on team machines | Each team member runs `lsof -i :47890` (macOS) or `ss -tlnp \| grep 47890` (Linux); if anyone has a standing conflict, pick a different default | M6's port constant; cosmetic if `--port` override works, but a default everyone has to override is bad UX |

**Outputs:** All four results recorded in the PR description (one paragraph each: "confirmed" or "needs amendment X"). No code committed. If any spike fails, amend the lean spec before starting M1.

---

## Milestone Sequence

*Resolution on ordering:* Risk-first and test-driven planners agreed on `token_store → oauth → ZendeskClient → server → callback_server → auth`. Bottom-up flipped to `token_store → oauth → callback_server → auth → ZendeskClient → server`, arguing that bottom-up keeps API-token mode unbroken longer. The merged plan uses the **risk-first/test-driven order** because the spike (S2) already mitigates the zenpy-integration risk before any milestone runs, but surfacing zenpy issues at M3 instead of M6 still gives one extra day of recovery time if S2 was wrong. Bottom-up's "API-token mode stays unbroken" advantage is real but small at six users.

*Resolution on M0 (skeleton commit):* Test-driven proposed an M0 that creates empty modules + test harness so all subsequent milestone tests fail with `NotImplementedError` instead of `ImportError`. Bottom-up folded the same idea into M1. Risk-first omitted it. **The merged plan keeps it as M1** — it's cheap (~2h) and the CI improvement requires touching `pyproject.toml` and the workflow file anyway.

### M1 — Test infrastructure + module skeletons

**Size: small (~2h).** Changes nothing about the running server. (CI changes are in the separate pre-step PR — see "Pre-Implementation Cleanup" item 3.)

Files:
- `pyproject.toml` — add `authlib>=1.7.0` to deps; add `cachetools>=5.3` (currently transitive); add `zendesk-auth = "zendesk_mcp_server.auth:main"` to `[project.scripts]`; add a dev group with `pytest>=8`, `pytest-mock`, `responses` (HTTP mocking for `auth.py` tests)
- `tests/__init__.py`, `tests/conftest.py` — fixtures: `tmp_home` (patches `Path.home()`), `clean_env` (strips `ZENDESK_*`), `mock_token_file(subdomain, data)`
- `src/zendesk_mcp_server/{token_store,oauth,callback_server,auth}.py` — empty modules with `NotImplementedError` stubs

Gate: `pytest --collect-only` exits 0; `uv build` succeeds; `uv lock --check` succeeds with Authlib added; `zendesk-auth` entry point installed.

### M2 — `token_store.py`

**Size: small (~3h).** Pure stdlib I/O, no external deps. Bottom of the dependency stack.

Implementation: `save(subdomain, token_dict)` writes via `os.replace` from `{subdomain}.json.tmp.{pid}`; `load(subdomain) -> dict` reads with required-keys validation. Required keys: `subdomain`, `access_token`, `token_type`. `expires_at` is optional and may be JSON `null`. Directory created with `0o700` on first write (no chmod if pre-existing). File chmod'd to `0o600` after write. `load()` raises `FileNotFoundError` on missing file (caller decides), `ValueError` with `"Token file at {path} is corrupt. Run zendesk-auth to re-authenticate."` on bad JSON or missing keys.

Test inventory: see oauth-test-strategy-lean.md "Token Storage" section. All ~12 items.

**Test-first invariants** (write the test before any production code in this milestone):
- `expires_at: null` round-trips as Python `None`, not string `"null"`
- Atomic write leaves no partial file on `os.replace` failure
- File permissions exactly `0o600`
- Temp filename includes `os.getpid()`

Gate: all `test_token_store.py` green.

### M3 — `oauth.py`: `OAuthTokenManager` + `OAuthRefreshError` + `@retry_on_401`

**Size: medium (~1d).** Depends on `token_store` (M2) and Authlib (M1).

*Resolution on bundling `@retry_on_401` here vs separately:* Test-driven and bottom-up bundled it with `OAuthTokenManager`; risk-first split it into M3. The merged plan **bundles it here** — the decorator's no-op-API-token-mode test and `OAuthRefreshError` propagation tests both need the manager mocked, so co-locating them avoids fixture duplication.

Implementation:
- `OAuthRefreshError(Exception)` — single message string
- `OAuthTokenManager.__init__(subdomain, client_id, client_secret)` — calls `token_store.load()`, raises immediately if missing; constructs Authlib `OAuth2Session(client_id, client_secret=..., update_token=self._on_token_updated)`
- `get_valid_token() -> str` — proactive refresh when `expires_at is not None and now > expires_at - 30`; otherwise return current `access_token`. The `expires_at is None` branch never refreshes proactively.
- `refresh()` — calls `session.refresh_token(token_endpoint, refresh_token=...)`. On Authlib's `invalid_grant`, raise `OAuthRefreshError("Refresh token rejected by Zendesk. Run zendesk-auth to re-authenticate.")` (verbatim per spec). On any other Authlib/network error, raise `OAuthRefreshError(str(e))`.
- `_on_token_updated(token, refresh_token=None)` — Authlib callback. Calls `token_store.save(subdomain, token)`. Updates `self._token = token`. **Plus** invokes any registered post-refresh hooks (used by `ZendeskClient.from_oauth` in M4 to update zenpy's session header in-place).
- `@retry_on_401` decorator — on 401, calls `self._token_manager.refresh()` (no-op if `self._token_manager is None`), retries once. Excludes `post_comment`, `apply_macro`, and `create_jira_link` (see M4 for the full method-by-method decorator policy and rationale).

**Test-first invariants:**
- 30-second proactive-refresh boundary (`now+29` triggers, `now+31` doesn't)
- `expires_at is None` does not trigger proactive refresh
- `invalid_grant` message contains "Run zendesk-auth to re-authenticate" verbatim
- Exclusion of `post_comment`, `apply_macro`, and `create_jira_link` (verified structurally — no `__wrapped__` — and behaviorally — 401 propagates without refresh call). Test all three.

Gate: all `oauth.py` tests green with Authlib mocked. The `@retry_on_401` API-token-mode no-op test passes (otherwise M4's `from_api_token` will crash on the first 401).

### M4 — `ZendeskClient` factory methods + `auth_header` property + decorator application

**Size: medium (~1d).** Modifies existing production code. The S2 spike result determines whether the in-place header rewrite is feasible or whether the fallback (custom `requests.Session`) is needed.

Implementation:
- Remove `__init__(subdomain, email, token)`. Add `from_api_token(cls, subdomain, email, token)` and `from_oauth(cls, subdomain, token_manager)` classmethods.
- `auth_header` becomes a `@property`. In API-token mode: returns `"Basic " + base64(f"{email}/token:{token}")` (same as today). In OAuth mode: calls `token_manager.get_valid_token()` and returns `f"Bearer {token}"`. **Live property, not cached.**
- `from_oauth` registers a post-refresh hook on `token_manager` that updates `self.client._session.headers["Authorization"]` in-place (or the S2-fallback architecture).
- Apply `@retry_on_401` to (24 methods — all reads, idempotent writes, and `create_ticket` per Dylan's call):
  `get_ticket`, `get_ticket_comments`, `get_ticket_attachment`, `get_tickets`, `get_all_articles`, `create_ticket`, `search_tickets`, `get_organization`, `search_users`, `get_group_users`, `get_groups`, `list_custom_statuses`, `get_jira_links`, `get_zendesk_tickets_for_jira_issue`, `list_ticket_fields`, `list_macros`, `preview_macro`, `get_view`, `list_views`, `get_view_tickets`, `add_tag`, `remove_tag`, `delete_jira_link`, `update_ticket`.

- **Explicitly NOT applied to (3 methods — non-idempotent writes with duplicate hazard):**
  - `post_comment` — retry posts a duplicate comment
  - `apply_macro` — macro actions can include posting comments / tag changes / state mutations; retry replays them
  - `create_jira_link` — retry creates a duplicate Jira link

- *Per Dylan: `create_ticket` IS decorated despite a similar duplicate hazard — Claude shouldn't be calling it routinely, and a duplicate ticket is easy to clean up.*

- `add_tag`, `remove_tag`, `delete_jira_link` are decorated because they're set-semantic (idempotent: re-adding/removing the same tag or re-deleting an already-deleted link is a no-op). `update_ticket` is decorated because re-applying the same field values produces the same end state.

**Test-first invariants:**
- `auth_header` property is live (two reads with different mock returns yield different values — no caching)
- `post_comment`, `apply_macro`, and `create_jira_link` are not decorated (structural + behavioral check on each)
- `from_api_token` regression: produces the same Basic auth header as the removed `__init__` did, byte for byte

Gate: all `test_zendesk_client.py` green. `python -c "from zendesk_mcp_server.zendesk_client import ZendeskClient; ZendeskClient.from_api_token('x','y@y.com','t').auth_header"` works without importing `oauth.py`.

### M5 — `server.py`: `build_zendesk_client()`

**Size: small (~3h).** Top of the stack. Pure wiring once M4 is done.

*Resolution on placement:* See "Open Questions for Dylan" — placement (module-import vs `server.main()`) is the one substantive disagreement that needs Dylan's call. The plan assumes **module-import time** (lean spec) but flags the decision.

Implementation:
- `build_zendesk_client()` reads env, mode-selects (truthy check on `ZENDESK_CLIENT_ID` so empty string falls through to API-token mode), constructs the right factory variant.
- Hard-fail if OAuth mode and token file missing — message contains "zendesk-auth".
- Hard-fail if API-token mode and email/key missing.
- Hard-fail if `ZENDESK_SUBDOMAIN` missing.
- Replace module-level `zendesk_client = ZendeskClient(...)` with `zendesk_client = build_zendesk_client()`.

**Test-first invariants:**
- `ZENDESK_CLIENT_ID = ""` does NOT trigger OAuth mode
- OAuth mode + missing token file → exception message contains "zendesk-auth"
- Importing `server` with no env vars set does NOT raise (regression guard against re-introduction of import-time I/O — *test-driven's catch*)

Gate: all `test_server.py` green. Subprocess integration test: launch server with bad env, assert non-zero exit. Manual: existing API-token mode still works end-to-end (set the three vars, start server, run `get_ticket`).

### M6 — `callback_server.py`

**Size: small (~3h).** Stdlib only, no Authlib, no `oauth.py` dependency. Fully testable in isolation.

Implementation: `CallbackServer(host="127.0.0.1", port=47890, expected_state, timeout_seconds=300)`. `wait_for_code() -> str` runs `serve_forever()` on a daemon thread, waits on `threading.Event`, returns code or raises `TimeoutError`. Handler validates state with `==` (no `hmac.compare_digest` — loopback only, six users). Handler returns 400 for missing code / state mismatch / wrong path / `?error=` param.

**Test-first invariants:**
- Bound to `127.0.0.1` (not `0.0.0.0`, not `localhost`)
- Server shuts down after one valid callback
- `threading.Event` set vs timeout properly distinguishable so the CLI doesn't hang (*test-driven's catch — R11 below*)

Gate: all `test_callback_server.py` green.

### M7 — `auth.py` CLI

**Size: medium (~1d).** Integrates everything. Most integration-heavy milestone.

Implementation: `argparse` for `--check`, `--port N`, `--no-browser`. `_run_auth(...)` does PKCE generation via Authlib, builds auth URL with `redirect_uri=http://127.0.0.1:{port}/callback`, starts `CallbackServer`, opens browser (or prints URL), waits for code, exchanges via `session.fetch_token()`, calls `token_store.save()`, prints success message verbatim. `_run_check(subdomain)` loads via `OAuthTokenManager`, prints subdomain + expiry or "no expiry — refresh on 401 only".

**Test-first invariants** (all spec-prescribed message wording):
- Success message: `"Authenticated as {subdomain}.zendesk.com. Token saved to {path}. Restart your MCP server."`
- State mismatch: `"state mismatch — possible CSRF or stale auth attempt"`
- Port-in-use: includes port number AND redirect-URI reminder
- Timeout: `"timed out waiting for callback"`
- `--check` with `expires_at: null`: `"no expiry — refresh on 401 only"`

Gate: all `test_auth.py` green. Integration happy-path (mocked Zendesk + real callback server) green. CLI smoke: `zendesk-auth --help` works.

---

## Manual Smoke (Single Team Member, Before Broader Rollout)

Not automated. Recorded in PR description with date and outcome before merge. Performed once.

1. Register OAuth client in Zendesk admin with redirect URI `http://127.0.0.1:47890/callback`.
2. Set `ZENDESK_CLIENT_ID` + `ZENDESK_CLIENT_SECRET` in `.env`. Run `zendesk-auth`.
3. Confirm browser opens, authorization completes, token file written at the expected path.
4. Run `zendesk-auth --check`. Confirm subdomain + expiry display.
5. Restart MCP server. Run a `get_ticket` call. Confirm response.
6. **Record `expires_in` behavior**: did Zendesk return it or not? This determines which refresh path users actually exercise (proactive vs reactive-only).
7. If `expires_in` is present: manually edit token file to set `expires_at` to a past timestamp; trigger a tool call; confirm proactive refresh fires and succeeds.

---

## Risk Register (Merged)

Severity: Critical = blocks the milestone if wrong; High = silent failure / data quality issue; Medium = recoverable but painful; Low = annoyance.

| # | Risk | Severity | Source | Mitigation | Gated by |
|---|---|---|---|---|---|
| R1 | Authlib `update_token` signature differs from spec assumption | Critical | All three | Spike S1; M3 test asserting `save()` called with correct dict | S1 + M3 |
| R2 | Zenpy `_session` missing or not a `requests.Session` on 2.0.56 | Critical | All three | Spike S2; pin zenpy version; M4 test of in-place header rewrite; documented fallback architecture | S2 + M4 |
| R3 | CLAUDE.md locked decisions still contradict lean spec at implementation time | High | Risk-first | Pre-implementation cleanup (item 1 above) | Before M1 |
| R4 | Old `implementation-plan.md` still in repo, confuses readers | Medium | All three | Pre-implementation cleanup (item 2 above) | Before M1 |
| R5 | CI doesn't run pytest — tests advisory not blocking | High | Bottom-up only | Pre-implementation cleanup (item 3 above), folded into M1 | M1 |
| R6 | `cachetools` not declared in `pyproject.toml` — environment-breaking on next dep upgrade | Medium | Bottom-up only | Add explicit dep in M1 | M1 |
| R7 | Zero existing tests = no regression baseline for API-token mode | High | Bottom-up only | M4 includes explicit `from_api_token` regression test against current behavior | M4 |
| R8 | Zendesk doesn't return `expires_in` (the common default) — proactive refresh never fires; reactive `@retry_on_401` is the only path | High | Test-driven only | M3 test of `expires_at is None` path; manual smoke step 6 records actual behavior | M3 + manual smoke |
| R9 | `auth_header` property accidentally cached at construction time, defeating refresh | High | All three | M4 test-first: change mock between two reads, both reads must reflect current value | M4 |
| R10 | A non-idempotent write method (`post_comment`, `apply_macro`, or `create_jira_link`) inadvertently decorated with `@retry_on_401`, causing a duplicate comment / replayed macro side-effects / duplicate Jira link | High | All three (extended for new methods after main rebase) | M3 + M4 tests structural + behavioral on all three excluded methods; module-level comment in `zendesk_client.py` listing the exclusions and why | M3 + M4 |
| R11 | `expires_at: null` round-trips as string "null" instead of Python `None` — `is None` check never matches | High | All three | M2 test-first round-trip | M2 |
| R12 | `ZENDESK_CLIENT_ID = ""` triggers OAuth mode, silently breaks API-token users with stray env var | Medium | All three | M5 explicit truthy-check test | M5 |
| R13 | Module-level `build_zendesk_client()` makes `server.py` untestable without env-patching at import time | Medium | Risk-first + test-driven | M5 regression test that import-without-env doesn't raise; if too painful, escalate `build_zendesk_client()` placement to Dylan | M5 |
| R14 | `redirect_uri` byte mismatch between auth URL and Zendesk admin registration | Medium | All three | M7 unit test asserts exact `http://127.0.0.1:{port}/callback` format; manual smoke catches real mismatch | M7 + manual smoke |
| R15 | `threading.Event` not set before callback server timeout — CLI hangs indefinitely | Medium | Test-driven only | M6 explicit injectable-timeout test; M7 catches `TimeoutError` | M6 + M7 |
| R16 | Port 47890 conflict on a team machine | Low | Risk-first + test-driven | Spike S4; `--port` override always available | S4 |
| R17 | Zendesk region uses different hostname than `{subdomain}.zendesk.com` | Low | Risk-first + test-driven | Spike S3 | S3 |
| R18 | Future non-idempotent method added without `@retry_on_401` audit | Low | Risk-first only | Module-level comment in `zendesk_client.py` listing excluded methods + why; code-review checklist entry | Post-merge maintenance |
| R19 | zenpy upgraded after pin — `_session` attribute moves silently | Low | Test-driven only | Pin zenpy in `pyproject.toml` with comment explaining why; re-run M4 test after any zenpy upgrade | Post-merge maintenance |

---

## PR Shape

**One PR. One commit per milestone (7 milestone commits + 1 spike-notes commit + 1 cleanup commit = ~9 commits).**

All three planners independently agreed on one PR. Justification:
- ~400 LOC across 4 new files and 2 modified files — reviewable as a unit
- The integration seams (`update_token` → `save()`, `auth_header` property → `get_valid_token()`, `build_zendesk_client()` mode selection) form a chain where any split produces dead code or half-wired states
- 6 internal users with a 30-second recovery path — no rollout-risk argument for staging

**If forced to split** (PR-size policy, reviewer availability): the cleanest boundary is **before M4** — i.e., PR-A = cleanup + spike + M1 + M2 + M3 (new modules only, zero behavior change to existing `ZendeskClient` and `server.py`); PR-B = M4 + M5 + M6 + M7 (existing files modified, server behavior changed). This is the only split where PR-A ships dead code that's safe and PR-B contains a coherent observable feature. Do not split within PR-B.

Use a **merge commit, not squash** — preserves milestone history for `git bisect` over the months-long shelf life. *(Bottom-up's recommendation; the others didn't specify.)*

---

## Test-First vs Interleaved (Consensus)

All three planners agreed: test-first for spec-prescribed correctness invariants; interleaved for everything else. The invariants list is the union of what they each called out:

**Test-first (must be red-then-green; don't let implementation accidentally satisfy):**

| Invariant | Milestone |
|---|---|
| `expires_at: null` round-trips as Python `None` | M2 |
| Atomic write leaves no partial file on `os.replace` failure | M2 |
| File permissions exactly `0o600` | M2 |
| Temp filename includes `os.getpid()` | M2 |
| 30-second proactive-refresh boundary (29s in / 31s out) | M3 |
| `expires_at is None` does not trigger proactive refresh | M3 |
| `OAuthRefreshError` from `invalid_grant` contains "Run zendesk-auth to re-authenticate" verbatim | M3 |
| `post_comment`, `apply_macro`, `create_jira_link` not decorated with `@retry_on_401` (`create_ticket` IS decorated) | M3 + M4 |
| `auth_header` property is live (not cached) | M4 |
| `from_api_token` produces byte-identical Basic auth header to the removed `__init__` | M4 |
| `ZENDESK_CLIENT_ID = ""` does not trigger OAuth mode | M5 |
| OAuth mode + missing token file → message contains "zendesk-auth" | M5 |
| Importing `server` with no env does not raise | M5 |
| Callback server bound to `127.0.0.1` (not `0.0.0.0`, not `localhost`) | M6 |
| All spec-prescribed CLI message wording (success, state mismatch, port-in-use, timeout, `--check` with null expiry) | M7 |

Everything else: write production code for one behavior, write its test, refactor, continue.

---

## Effort Sizing

*Resolution:* Estimates ranged from bottom-up's 3 days to risk-first's 5–6 days. The merged estimate splits the difference; bottom-up was likely too aggressive given there's no existing test infrastructure to start from, and risk-first too conservative for a 400-LOC feature.

| Milestone | Size | Estimate |
|---|---|---|
| Pre-implementation cleanup (CLAUDE.md, archive old plan) | small | 30 min |
| Spike (S1–S4) | small | 2–3h |
| M1 — Test infra + skeletons + CI | small | 2h |
| M2 — `token_store.py` | small | 3h |
| M3 — `oauth.py` (`OAuthTokenManager` + `@retry_on_401`) | medium | 1d |
| M4 — `ZendeskClient` refactor | medium | 1d |
| M5 — `server.py` wiring | small | 3h |
| M6 — `callback_server.py` | small | 3h |
| M7 — `auth.py` CLI | medium | 1d |
| Manual smoke | small | 1h |
| **Total** | | **~4–5 focused working days, ~1 week calendar with review** |

---

## Resolutions From Dylan (2026-04-26)

1. **`build_zendesk_client()` placement:** module-import time, in `server.py`. CLAUDE.md updated accordingly.
2. **CLAUDE.md cleanup:** done — drafted by Claude, see commit history.
3. **Old `implementation-plan.md`:** deleted.
4. **`create_ticket` and `@retry_on_401`:** decorated. Reasoning: Claude shouldn't be calling `create_ticket` routinely, and a duplicate ticket is easy to clean up if it happens.
5. **CI pytest:** split to a pre-step PR (not bundled into the OAuth PR). M1 no longer touches `.github/workflows/ci.yml`.
6. **(Added 2026-04-26 after rebase onto main, which brought 13 new tools):** Decorator policy for the new methods confirmed by Dylan: decorate all reads + idempotent writes (24 methods total); exclude `apply_macro` (replays macro side-effects) and `create_jira_link` (duplicate link). See M4 for the full enumerated list.
