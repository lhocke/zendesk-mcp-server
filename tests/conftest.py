import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Patch Path.home() to a tmp dir so token-file tests don't touch real $HOME."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def clean_env(monkeypatch):
    """Strip ZENDESK_* vars from os.environ for the test."""
    for key in list(os.environ):
        if key.startswith("ZENDESK_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("zendesk_mcp_server.auth.load_dotenv", lambda **kw: None)


@pytest.fixture
def mock_token_file(tmp_home):
    """Factory: write a token file at the canonical path for a subdomain."""
    def _write(subdomain: str, token_data: dict) -> Path:
        config_dir = tmp_home / ".config" / "zendesk-mcp"
        config_dir.mkdir(parents=True, exist_ok=True)
        path = config_dir / f"{subdomain}.json"
        path.write_text(json.dumps(token_data))
        return path
    return _write
