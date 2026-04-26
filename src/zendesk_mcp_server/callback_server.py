"""Local HTTP server that captures the OAuth authorization code.

Stdlib-only (http.server, threading, urllib.parse). Bound to 127.0.0.1.
Single-request lifecycle: shuts down after one valid callback or timeout.
"""


class CallbackServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 47890,
        expected_state: str = "",
        timeout_seconds: int = 300,
    ):
        raise NotImplementedError

    def wait_for_code(self) -> str:
        raise NotImplementedError
