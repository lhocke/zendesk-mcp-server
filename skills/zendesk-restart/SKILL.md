---
name: zendesk-restart
description: Gracefully restarts the Zendesk MCP HTTP server and prompts the user to reconnect. Use this when the server needs a restart to pick up new code or config changes.
---

# zendesk-restart

Use this when you need to restart the Zendesk MCP server — e.g. after a code update, config change, or when the server is misbehaving.

**You have Bash tool access. Follow these steps exactly.**

---

## Restart flow

### Step 1 — Run the restart script

```bash
~/.claude/mcp-servers/zendesk-mcp-server/scripts/restart-zendesk-mcp.sh
```

The script:
1. Finds the process in `LISTEN` state on `$ZENDESK_MCP_PORT` (default 8000) — never touches connected clients
2. Sends `SIGTERM` for a graceful shutdown
3. Falls back to `SIGKILL` if the process doesn't exit within 10s
4. Calls `ensure-zendesk-mcp.sh` to bring the server back up

### Step 2 — Interpret the result

**Script printed "Started zendesk-mcp on..."** (exit 0):
- Server restarted successfully. Tell the user: "The server has restarted. Run `/mcp reconnect zendesk` to re-establish the MCP connection, then retry your request."

**Script printed "No server listening on port N — starting fresh."** (exit 0):
- Server wasn't running; it has now been started. Same instruction: "Run `/mcp reconnect zendesk` to connect."

**Script exited non-zero:**
- Surface the error and log path. Tell the user: "The server failed to restart. Check `/tmp/zendesk-mcp.log` (or `$ZENDESK_MCP_LOG`) for details."

---

## Limitation

Claude Code skills cannot execute slash commands. `/mcp reconnect zendesk` always requires the user to type it manually.
