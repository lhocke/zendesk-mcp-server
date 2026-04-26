"""zendesk-auth CLI entry point.

Runs the OAuth Authorization Code + PKCE flow against a Zendesk tenant.
Subcommands: (default) full auth flow, --check (inspect token file),
--port N (override callback port), --no-browser (print URL instead of opening).
"""
import argparse
import os
import re
import sys
import time
import webbrowser
from datetime import datetime, timezone
from urllib.parse import urlencode

from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from dotenv import load_dotenv

from zendesk_mcp_server import token_store
from zendesk_mcp_server.callback_server import CallbackServer

DEFAULT_PORT = 47890
CALLBACK_TIMEOUT_SECONDS = 300  # 5 min; tests monkeypatch to shorten
SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
SUBDOMAIN_PATTERN_HUMAN = SUBDOMAIN_RE.pattern


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="zendesk-auth")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect the saved token file (subdomain + expiry) and exit.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local callback server port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorization URL instead of opening a browser.",
    )
    args = parser.parse_args(argv)

    subdomain = os.getenv("ZENDESK_SUBDOMAIN")
    if not subdomain:
        print("Error: ZENDESK_SUBDOMAIN is required.", file=sys.stderr)
        return 1

    if args.check:
        return _run_check(subdomain)
    return _run_auth(subdomain, args.port, args.no_browser)


def _run_check(subdomain: str) -> int:
    try:
        token = token_store.load(subdomain)
    except FileNotFoundError:
        print(
            f"No token file for subdomain '{subdomain}'. Run zendesk-auth to authenticate.",
            file=sys.stderr,
        )
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    expires_at = token.get("expires_at")
    if expires_at is None:
        expiry_line = "Expiry: no expiry — refresh on 401 only"
    else:
        when = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
        expiry_line = f"Expiry: {when}"
    print(f"Subdomain: {subdomain}\n{expiry_line}")
    return 0


def _run_auth(subdomain: str, port: int, no_browser: bool) -> int:
    client_id = os.getenv("ZENDESK_CLIENT_ID")
    client_secret = os.getenv("ZENDESK_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "Error: ZENDESK_CLIENT_ID and ZENDESK_CLIENT_SECRET are required for OAuth. "
            "See README for setup.",
            file=sys.stderr,
        )
        return 1

    if not SUBDOMAIN_RE.fullmatch(subdomain):
        print(
            f"Error: ZENDESK_SUBDOMAIN must match {SUBDOMAIN_PATTERN_HUMAN}",
            file=sys.stderr,
        )
        return 1

    code_verifier = generate_token(48)
    code_challenge = create_s256_code_challenge(code_verifier)
    state = generate_token(32)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "read write",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = (
        f"https://{subdomain}.zendesk.com/oauth/authorizations/new?"
        + urlencode(auth_params)
    )

    try:
        server = CallbackServer(
            expected_state=state, port=port, timeout_seconds=CALLBACK_TIMEOUT_SECONDS
        )
    except OSError:
        print(
            f"Error: Port {port} in use. Pass --port N to use a different port. "
            f"Make sure http://127.0.0.1:N/callback is registered as a redirect URI "
            f"in your Zendesk OAuth client.",
            file=sys.stderr,
        )
        return 1

    if no_browser:
        print(f"Open this URL in a browser to authorize:\n{auth_url}")
    else:
        webbrowser.open(auth_url)
        print("Browser opened. Waiting for authorization...")

    try:
        code = server.wait_for_code()
    except TimeoutError:
        print("Error: timed out waiting for callback", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    session = OAuth2Session(
        client_id,
        client_secret=client_secret,
        code_challenge_method="S256",
    )
    try:
        token = session.fetch_token(
            f"https://{subdomain}.zendesk.com/oauth/tokens",
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        print(f"Error: token exchange failed: {e}", file=sys.stderr)
        return 1

    token_dict = dict(token)
    if "expires_in" in token_dict and token_dict["expires_in"] is not None:
        token_dict["expires_at"] = int(time.time()) + int(token_dict["expires_in"])
    else:
        token_dict["expires_at"] = None
    token_dict["subdomain"] = subdomain

    try:
        token_store.save(subdomain, token_dict)
    except OSError as e:
        print(f"Error: failed to write token file: {e}", file=sys.stderr)
        return 1

    print(
        f"Authenticated as {subdomain}.zendesk.com. "
        f"Token saved to {token_store._path(subdomain)}. "
        f"Restart your MCP server."
    )
    return 0
