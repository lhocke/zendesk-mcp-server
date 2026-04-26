"""Integration-flavored tests for CallbackServer: spin up a real server on a
random port, drive it with real HTTP requests, assert behavior."""
import threading
import time
import urllib.error
import urllib.request

import pytest

from zendesk_mcp_server.callback_server import CallbackServer


def _run_server_in_background(server):
    """Run wait_for_code on a thread; return a result dict that gets populated
    once wait_for_code returns or raises."""
    result = {}

    def runner():
        try:
            result["code"] = server.wait_for_code()
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=runner)
    t.start()
    return t, result


def _hit(port: int, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --- happy path ---

def test_valid_callback_returns_code_and_success_html():
    server = CallbackServer(expected_state="STATE", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, body = _hit(port, "/callback?code=auth_code_xyz&state=STATE")
    assert status == 200
    assert b"Authentication complete" in body

    t.join(timeout=2)
    assert result.get("code") == "auth_code_xyz"
    assert "error" not in result


def test_server_bound_to_127_0_0_1():
    server = CallbackServer(expected_state="x", port=0, timeout_seconds=1)
    assert server.bound_address[0] == "127.0.0.1"
    # Cleanup — server's socket is open; close by triggering wait_for_code with timeout
    t, result = _run_server_in_background(server)
    t.join(timeout=2)


def test_server_shuts_down_after_one_valid_callback():
    server = CallbackServer(expected_state="STATE", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    _hit(port, "/callback?code=abc&state=STATE")
    t.join(timeout=2)
    assert "code" in result

    # Subsequent connection should fail because the server has shut down
    with pytest.raises(Exception):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback", timeout=0.5)


# --- error paths ---

def test_missing_code_returns_400():
    server = CallbackServer(expected_state="x", port=0, timeout_seconds=1)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, _ = _hit(port, "/callback?state=x")
    assert status == 400

    # No valid callback ever arrives — wait for timeout
    t.join(timeout=3)
    assert isinstance(result.get("error"), TimeoutError)


def test_oauth_error_param_signals_runtime_error():
    server = CallbackServer(expected_state="x", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, body = _hit(port, "/callback?error=access_denied")
    assert status == 400
    assert b"access_denied" in body

    t.join(timeout=2)
    assert isinstance(result.get("error"), RuntimeError)
    assert "access_denied" in str(result["error"])


def test_state_mismatch_returns_400_and_does_not_store_code():
    server = CallbackServer(expected_state="EXPECTED", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, body = _hit(port, "/callback?code=should_be_ignored&state=WRONG")
    assert status == 400
    assert b"State mismatch" in body

    t.join(timeout=2)
    # State mismatch surfaces as RuntimeError with the spec-prescribed wording,
    # not a TimeoutError — the CLI needs to distinguish.
    assert isinstance(result.get("error"), RuntimeError)
    assert "state mismatch" in str(result["error"])
    # Code was never stored
    assert server._code is None


def test_wrong_path_returns_400():
    server = CallbackServer(expected_state="x", port=0, timeout_seconds=1)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, _ = _hit(port, "/favicon.ico")
    assert status == 400
    t.join(timeout=2)


def test_extra_query_parameters_are_ignored():
    """Zendesk may append extras like &session_state=...; handler reads only
    code and state."""
    server = CallbackServer(expected_state="STATE", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    status, _ = _hit(port, "/callback?code=abc&state=STATE&session_state=ignored&foo=bar")
    assert status == 200
    t.join(timeout=2)
    assert result.get("code") == "abc"


# --- edge cases ---

def test_late_callback_after_event_already_set_returns_400():
    """A second request arriving between valid callback and shutdown must not
    overwrite the stored code."""
    server = CallbackServer(expected_state="STATE", port=0, timeout_seconds=2)
    port = server.bound_address[1]
    t, result = _run_server_in_background(server)

    # First valid callback
    status1, _ = _hit(port, "/callback?code=first&state=STATE")
    assert status1 == 200

    # Race: try to send a second request before server fully shuts down. May or may
    # not get through — what matters is that the code stored is "first", not "second".
    try:
        _hit(port, "/callback?code=second&state=STATE")
    except Exception:
        pass

    t.join(timeout=2)
    assert result.get("code") == "first"


def test_timeout_raises_timeouterror():
    """wait_for_code with no callback raises TimeoutError after timeout_seconds."""
    server = CallbackServer(expected_state="x", port=0, timeout_seconds=0.1)
    t, result = _run_server_in_background(server)

    t.join(timeout=2)
    assert isinstance(result.get("error"), TimeoutError)
    assert "timed out waiting for callback" in str(result["error"])


def test_port_in_use_raises_oserror():
    """If the requested port is already bound, HTTPServer __init__ raises OSError
    so the caller can report it cleanly."""
    blocker = CallbackServer(expected_state="x", port=0, timeout_seconds=1)
    blocked_port = blocker.bound_address[1]
    try:
        with pytest.raises(OSError):
            CallbackServer(expected_state="x", port=blocked_port, timeout_seconds=1)
    finally:
        # Drain blocker
        t, _ = _run_server_in_background(blocker)
        t.join(timeout=2)
