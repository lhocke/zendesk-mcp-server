# Issues

Gaps and bugs surfaced during testing. Add entries as found; close them when fixed.

Format: `- [ ]` open · `- [x]` fixed (include commit)

---

## Bugs

- [x] `get_ticket` / `create_ticket` / `update_ticket` / `get_view_tickets` — custom_fields serialization threw `ProxyDict` attribute error; Zenpy returns dict-like objects, not attribute-accessible ones. Fixed with `_serialize_custom_fields()` helper. (b3bbb12)
- [x] `create_ticket_comment` / `update_ticket` — MCP schema enforces `integer` type on `ticket_id` but rejects valid numeric values with `'NNNNN' is not of type 'integer'`; curl fallback required. Fixed by widening all integer ID schemas to `["integer", "string"]` and adding `int()` coercion in handlers missing it. (next commit)

---

## Field gaps (from audit — see specs/field-gaps.md for full detail)

### P1

- [ ] `list_ticket_fields` — `options` array missing for `select`/`multiselect`/`tagger` field types; callers can't enumerate valid values
- [ ] `search_users` / `get_group_users` — only 3–4 fields returned; missing `organization_id`, `active`, `role` (group_users), `user_fields`
- [ ] `get_tickets` — missing `organization_id` and `tags` (inconsistent with `get_ticket`)

### P2

- [ ] `get_ticket` / `create_ticket` / `update_ticket` — missing `type`, `group_id`, `due_at`
- [ ] `apply_macro` — response returns only `status`/`tags` after apply; full ticket state not visible
- [ ] `list_macros` — missing `restriction` field (which agents/groups can use the macro)
- [ ] `get_article` / `search_articles` — missing `draft`, `author_id`; `created_at` absent from search results

### P3

- [ ] `get_group_users` — missing `role` (returned by `search_users` but not here)
- [ ] `list_views` — only `id` and `title` returned; missing `active` flag
- [ ] `get_ticket_comments` — missing `via` (channel: email, web form, API, etc.)
- [ ] `get_groups` — missing `created_at` / `updated_at`
