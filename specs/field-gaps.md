# Field Gap Log

Audit of fields silently dropped from tool responses. Ordered by impact.

---

## P1 — High impact, blocks common workflows

### `list_ticket_fields` — missing `options` for select/multiselect fields

`list_ticket_fields` uses the zenpy `client.ticket_fields()` iterator, which returns Zenpy objects
that don't expose the `custom_field_options` array. For fields of type `tagger`, `select`, or
`multiselect`, callers have no way to know valid values without a separate raw API call.

**Fix:** Switch to raw API (`/ticket_fields.json`) and include `options` when present:
```json
{ "id": 123, "title": "Plan Tier", "type": "tagger", "options": [{"name": "Starter", "value": "starter"}] }
```

---

### `search_users` / `get_group_users` — minimal user fields returned

Both return only `id`, `name`, `email` (and `role` for `search_users`). Missing fields that are
routinely needed for ticket work:

| Field | Why it matters |
|---|---|
| `organization_id` | Link user → org without a second call |
| `role` | Missing from `get_group_users` entirely |
| `active` / `suspended` | Know if the account is usable |
| `time_zone` | Relevant for SLA and scheduling |
| `user_fields` | Custom user fields (same gap as ticket custom_fields was) |

**Fix:** Both methods hit the raw API already — add the missing fields to the returned dict.

---

### `get_tickets` — missing `organization_id` and `tags`

`get_ticket` (single) returns `organization_id` and `tags`; `get_tickets` (list) silently drops
both. Creates an inconsistency: you can't filter or group list results by org without re-fetching
each ticket individually.

**Fix:** Add `organization_id`, `tags`, and `type` to the per-ticket dict in `get_tickets`.

---

## P2 — Moderate impact, creates inconsistency or limits utility

### `get_ticket` / `update_ticket` / `create_ticket` — missing `type` and `group_id`

`type` (problem/incident/question/task) and `group_id` are standard ticket attributes present
on the Zenpy object but not returned. `due_at` is also absent, which matters for task-type tickets.

**Fix:** Add `type`, `group_id`, and `due_at` (nullable) to all three single-ticket response dicts.

---

### `apply_macro` — post-apply ticket state is partial

After applying a macro the response returns only `id`, `status`, `tags`, and `applied_changes`.
If a macro changes assignee, priority, or custom fields those changes aren't visible in the
response — callers must do a follow-up `get_ticket`.

**Fix:** Return the full ticket dict (same shape as `get_ticket`) instead of the minimal subset.

---

### `list_macros` — missing `restriction`

`restriction` specifies which agents/groups can use the macro. Without it callers can't tell
whether a macro is available to a given agent before attempting to apply it.

**Fix:** Add `restriction: getattr(m, 'restriction', None)` to the macro dict.

---

### `get_article` / `search_articles` — missing `draft`, `author_id`, `created_at`

KB article responses omit:
- `draft` — a draft article should not be surfaced to end users
- `author_id` — useful for attribution
- `created_at` — only `updated_at` is returned by `search_articles`

**Fix:** Add the three fields. Guard `draft` with `getattr(article, 'draft', False)`.

---

## P3 — Low impact / nice-to-have

### `get_group_users` — missing `role`

`search_users` returns `role`; `get_group_users` doesn't despite hitting the same `/users` shape.
Minor inconsistency but easy to fix.

### `get_groups` — missing `created_at` / `updated_at`

Both timestamps are available in the raw API response but not extracted. Low value but trivial.

### `list_views` — missing `active` flag

`list_views` returns only `id` and `title`. The `active` flag would let callers skip inactive
views without calling `get_view` for each one.

### `get_ticket_comments` — missing `via`

The `via` field (channel: email, web form, API, etc.) is on every comment object. Useful for
understanding how a comment was submitted.

---

## Not a gap

- `preview_macro` — passes through `data['result']` unchanged; complete by design.
- `get_organization` — returns `organization_fields`; already correct.
- `get_jira_links` / `get_zendesk_tickets_for_jira_issue` — returns all meaningful link fields.
- `list_custom_statuses` — returns all fields relevant for status resolution.
