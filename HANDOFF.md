# OAuth Implementation Handoff

Status as of 2026-04-26 (second session — this machine). Pick up here next session.
**Delete this file after OAuth is merged.**

## What's done

All seven milestones complete on `feat/oauth`. **115 tests passing.**

| # | Commit | Notes |
|---|---|---|
| (see previous handoff history) | all 7 milestones | see git log |
| Fix + lock + docs + CI | `Fix test isolation, update lock file, correct README OAuth docs, add pytest to CI` | this session |
| Auth mode logging | `Add auth_mode log line to build_zendesk_client` | this session — not yet pushed |

### This session's changes (committed, not yet pushed)
- `uv.lock` — regenerated (was stale; authlib, cryptography, pytest deps now locked)
- `tests/conftest.py` — `clean_env` fixture now patches `load_dotenv` to a no-op so `.env` on disk doesn't bleed into isolation tests (fixed 1 failing test; 115/115 green)
- `README.md` — corrected OAuth section: wrong redirect URI (`localhost:8085` → `127.0.0.1:47890`), wrong token path (`~/.zendesk_mcp` → `~/.config/zendesk-mcp`), added `--no-browser` and `--port N` flags, added mode-coexistence note
- `.github/workflows/ci.yml` — added `uv run pytest` step after `uv build`
- `src/zendesk_mcp_server/zendesk_client.py` — added `import logging` + `logger.warning("auth_mode=oauth subdomain=%s", subdomain)` in `build_zendesk_client()` so startup logs confirm which mode is active

## Branch state

- `feat/oauth` is **1 commit ahead of `origin/feat/oauth`** (the logging change — needs to be pushed)
- Working tree clean after committing logging change
- MCP config (`~/.claude.json`) has been redirected to `~/zendesk-mcp-server` for dev work — this is the correct protocol going forward

## Smoke test status

- `zendesk-auth` ran successfully — token saved to `~/.config/zendesk-mcp/mantl.json`
- `zendesk-auth --check` confirms: `Subdomain: mantl`, `Expiry: no expiry — refresh on 401 only`
- **Zendesk did NOT return `expires_in`** — only `@retry_on_401` refresh path runs in production (no proactive refresh). Record this in the PR description.
- End-to-end tool call not yet validated with OAuth — was hitting API token mode (MCP pointed at installed copy). Redirect is now in place; needs a `/hooks` reconnect then a test tool call to confirm OAuth path.

## Outstanding work for next session

### Must do before merge

1. **Push the logging commit:** `git push origin feat/oauth`
2. **Reconnect MCP server:** run `/hooks` in Claude Code to pick up the redirected config
3. **Validate OAuth end-to-end:** fire any tool call (e.g. `get_ticket`) and confirm `auth_mode=oauth` appears in server logs
4. **Open the PR** — note in description:
   - Zendesk did NOT return `expires_in`; only retry-on-401 refresh runs in production
   - Manual smoke test completed (token flow, --check, expiry behavior)

### Manual smoke remaining (step 7 from original handoff)
If you want to test proactive refresh path (only relevant if `expires_in` ever shows up):
- Manually edit token file to set `expires_at` to a past timestamp
- Trigger a tool call and confirm proactive refresh fires
- Per smoke test findings this is moot for Zendesk's current OAuth implementation

### Port availability check
Have each of the 6 team members run `lsof -i :47890` before first use.

### CI pre-step PR (separate from OAuth PR)
`uv run pytest` is now in `ci.yml` on `feat/oauth` — this will land when OAuth merges. No separate PR needed unless you want it earlier on main.

### README (done)
OAuth section is corrected and committed. No further work needed.

## Key context

- Zendesk does NOT return `expires_in` — only `@retry_on_401` fires in prod
- MCP config should always point to `~/zendesk-mcp-server` during dev work (not `~/.claude/mcp-servers/zendesk-mcp-server`)
- Token file: `~/.config/zendesk-mcp/mantl.json` (written, valid)
- `build_zendesk_client()` now logs `auth_mode=oauth` or falls through to API-token — use this to confirm which path is active

## Where things live

- Spec: `oauth-spec-lean.md`
- Test strategy: `oauth-test-strategy-lean.md`
- Plan: `oauth-implementation-plan-lean.md`
- New code: `src/zendesk_mcp_server/{auth,callback_server,oauth,token_store}.py`
- Modified: `src/zendesk_mcp_server/{__init__,server,zendesk_client}.py`
- Tests: `tests/test_{auth,build_zendesk_client,callback_server,oauth,token_store,zendesk_client}.py`
