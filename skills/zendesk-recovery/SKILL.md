---
name: zendesk-recovery
description: Recovers a dropped Zendesk MCP server connection mid-session. Restarts the server if it's down and tells the user when to retry vs. when to run /mcp reconnect.
---

# zendesk-recovery

Use this when Zendesk tool calls start failing mid-session (errors like "tool not found", "MCP server unavailable", or silent failures).

**You have Bash tool access. Follow these steps exactly.**

---

## Recovery flow

### Step 1 — Run the lifecycle script

```bash
~/.claude/mcp-servers/zendesk-mcp-server/scripts/ensure-zendesk-mcp.sh
```

### Step 2 — Interpret the result

**Script printed "Started zendesk-mcp on..."** (exit 0, server was down):
- The server just restarted. Tell the user: "The Zendesk MCP server was down — I've restarted it. Try your last request again in a few seconds. If tool calls still fail, run `/mcp reconnect zendesk` to re-establish the connection."

**Script exited 0 with no output** (server was already running):
- The server is up but the connection is stale. Tell the user: "The server is running but the MCP connection dropped. Run `/mcp reconnect zendesk` to reconnect."

**Script exited non-zero** (failed to start within 10s):
- Surface the error and log path from stderr. Tell the user: "The server failed to start. Check the log at `/tmp/zendesk-mcp.log` (or `$ZENDESK_MCP_LOG` if overridden) for the error. Common causes: `.env` missing credentials, port 8000 in use by another process, or `uv` not on PATH."

---

## Limitation

Claude Code skills cannot execute slash commands. `/mcp reconnect zendesk` always requires the user to type it manually — this skill can't do it for you.
