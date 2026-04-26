# OAuth Implementation Handoff

Status as of 2026-04-26 (overnight session). Pick up tomorrow on the other machine.
**Delete this file after the work machine catches up.**

## What's done

All seven milestones complete on `feat/oauth`. **115 tests passing locally.**

| # | Commit | Tests added |
|---|---|---|
| Lean docs | `Replace 3000-line OAuth spec with lean design docs` | – |
| M1 | `Add test scaffolding and OAuth module stubs` | conftest, stubs |
| M2 | `Implement token_store with atomic write and corruption detection` | 13 |
| M3 | `Implement OAuthTokenManager and @retry_on_401 with chain-walking 401 detection` | 19 |
| M4 | `Refactor ZendeskClient with factory methods, auth_header property, and @retry_on_401` | 37 |
| M5 | `Add build_zendesk_client mode-selection factory and wire into server.py` | 8 |
| M6 | `Add CallbackServer for OAuth authorization code capture` | 11 |
| M7 | `Implement zendesk-auth CLI with PKCE flow and --check subcommand` | 27 |

## Branch state

- `feat/oauth` is **rebased onto `origin/main`** (was 8 commits behind because of the Jira/skills work merged from the work machine).
- Local branch has **diverged from `origin/feat/oauth`** (the original `eaddf48` was rebased into `3161aa6`). Push will need `--force-with-lease`.
- Working tree clean; only untracked files are `CLAUDE.md` and `REVIEW_PROTOCOL.md` (machine-local per preference).

## Outstanding work for the work machine

### Required before merge

1. **Run `uv lock`.** I couldn't regenerate `uv.lock` because uv isn't installed on this machine — used a pip-based `.venv` instead. The pyproject.toml has the new deps (`authlib>=1.7.0`, `cachetools>=5.3`, dev group) but the lock file is stale. Run `uv lock` then commit the updated lock.
2. **Run the test suite via uv to confirm it passes there too:** `uv run pytest`. Should be 115 green.
3. **Force-push to GitHub:** `git push --force-with-lease origin feat/oauth`. Then open the PR.

### Manual end-to-end smoke (one team member, before broader rollout)

Cannot be automated. Per the lean spec / plan:

1. Register an OAuth client in Zendesk admin with redirect URI exactly `http://127.0.0.1:47890/callback`.
2. Set `ZENDESK_CLIENT_ID` + `ZENDESK_CLIENT_SECRET` in `.env`.
3. Run `zendesk-auth`. Confirm browser opens, auth completes, token file written at `~/.config/zendesk-mcp/{subdomain}.json` with mode `0o600`.
4. Run `zendesk-auth --check`. Confirm subdomain + expiry display.
5. Restart the MCP server. Run any tool (e.g., `get_ticket`) and confirm it returns data.
6. **Record whether Zendesk returned `expires_in`** in the PR description — this determines which refresh path actually runs in production:
   - If returned: proactive refresh fires within 30s of expiry.
   - If absent (the common default): only `@retry_on_401` runs, on 401.
7. If `expires_in` is present, manually edit token file to set `expires_at` to a past timestamp; trigger a tool call; confirm proactive refresh fires.

### S4 spike — port 47890 availability

Have each of the 6 team members run `lsof -i :47890` (or `ss -tlnp | grep 47890` on Linux) before first use. If any conflict, document the `--port N` override.

### CI pre-step PR (per Dylan's prior decision — split from OAuth PR)

Add `uv run pytest` to `.github/workflows/ci.yml` after `uv build`. Currently CI only runs `uv build`, so the test suite is advisory until this lands.

### README rewrite (lower priority — can be follow-up)

The rebased `README.md` still has the OBSOLETE OAuth section from the old spec (references `--revoke`, lock files, etc. that no longer exist). Not committed by this work — the rebase auto-merged it back in. Either rewrite to match the lean spec or strip the OAuth section entirely and add a fresh one. Suggested replacement content already in `oauth-spec-lean.md` "Migration for existing API-token users".

## Key decisions made / spec deviations

1. **`build_zendesk_client()` placement:** module-import time (in `server.py`), per Dylan's call. Lives in `zendesk_client.py` next to factory classmethods so tests can import it without triggering `server.py` init.
2. **Decorator policy on the 27 ZendeskClient methods:** 24 decorated with `@retry_on_401`, 3 excluded (`post_comment`, `apply_macro`, `create_jira_link` — all non-idempotent writes that would replay side-effects on retry). `create_ticket` IS decorated per Dylan's call (Claude shouldn't be calling it routinely; duplicate is easy to clean up).
3. **`@retry_on_401` walks the exception chain.** Existing methods wrap underlying HTTPError in `raise Exception(...)` without `from`, which sets `__context__`. The decorator walks `__cause__ → __context__` to find the underlying 401, so we did NOT need to refactor every method (the prior 3000-line spec's "exception-wrapper stripping" was avoided).
4. **Spike S2 (zenpy `_session`):** spec assumption was wrong — `_session` doesn't exist on Zenpy 2.0.57. Workaround: `client.tickets.session` is the shared `requests.Session`, and rewriting its `Authorization` header propagates to every API helper (verified). Pinned `zenpy==2.0.56` in pyproject.toml as a hedge against future API drift.
5. **`__init__.py` deferred-import refactor.** Moved `from . import server` inside `main()` so submodules can be imported without triggering server.py module init. Required for testing without env vars set everywhere.

## Spike findings

Full details written to `/tmp/oauth-spike-findings.md` during the session, but `/tmp` won't survive across machines. The findings are encoded in:
- `oauth.py` (`_on_token_updated` callback signature comment)
- `zendesk_client.py` (`_on_token_refreshed` comment about `client.tickets.session`)
- This handoff doc

S1 (Authlib) and S3 (Zendesk endpoints) confirmed as-spec'd. S2 deviated as noted above.

## Where things live

- Spec: `oauth-spec-lean.md`
- Test strategy: `oauth-test-strategy-lean.md`
- Plan: `oauth-implementation-plan-lean.md`
- New code: `src/zendesk_mcp_server/{auth,callback_server,oauth,token_store}.py`
- Modified: `src/zendesk_mcp_server/{__init__,server,zendesk_client}.py`
- Tests: `tests/test_{auth,build_zendesk_client,callback_server,oauth,token_store,zendesk_client}.py`
- Dependencies: added to `pyproject.toml` (lock file pending — see Outstanding Work)
