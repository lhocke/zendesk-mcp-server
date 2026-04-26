# Rule Dump CLI

## Goal

Add a `zendesk-dump-rules` CLI that writes `triggers.json` and `automations.json` to disk, so skill authors working in Claude Code have a structured, grep-friendly reference for the team's Zendesk rule landscape. This is a developer tool, not a runtime tool — there is no MCP tool surface added by this feature.

## Motivation

When authoring skills against this MCP server, the skill author needs to understand what rules already fire automatically in Zendesk so the skill doesn't fight or duplicate them. The Zendesk admin UI is awkward for browsing 30+ rules, and a runtime MCP tool would be the wrong shape — the rules don't change per-ticket, so they don't belong in the per-call context. A one-shot CLI that dumps to disk keeps reference material adjacent to the skill code (commit-able alongside the skill spec) without polluting the runtime tool surface.

Macros are excluded — they already have first-class MCP tools (`list_macros`, `preview_macro`, `apply_macro`) because they're agent-triggered runtime actions, not server-side automation rules.

## CLI

### Command

`zendesk-dump-rules` — registered as a `console_script` in `pyproject.toml`, alongside `zendesk-auth`.

### Flags

- `--output-dir <path>` — directory to write JSON files. Default: current working directory.
- `--include-inactive` — dump all rules, including disabled ones. Default: active only.
- `--triggers-only` / `--automations-only` — filter to one type. Mutually exclusive. Default: both.

### Behavior

1. Build a Zendesk client via the existing `build_zendesk_client()` factory — works in both OAuth and API-token modes.
2. Fetch rules via zenpy:
   - Triggers: `client.triggers` (collection iterator, paginates transparently).
   - Automations: `client.automations` (same pattern).
3. Filter to active-only unless `--include-inactive` is passed.
4. Serialize each rule to a dict via zenpy's native `to_dict()` (or equivalent) — no field stripping; let skill authors trim what they don't want.
5. Write `triggers.json` and `automations.json` to the output directory. Each file is a JSON array of rule objects, sorted by `position` (Zendesk's evaluation order).
6. Print a one-line summary to stdout: e.g. `Wrote 47 triggers and 12 automations to /Users/dylan/skills/foo/`.
7. Exit 0 on success, non-zero with stderr message on failure.

### Output shape

Each rule entry is the zenpy-native dict, which includes at minimum:

- `id` (integer)
- `title` (string)
- `active` (bool)
- `position` (integer) — evaluation order within rule type
- `conditions` (object with `all` and `any` arrays)
- `actions` (array)
- Plus standard timestamps (`created_at`, `updated_at`) and any other fields zenpy serializes.

No re-shaping. The point is structured reference data; transformation is the skill author's choice.

## OAuth scope

Triggers and automations are admin-only endpoints in Zendesk. The current OAuth client requests `"read write"` (`auth.py:111`). Same uncertainty as KB search — Zendesk's documented scope model has separate admin scopes, and it's not certain whether `read` covers these endpoints under OAuth.

**Action for the work machine**: before implementing, run a smoke test against `client.triggers` under OAuth mode. If it returns rules, no scope change needed. If it returns 403, the OAuth client config in Zendesk Admin needs the appropriate admin scope added (Zendesk's docs should clarify which one — likely no specific `triggers:read` exists, so this may require the broader `read` already being sufficient OR a re-check of Dylan's user role on the OAuth grant). API-token mode should work regardless because tokens carry the underlying user's permissions directly.

If a scope change is needed, update `auth.py:111` and re-run `zendesk-auth` to acquire a token with the new scope.

## Non-goals

- No MCP tool surface. Triggers and automations stay accessible only via this CLI.
- No macro support — macros already have MCP tools.
- No re-shaping or summarization of rule data into markdown. JSON only; transformation is the caller's job.
- No diff/changelog functionality. Each run is a fresh snapshot.
- No write operations. Read-only dump.
- No category dump for triggers (Zendesk has trigger categories). If skill authors want category info, they can read it from each trigger's `category_id` field — categories are bounded enough that listing them isn't pressing.

## Implementation notes

- Place the CLI module at `src/zendesk_mcp_server/dump_rules.py`, mirroring how `zendesk-auth` is structured (`src/zendesk_mcp_server/auth.py` with a `main()` entry point referenced from `pyproject.toml`).
- Use `argparse` (stdlib) for flag parsing — consistent with the existing `zendesk-auth` CLI.
- Use `build_zendesk_client()` directly; do not bypass it. Errors from the factory (e.g. missing OAuth token, no `ZENDESK_*` env vars) propagate to the user with the same messages.
- Sort rules by `position` before writing so the JSON file ordering reflects Zendesk's evaluation order.
- JSON output: use `indent=2` for human readability — these files will be read by people and Claudes, not just machines.
- If `--triggers-only` and `--automations-only` are both passed, exit non-zero with a clear error.

## Validation (work machine)

- `zendesk-dump-rules` (no flags) writes `triggers.json` and `automations.json` to CWD, both containing only active rules.
- `zendesk-dump-rules --include-inactive` includes disabled rules in both files.
- `zendesk-dump-rules --output-dir /tmp/zd-rules` writes to that directory. The directory must already exist; the CLI does not auto-create (typo guard — `mkdir -p` would silently mis-target on a fat-finger).
- `zendesk-dump-rules --triggers-only` writes only `triggers.json`; `--automations-only` writes only `automations.json`.
- `zendesk-dump-rules --triggers-only --automations-only` exits non-zero with an error message.
- Output JSON is valid (parses with `json.loads`) and entries are sorted by `position`.
- Conditions and actions appear in the dumped data with their `all` / `any` shape intact.
- Works under both OAuth mode and API-token mode.
- Smoke check: open `triggers.json` and confirm at least one trigger you recognize from the Zendesk admin UI is present with the expected actions.
