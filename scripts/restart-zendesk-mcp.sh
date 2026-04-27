#!/usr/bin/env bash
# Gracefully restarts the Zendesk MCP HTTP server.
# Sends SIGTERM to the listener, waits for the port to clear, then re-starts via ensure script.
set -euo pipefail

PORT="${ZENDESK_MCP_PORT:-8000}"
TIMEOUT=10
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find the process in LISTEN state on the port (not connected clients).
SERVER_PID=$(lsof -i "TCP:${PORT}" -s TCP:LISTEN -t 2>/dev/null || true)

if [ -z "$SERVER_PID" ]; then
    echo "No server listening on port ${PORT} — starting fresh."
    exec "$SCRIPT_DIR/ensure-zendesk-mcp.sh"
fi

echo "Sending SIGTERM to zendesk-mcp (pid ${SERVER_PID})..."
kill -TERM "$SERVER_PID"

# Wait for the port to clear.
elapsed=0
while nc -z 127.0.0.1 "$PORT" 2>/dev/null; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo "Server did not stop within ${TIMEOUT}s — sending SIGKILL." >&2
        kill -KILL "$SERVER_PID" 2>/dev/null || true
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

exec "$SCRIPT_DIR/ensure-zendesk-mcp.sh"
