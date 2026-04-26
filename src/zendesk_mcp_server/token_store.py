"""Token file persistence for OAuth mode.

Pure stdlib; no Authlib, no zenpy, no MCP. Atomic write via os.replace, no
lock files (last-write-wins is acceptable at this scale — see oauth-spec-lean.md
"Out of Scope (and why)").
"""
import json
import os
from pathlib import Path

_CONFIG_DIR_PARTS = (".config", "zendesk-mcp")
_REQUIRED_KEYS = {"subdomain", "access_token", "token_type"}
_CORRUPT_MSG = "Token file at {path} is corrupt. Run zendesk-auth to re-authenticate."


def _config_dir() -> Path:
    return Path.home().joinpath(*_CONFIG_DIR_PARTS)


def _path(subdomain: str) -> Path:
    return _config_dir() / f"{subdomain}.json"


def _tmp_path(subdomain: str) -> Path:
    return _config_dir() / f"{subdomain}.json.tmp.{os.getpid()}"


def save(subdomain: str, token_data: dict) -> None:
    config_dir = _config_dir()
    if not config_dir.exists():
        config_dir.mkdir(mode=0o700, parents=True)

    final_path = _path(subdomain)
    tmp_path = _tmp_path(subdomain)

    try:
        tmp_path.write_text(json.dumps(token_data))
        os.replace(tmp_path, final_path)
        os.chmod(final_path, 0o600)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def load(subdomain: str) -> dict:
    path = _path(subdomain)
    raw = path.read_text()  # FileNotFoundError propagates per spec

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(_CORRUPT_MSG.format(path=path))

    if not isinstance(data, dict) or not _REQUIRED_KEYS.issubset(data.keys()):
        raise ValueError(_CORRUPT_MSG.format(path=path))

    return data
