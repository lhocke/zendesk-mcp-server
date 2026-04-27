# Handoff: KB Search Tools

**Branch:** `feat/kb-search`
**Spec authored:** 2026-04-26
**Status:** Ready for implementation

## What's in this branch

- `specs/kb-search/spec.md` — feature spec (no test-strategy or implementation-plan; scope didn't warrant either)

## Setup deltas (work machine)

Before implementing, verify whether the current OAuth `read` scope grants Help Center read access:

1. With OAuth mode active (`ZENDESK_CLIENT_ID` set, valid token), trigger a read of the `zendesk://knowledge-base` resource (e.g. via the MCP inspector or a test script that calls `get_all_articles`).
2. **If it returns articles**: no scope change needed. Proceed with implementation.
3. **If it returns 403 / scope error**:
   - Add `hc:read` to the OAuth client config in Zendesk Admin (Admin Center → Apps and integrations → APIs → OAuth clients).
   - Update `auth.py:111` from `"scope": "read write"` to `"scope": "read write hc:read"`.
   - Have all users re-run `zendesk-auth` to acquire a token with the new scope.
   - Note this in the eventual PR description so it's visible to the team.

No new dependencies expected. Snippet synthesis can use stdlib `html.parser`.

## Validation checklist (post-implementation)

- [ ] `search_articles("permissions")` returns at least one hit with `section` and `category` populated.
- [ ] `search_articles("permissions", section_id=<known_id>)` narrows correctly to that section.
- [ ] `search_articles("permissions", limit=3)` honors the limit; passing `limit=100` clamps to 25.
- [ ] `get_article(<known_id>)` returns the full HTML body matching what's rendered in the Help Center UI.
- [ ] `list_sections()` returns all sections, each with the correct parent `category` id + name.
- [ ] Snippets are ~200 chars, HTML-stripped, word-boundary truncated, with `...` appended when truncated.
- [ ] Empty-result query (e.g. `search_articles("zzzzzznoresults")`) returns `[]`, not an error.
- [ ] Existing `zendesk://knowledge-base` resource still works (regression check).
- [ ] All three tools work end-to-end under OAuth mode.

## Open questions for the implementer

None at spec time. Two zenpy details to confirm during implementation (spec calls these out):
- Exact param names on `client.help_center.articles.search()` (`section` vs `section_id`, etc.).
- Article fetch accessor — `client.help_center.articles(id=...)` vs `articles.show(id=...)` or similar.

Adjust the wrappers to match whatever zenpy actually exposes; the tool-level API in the spec is the contract.

## After merge

- Delete this `HANDOFF.md` from `main` in the merge commit (or a follow-up).
- Leave `specs/kb-search/` in place as the durable record.
- Update `GAPS.md`: move "Knowledge base search" from Potential additions to Closed gaps.
