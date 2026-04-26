import json
import os
import stat

import pytest

from zendesk_mcp_server import token_store


def _sample_token(**overrides):
    base = {
        "subdomain": "example",
        "access_token": "abc123",
        "refresh_token": "rfsh",
        "token_type": "Bearer",
        "expires_at": 1735689600,
        "scope": "read write",
    }
    base.update(overrides)
    return base


# --- happy path ---

def test_save_writes_valid_json_at_canonical_path(tmp_home):
    token_store.save("example", _sample_token())
    path = tmp_home / ".config" / "zendesk-mcp" / "example.json"
    assert path.exists()
    assert json.loads(path.read_text()) == _sample_token()


def test_save_atomic_no_tmp_file_remains(tmp_home):
    token_store.save("example", _sample_token())
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    assert list(config_dir.glob("*.tmp.*")) == []


def test_save_creates_directory_with_0o700(tmp_home):
    token_store.save("example", _sample_token())
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700


def test_save_file_permissions_0o600(tmp_home):
    token_store.save("example", _sample_token())
    path = tmp_home / ".config" / "zendesk-mcp" / "example.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_does_not_chmod_existing_directory(tmp_home):
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    config_dir.mkdir(mode=0o755, parents=True)
    # Re-chmod after mkdir in case umask stripped bits
    os.chmod(config_dir, 0o755)
    token_store.save("example", _sample_token())
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o755


def test_per_subdomain_isolation(tmp_home):
    token_store.save("example", _sample_token(subdomain="example", access_token="EX"))
    token_store.save("sandbox", _sample_token(subdomain="sandbox", access_token="SB"))
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    assert json.loads((config_dir / "example.json").read_text())["access_token"] == "EX"
    assert json.loads((config_dir / "sandbox.json").read_text())["access_token"] == "SB"


def test_load_returns_dict_for_well_formed_file(mock_token_file):
    expected = _sample_token()
    mock_token_file("example", expected)
    assert token_store.load("example") == expected


def test_expires_at_null_round_trips_as_python_none(tmp_home):
    token_store.save("example", _sample_token(expires_at=None))
    loaded = token_store.load("example")
    assert loaded["expires_at"] is None


def test_temp_filename_includes_pid(tmp_home, monkeypatch):
    captured = {}
    real_replace = os.replace

    def capture_replace(src, dst):
        captured["src"] = str(src)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", capture_replace)
    token_store.save("example", _sample_token())
    assert str(os.getpid()) in captured["src"]


# --- error paths ---

def test_load_missing_file_raises_filenotfounderror(tmp_home):
    with pytest.raises(FileNotFoundError):
        token_store.load("nonexistent")


def test_load_invalid_json_raises_with_actionable_message(tmp_home):
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    config_dir.mkdir(parents=True)
    (config_dir / "example.json").write_text("{not json")
    with pytest.raises(ValueError, match="Run zendesk-auth to re-authenticate"):
        token_store.load("example")


def test_load_valid_json_missing_required_key_raises_actionable(tmp_home):
    config_dir = tmp_home / ".config" / "zendesk-mcp"
    config_dir.mkdir(parents=True)
    incomplete = {"subdomain": "example", "token_type": "Bearer"}  # no access_token
    (config_dir / "example.json").write_text(json.dumps(incomplete))
    with pytest.raises(ValueError, match="Run zendesk-auth to re-authenticate"):
        token_store.load("example")


def test_save_mid_write_failure_no_partial_file(tmp_home, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        token_store.save("example", _sample_token())

    config_dir = tmp_home / ".config" / "zendesk-mcp"
    assert not (config_dir / "example.json").exists()
    assert list(config_dir.glob("*.tmp.*")) == []
