# HTTP Transport for MCP Server

## Goal

Migrate the MCP server's transport from stdio to HTTP (Streamable HTTP via the official `mcp` SDK) so that Claude Code's auto-reconnect and `/mcp reconnect` mechanisms apply, and so that an in-session reload pattern (file-save → server restart → Claude Code reconnects) becomes possible. Stdio mode stays available as a fallback during transition.

## Motivation

Research (2026-04-26) on Claude Code's MCP behavior turned up two confirmed limitations of stdio transport that bite this team in practice:

1. **No mid-session recovery**: when a stdio MCP server crashes or hangs, Claude Code does not restart it; the only fix today is killing the `claude` CLI session and starting a new one. Documented in [github.com/anthropics/claude-code/issues/45146](https://github.com/anthropics/claude-code/issues/45146) and [#43177](https://github.com/anthropics/claude-code/issues/43177).
2. **No hot-reload during development**: stdio servers are spawned once at session start and not reloaded when the source changes. Documented feature request: [#46426](https://github.com/anthropics/claude-code/issues/46426).

HTTP / Streamable HTTP transport gets both for free:
- Claude Code retries failed HTTP servers automatically (5 attempts, 1–16s exponential backoff).
- `/mcp reconnect <name>` is available as a manual recovery command.
- A file-save → server restart cycle (via `uvicorn --reload` during development) becomes a reload pattern, since Claude Code reconnects to the bounced process automatically.

Sources for the above: official MCP docs at [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp). Verify against the docs before pinning behavior — Claude Code iterates quickly.

## Scope

**In scope**:
- Add HTTP / Streamable HTTP transport to the existing `mcp` server, served via `uvicorn`.
- Preserve stdio as a parallel mode for fallback / migration.
- Bump the `mcp` SDK floor to a recent version with documented Streamable HTTP support.
- Add `uvicorn` as a runtime dep.
- Update README and `.env.example` so users can switch their Claude Code config to HTTP.
- Wire up `--reload` development mode (file watching).

**Out of scope (deferred to follow-up work)**:
- Process supervision (launchd plist, systemd unit, Docker image). Pending separate research thread comparing Docker vs. native daemon.
- Remote (non-localhost) hosting. Requires real auth between Claude Code and the server; out of scope for this team's laptop-only deployment.
- Multi-user shared deployment.
- Removing stdio support entirely. Keep both modes; drop stdio in a follow-up once the team has migrated.

## Architecture

### Transport selection

Mode is controlled by an env var or CLI flag. Default = stdio for backward compatibility; flip to HTTP via opt-in until the team has fully migrated, then revisit.

- `ZENDESK_MCP_TRANSPORT=stdio` (default) or `=http`
- Or a CLI flag on the existing entry point (e.g. `zendesk --http`)

Whichever shape is implemented, the env var is the canonical knob — Claude Code's MCP config can pass env vars cleanly via `settings.json`.

### HTTP server config

When `ZENDESK_MCP_TRANSPORT=http`:

- Bind to `127.0.0.1` only. **Never** bind to `0.0.0.0` or `::` — the trust boundary is "local user on this machine," same model as the OAuth callback server.
- Default port: `8000`. Override via `ZENDESK_MCP_PORT`. (8765 is reserved for the OAuth callback's ephemeral use; pick a different default.)
- Use `uvicorn` to serve the ASGI app the `mcp` SDK exposes for Streamable HTTP transport. Exact API entry point is SDK-version-dependent — verify on the work machine when bumping the SDK floor.

### Claude Code client config

End-user `settings.json` for MCP changes from the stdio command form:

```jsonc
"zendesk": {
  "command": "zendesk",
  "args": []
}
```

to the HTTP form:

```jsonc
"zendesk": {
  "url": "http://127.0.0.1:8000/mcp",
  "transport": "streamable-http"
}
```

Exact key names (`url`, `transport`, etc.) follow Claude Code's documented MCP HTTP config — verify shape on the work machine before publishing the README change. The path component (`/mcp` above) depends on what the SDK mounts; confirm during implementation.

### Dev reload

Run via `uvicorn zendesk_mcp_server.server:app --reload --reload-dir src/zendesk_mcp_server` during development. On file save, uvicorn restarts the worker; Claude Code's auto-reconnect catches the bounce within ~1–16s.

For non-dev runs, no reload — the user starts the server once and lets it run. Restart is a deliberate action.

## Auth / security

- 127.0.0.1 binding is the security boundary. No client-server auth needed because the client (Claude Code) and server (this MCP) run as the same user on the same machine. Same model as the existing OAuth callback server.
- The OAuth flow between the MCP server and Zendesk is unaffected by transport change. Token storage, refresh, `@retry_on_401` — all transport-agnostic.
- If the team ever wants remote hosting, that's a separate spec — MCP HTTP transport supports OAuth between client and server, but it's a real lift.

## Dependency changes

- **`mcp`**: bump floor from `>=1.1.2` to a recent version with stable Streamable HTTP support. Exact version to research and pin on the work machine — check PyPI for current and the SDK changelog for the version that introduced or stabilized Streamable HTTP.
- **`uvicorn`**: new runtime dep. Pin a current minor (e.g. `>=0.30`) — verify on work machine.
- **`zenpy`, `authlib`, `cachetools`, `python-dotenv`**: unaffected.
- Dev deps unaffected. Existing pytest suite targets client logic, not transport, so it should pass unchanged.

## Implementation notes

- The current entry point is `server.py:main()` using `mcp.server.stdio.stdio_server()` (server.py:11, server.py:731-745). Refactor to:
  1. Read `ZENDESK_MCP_TRANSPORT` (default `stdio`).
  2. If `stdio`: keep current behavior unchanged.
  3. If `http`: build the SDK's HTTP/Streamable HTTP ASGI app and serve via uvicorn programmatically (or expose `app` as a module-level ASGI callable so `uvicorn zendesk_mcp_server.server:app` works directly — likely cleaner for the `--reload` story).
- Module-import-time work in `server.py` (the `build_zendesk_client()` call, tool registrations) runs once per uvicorn worker. Keep that pattern; it matches the existing import-time setup and the OAuth team's prior decision.
- `README.md` needs a new section: "Running over HTTP" with the `settings.json` change, port info, and the reload command.
- `.env.example`: add `ZENDESK_MCP_TRANSPORT` and `ZENDESK_MCP_PORT` lines with defaults and a one-line comment.

## Validation (work machine)

- `ZENDESK_MCP_TRANSPORT=http zendesk` (or equivalent) starts the server bound to `127.0.0.1:8000`.
- `curl http://127.0.0.1:8000/mcp` (or whatever path the SDK mounts) responds to a basic MCP initialize handshake.
- A Claude Code session configured for HTTP transport connects successfully and tool calls (e.g. `get_ticket`) work end-to-end.
- Killing the server process while a Claude Code session is connected produces a brief disconnect; restarting the server within ~16s, the session reconnects automatically (Claude Code's documented auto-retry behavior).
- `uvicorn zendesk_mcp_server.server:app --reload --reload-dir src/zendesk_mcp_server` triggers a restart on file save, and Claude Code reconnects on the next tool call.
- Stdio mode (default, no env var set) still works exactly as before — the existing local test setup that uses `command: zendesk` in `settings.json` is unaffected.
- Existing pytest suite passes unchanged.
- OAuth flow still works in HTTP mode (`zendesk-auth` produces a token, server reads it, tool calls succeed).
