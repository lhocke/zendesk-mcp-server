# Connection Skill (Lifecycle for HTTP MCP Server)

## Goal

Provide a lightweight lifecycle layer for the HTTP MCP server: auto-start when a Claude Code session begins, and a documented recovery flow when the server dies mid-session. Avoid the operational weight of a system agent (launchd / systemd / Docker) by leaning on Claude Code's `SessionStart` hook for proactive starts and Claude Code's built-in auto-reconnect / `/mcp reconnect` for in-session recovery.

## Dependency

This feature only makes sense once `feat/http-transport` has shipped — stdio MCP servers don't have a "is the server up" question (Claude Code spawns the process directly). Do not implement until HTTP transport is merged.

## Motivation

After the HTTP transport switch, three operational shapes were considered:

1. **System agent** (launchd plist or systemd unit): always-running, transparent. Setup and platform-specific maintenance overhead, plus possible Docker Desktop licensing concerns if the team had gone that route.
2. **Pure manual start**: user runs `zendesk-mcp-server --http` in a terminal each work session. Zero setup, but every user has to remember.
3. **Hook + script** (this spec): a `SessionStart` hook fires a small idempotent script that checks if the server is up and starts it if not. No always-running daemon. No remembering.

Option 3 wins for ~6 internal users with a months-long shelf life. The cost is one bash script, a documented settings.json hook config, and a small recovery skill — all artifacts that live in this repo and ship with the server.

## Components

### 1. Lifecycle script

`scripts/ensure-zendesk-mcp.sh` — idempotent shell script that ensures the HTTP MCP server is running on `127.0.0.1:8000` (or wherever the env config points).

**Behavior:**

1. Read `ZENDESK_MCP_PORT` (default 8000), `ZENDESK_MCP_LOG` (default `/tmp/zendesk-mcp.log`).
2. Check if something is listening on the port: `nc -z 127.0.0.1 $PORT`.
3. If yes, exit 0. (Don't disambiguate "our server" vs. "something else on this port" — if the port is wrongly occupied, the user finds out the next time they try a tool call. Keeping the script simple is more valuable than detecting that edge case.)
4. If no, start the server backgrounded: `nohup zendesk-mcp-server --http > "$ZENDESK_MCP_LOG" 2>&1 &`.
5. Poll the port for up to 10 seconds. If it comes up, exit 0 with a stdout one-liner like `Started zendesk-mcp on 127.0.0.1:8000 (logs: /tmp/zendesk-mcp.log)`.
6. If 10s elapses without the port responding, exit non-zero with stderr that points at the log file for diagnosis.

**Constraints:**
- `#!/usr/bin/env bash` — bash explicit, not `/bin/sh`. Tested on macOS bash 3.2 and modern Linux bash.
- Idempotent — concurrent invocations don't cause issues. The "is something listening" check is cheap; if two hooks race, the second one sees the first's server already up.
- No PID file. Process management is "is the port listening?" — simpler and avoids stale-PID footguns.

### 2. SessionStart hook

A snippet for the user's Claude Code `settings.json` (or `settings.local.json`) that calls the script when a session starts:

```jsonc
"hooks": {
  "SessionStart": [
    {
      "type": "command",
      "command": "/Users/<you>/Code/zendesk-mcp-server/scripts/ensure-zendesk-mcp.sh"
    }
  ]
}
```

The repo ships:
- The script itself.
- A README section showing the hook config above with placeholders the user fills in for their checkout path.
- An optional helper `scripts/install-hook.sh` that writes the snippet into `~/.claude/settings.local.json` (merging if the file exists). Nice-to-have, not required.

### 3. Recovery skill

A Claude Code skill at `skills/zendesk-recovery/SKILL.md` (in this repo, shipped for users to copy to `~/.claude/skills/zendesk-recovery/`).

**Skill purpose:** when the user notices Zendesk tool calls failing mid-session, invoking this skill walks the LLM through the recovery flow rather than the user having to remember commands.

**Skill behavior:**

1. Run `scripts/ensure-zendesk-mcp.sh`. (Skill has Bash tool access.)
2. If the script reports it started a fresh server: tell the user the server was restarted, suggest they retry their last tool call. If still failing after a few seconds, suggest running `/mcp reconnect zendesk` (since auto-reconnect may have given up).
3. If the script reports the server was already running: the issue is more likely a connection-side problem. Tell the user to run `/mcp reconnect zendesk` directly.
4. If the script exits non-zero: surface the log path and the stderr message; don't try to diagnose further — the user reads the log.

**Limitation acknowledged in the skill markdown:** Claude Code skills can't execute slash commands directly. `/mcp reconnect zendesk` always requires the user to type it. The skill's job is detection + restart + clear instruction, not full automation.

## Non-goals

- No system agent (launchd / systemd / Docker). Explicitly the alternative this spec replaces.
- No PID-file process tracking. Port-listening check is sufficient.
- No log rotation. `/tmp/zendesk-mcp.log` gets cleared by the OS; users who want persistent logs override `ZENDESK_MCP_LOG`.
- No cross-platform abstraction beyond bash. If the team ever has a Windows-non-WSL user, that's a separate effort.
- No skill auto-invocation on tool errors. Skills are user-invoked; we're not building a tool-error-detector.

## Implementation notes

- `scripts/ensure-zendesk-mcp.sh` should be `chmod +x` and tested on Mac before commit. Bash 3.2 (Mac default) is the lowest common denominator — avoid bash 4+ features like associative arrays.
- The skill markdown follows whatever shape `~/.claude/skills/<name>/SKILL.md` expects (frontmatter with name/description/tools, body with instructions). The implementer should look at an existing skill in `~/.claude/skills/` on the work machine for reference rather than guessing the schema.
- The `install-hook.sh` helper (if implemented) needs to merge into existing `settings.local.json` JSON without clobbering other hooks. Use `jq` if available; if not, the helper should print the snippet and ask the user to add it manually rather than risk corrupting the file.
- README needs a new section: "Lifecycle: starting the server automatically." Includes the script path, the hook snippet, and the recovery skill install instructions.

## Validation (work machine)

- `scripts/ensure-zendesk-mcp.sh` with no server running: starts the server, returns within 10s, server is reachable on `127.0.0.1:8000`.
- Same script with the server already running: returns immediately, no second process spawned (verify with `pgrep -af uvicorn`).
- `ZENDESK_MCP_PORT=9000 scripts/ensure-zendesk-mcp.sh`: starts on port 9000.
- Server crashed mid-session test: kill the server with `pkill -f "uvicorn.*zendesk_mcp_server"`. Run the script. Server comes back up. A subsequent tool call in Claude Code succeeds (within auto-reconnect window) or after `/mcp reconnect zendesk` (outside it).
- SessionStart hook configured in `settings.local.json`: starting a fresh `claude` session in this repo causes the hook to fire and the server to be reachable before the first tool call.
- Recovery skill: invoking `/zendesk-recovery` (or whatever the skill name resolves to) walks through the flow described above.
- Log file at `/tmp/zendesk-mcp.log` contains the server's stdout/stderr after a fresh start.
- Concurrency: running the script twice in parallel doesn't double-start the server.
