#!/usr/bin/env bash
# Ensures the Zendesk MCP HTTP server is running. Idempotent — safe to call on every session start.
set -euo pipefail

PORT="${ZENDESK_MCP_PORT:-8000}"
LOG="${ZENDESK_MCP_LOG:-/tmp/zendesk-mcp.log}"
TIMEOUT=10

if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    exit 0
fi

ZENDESK_MCP_TRANSPORT=http nohup uv --directory ~/.claude/mcp-servers/zendesk-mcp-server run zendesk \
    > "$LOG" 2>&1 &

elapsed=0
while ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo "zendesk-mcp failed to start within ${TIMEOUT}s — check logs: $LOG" >&2
        exit 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

echo "Started zendesk-mcp on 127.0.0.1:${PORT} (logs: ${LOG})"
