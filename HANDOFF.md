# Handoff: Rule Dump CLI

**Branch:** `feat/rule-dump`
**Spec authored:** 2026-04-26
**Status:** Ready for implementation

## What's in this branch

- `specs/rule-dump/spec.md` — feature spec (no test-strategy or implementation-plan; scope didn't warrant either)

## Setup deltas (work machine)

Before implementing, smoke-test whether the current OAuth `read` scope grants access to triggers and automations:

1. With OAuth mode active (`ZENDESK_CLIENT_ID` set, valid token), open a Python REPL and try:
   ```python
   from zendesk_mcp_server.zendesk_client import build_zendesk_client
   c = build_zendesk_client()
   list(c.client.triggers)[:1]
   list(c.client.automations)[:1]
   ```
2. **If both return rules**: no scope change needed. Proceed with implementation.
3. **If either returns 403**: check Zendesk's OAuth scope docs for the appropriate admin scope. Update `auth.py:111` to include it, and have all users re-run `zendesk-auth` to acquire a token with the new scope. Note this in the eventual PR description.
4. API-token mode should work regardless (tokens carry the user's role permissions directly).

No new dependencies expected. `argparse` is stdlib; zenpy already has `triggers` and `automations` collections.

## Validation checklist (post-implementation)

- [ ] `zendesk-dump-rules` (no flags) writes `triggers.json` and `automations.json` to CWD, active rules only.
- [ ] `zendesk-dump-rules --include-inactive` includes disabled rules in both files.
- [ ] `zendesk-dump-rules --output-dir /tmp/zd-rules` writes to that directory; if the dir doesn't exist, the CLI exits non-zero with a clear error (no auto-create).
- [ ] `zendesk-dump-rules --triggers-only` writes only `triggers.json`; `--automations-only` writes only `automations.json`.
- [ ] `zendesk-dump-rules --triggers-only --automations-only` exits non-zero with an error explaining the flags are mutually exclusive.
- [ ] Output JSON is valid (parses with `json.loads`); entries are sorted by `position`.
- [ ] Each entry has `id`, `title`, `active`, `position`, `conditions` (with `all` / `any` arrays intact), `actions`.
- [ ] Works under OAuth mode (after any required scope adjustment) and under API-token mode.
- [ ] Spot check: open `triggers.json`, find a trigger you recognize from the Zendesk admin UI, confirm its actions match.
- [ ] One-line stdout summary on success, e.g. `Wrote 47 triggers and 12 automations to <path>`.

## Open questions for the implementer

None at spec time. One zenpy detail to verify during implementation:

- The exact serialization method on Trigger / Automation objects. zenpy's `to_dict()` is the typical accessor but the version pinned in this repo may vary. If `to_dict()` doesn't exist or omits fields, fall back to constructing the dict manually from the documented Zendesk API shape.

## After merge

- Delete this `HANDOFF.md` from `main` in the merge commit (or a follow-up).
- Leave `specs/rule-dump/` in place as the durable record.
- Update `GAPS.md`: move `list_triggers` and `list_automations` from Potential additions to Closed gaps, with a note that they ship as a CLI rather than MCP tools.
