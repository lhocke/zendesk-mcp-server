"""Token file persistence for OAuth mode.

Pure stdlib; no Authlib, no zenpy, no MCP. Atomic write via os.replace, no
lock files (last-write-wins is acceptable at this scale — see oauth-spec-lean.md
"Out of Scope (and why)").
"""


def save(subdomain: str, token_data: dict) -> None:
    raise NotImplementedError


def load(subdomain: str) -> dict:
    raise NotImplementedError
