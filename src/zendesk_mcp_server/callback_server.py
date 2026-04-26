"""Local HTTP server that captures the OAuth authorization code.

Stdlib-only. Bound to 127.0.0.1 (must match the redirect URI registered with
Zendesk byte-for-byte; localhost can resolve to IPv6 on some systems and break
the match). Single-request lifecycle: shuts down after one valid callback or
after timeout_seconds.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


_SUCCESS_HTML = (
    b"<!doctype html><html><body>"
    b"<h1>Authentication complete</h1><p>You can close this tab.</p>"
    b"</body></html>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Built per-request by HTTPServer; reads state via self.server._cb."""

    def log_message(self, fmt, *args):
        # Silence stderr access logging — the CLI handles user-facing output.
        pass

    def _respond(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        cb = self.server._cb

        # If we've already captured a valid code, ignore subsequent requests
        # (e.g., browser favicon prefetch arriving in the shutdown window).
        if cb._event.is_set():
            self._respond(400, b"<h1>Already handled</h1>")
            return

        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self._respond(400, b"<h1>Bad request</h1>")
            return

        params = parse_qs(parsed.query)
        error = params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if error:
            cb._error = error
            cb._event.set()
            self._respond(400, f"<h1>Authentication failed: {error}</h1>".encode())
            return

        if not code:
            self._respond(400, b"<h1>Missing authorization code</h1>")
            return

        if state != cb._expected_state:
            # CSRF guard: do NOT store code; signal state-mismatch via _error so
            # the CLI can distinguish it from a timeout.
            cb._error = "state_mismatch"
            cb._event.set()
            self._respond(400, b"<h1>State mismatch</h1>")
            return

        cb._code = code
        cb._event.set()
        self._respond(200, _SUCCESS_HTML)


class CallbackServer:
    def __init__(
        self,
        expected_state: str,
        host: str = "127.0.0.1",
        port: int = 47890,
        timeout_seconds: float = 300,
    ):
        self._expected_state = expected_state
        self._timeout_seconds = timeout_seconds
        self._code: str | None = None
        self._error: str | None = None
        self._event = threading.Event()
        # HTTPServer binds the socket here; raises OSError if the port is in use.
        self._server = HTTPServer((host, port), _CallbackHandler)
        self._server._cb = self  # type: ignore[attr-defined]

    @property
    def bound_address(self) -> tuple[str, int]:
        return self._server.server_address

    def wait_for_code(self) -> str:
        """Run the server until a valid callback arrives or the timeout fires.
        Returns the authorization code on success. Raises TimeoutError on timeout
        or RuntimeError if the callback delivered an OAuth error."""
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        try:
            triggered = self._event.wait(timeout=self._timeout_seconds)
            if not triggered:
                raise TimeoutError(
                    f"timed out waiting for callback after {self._timeout_seconds}s"
                )
            if self._error == "state_mismatch":
                raise RuntimeError(
                    "state mismatch — possible CSRF or stale auth attempt"
                )
            if self._error:
                raise RuntimeError(f"authorization failed: {self._error}")
            assert self._code is not None
            return self._code
        finally:
            self._server.shutdown()
            self._server.server_close()
