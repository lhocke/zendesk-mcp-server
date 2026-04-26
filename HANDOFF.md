# Handoff: HTTP Transport for MCP Server

**Branch:** `feat/http-transport`
**Spec authored:** 2026-04-26
**Status:** Ready for implementation

## What's in this branch

- `specs/http-transport/spec.md` — feature spec (no test-strategy or implementation-plan; transport swap is contained, existing tests cover client logic unchanged)

## Setup deltas (work machine)

Two version-research items to settle before coding — neither is doable from the spec-authoring machine because they need PyPI / SDK changelog inspection:

1. **Pin a recent `mcp` SDK version**: current floor `>=1.1.2` is well behind. Check PyPI for the latest `mcp` version and the SDK changelog for the version that introduced or stabilized Streamable HTTP transport. Update the floor in `pyproject.toml` accordingly. Run the existing test suite after the bump to catch any breaking changes in the SDK API.
2. **Pin a recent `uvicorn` version**: new dep. `>=0.30` is a reasonable floor but verify the latest stable on PyPI and pin to that minor.

Also:
- Confirm the exact ASGI app entry point exposed by the bumped `mcp` SDK for Streamable HTTP. The spec assumes `zendesk_mcp_server.server:app` works for `uvicorn` — adjust if the SDK shape differs.
- Confirm the path Claude Code's MCP HTTP config expects (the spec uses `/mcp` as a placeholder — verify against [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)).
- Confirm the exact `settings.json` keys for HTTP MCP servers (`url`, `transport`, etc.) against the same docs before publishing the README change.

No new OAuth scope needed; transport is orthogonal to Zendesk-side auth.

## Validation checklist (post-implementation)

- [ ] Default mode (`ZENDESK_MCP_TRANSPORT` unset or `=stdio`) runs unchanged — existing Claude Code config with `command: zendesk` still works.
- [ ] `ZENDESK_MCP_TRANSPORT=http zendesk` starts the server bound to `127.0.0.1:8000`.
- [ ] `ZENDESK_MCP_PORT=9000 ZENDESK_MCP_TRANSPORT=http zendesk` binds to `127.0.0.1:9000`.
- [ ] Server is **not** reachable from non-loopback interfaces — `curl http://<machine-LAN-ip>:8000/mcp` should fail to connect.
- [ ] A Claude Code session configured for HTTP transport completes the MCP initialize handshake and lists Zendesk tools.
- [ ] End-to-end tool call works under HTTP mode (e.g. `get_ticket(<known_id>)` returns the ticket).
- [ ] Killing the server process mid-session: Claude Code shows the server as pending; restarting within ~16s, the session reconnects automatically (no need to issue `/mcp reconnect`).
- [ ] `/mcp reconnect zendesk` works as a manual reconnect when the auto-retry has given up.
- [ ] `uvicorn zendesk_mcp_server.server:app --reload --reload-dir src/zendesk_mcp_server` triggers restart on file save; subsequent tool calls succeed against the reloaded server.
- [ ] OAuth flow under HTTP mode: `zendesk-auth` produces a token, server reads it, tool calls succeed.
- [ ] Existing pytest suite passes unchanged.
- [ ] README has a new "Running over HTTP" section with the settings.json change, default port, and the reload command.
- [ ] `.env.example` lists `ZENDESK_MCP_TRANSPORT` and `ZENDESK_MCP_PORT` with defaults and one-line comments.

## Open questions for the implementer

- **Exposing `app` as a module attribute vs. constructing it inside `main()`**: the spec leans toward exposing it module-level so `uvicorn ... :app --reload` works directly. If the SDK's HTTP app construction has side effects that don't tolerate import-time execution, fall back to a `make_app()` factory and adjust the uvicorn invocation.
- **Default transport**: spec defaults to `stdio` for backward compatibility. If Dylan + team want to flip the default to `http` once it's validated, that's a one-line change — flag it during the PR review rather than deciding now.

## After merge

- Delete this `HANDOFF.md` from `main` in the merge commit (or a follow-up).
- Leave `specs/http-transport/` in place as the durable record.
- The follow-up research thread (Docker vs. native daemon for process supervision) becomes the next thing to spec, and feeds into the eventual deployment story.
- Once the team has migrated and HTTP is the de facto default, schedule a follow-up to drop stdio support and simplify the entry point.
