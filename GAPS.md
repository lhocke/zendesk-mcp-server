# Zendesk MCP — Capability Gaps

Fork: `github.com/lhocke/zendesk-mcp-server`. Dev repo at `~/zendesk-mcp-server`.

## Potential additions (skills project benefit)

| Tool | Value | Notes |
|------|-------|-------|
| **`list_triggers`** | Exposes event-driven rules (conditions + actions) as a structured spec for skill authoring | Same conditions/actions shape as macros; zenpy: `client.triggers` |
| **`list_automations`** | Exposes time-based rules (conditions + actions) for the same purpose | zenpy: `client.automations` |

## Out of scope (use Zendesk UI)

| Item | Rationale |
|------|-----------|
| **Comment redaction** | Destructive admin-only operation, low frequency. Zendesk admin UI is the right path. `PUT /api/v2/tickets/{id}/comments/{comment_id}/redact.json` remains available for one-off curl when the UI is unavailable. |

## Closed gaps

| Gap | Fix | Status |
|-----|-----|--------|
| No `custom_status_id` | Added to `update_ticket` schema | Done |
| No `group_id` | Added to `update_ticket` schema | Done |
| No `html_body` on comments | `create_ticket_comment` passes as `html_body` | Done |
| No filtered search | `search_tickets` tool added | Done |
| No org lookup | `get_organization` tool added | Done |
| No user search | `search_users` tool added | Done |
| No group membership | `get_group_users` tool added | Done |
| No Jira link lookup (ticket→Jira) | `get_jira_links` tool added | Done |
| No Jira link reverse lookup (Jira→ticket) | `get_zendesk_tickets_for_jira_issue` tool added | Done |
| **Unassign ticket** (`assignee_id: null`) | `assignee_id` now typed as `["integer", "null"]` in `update_ticket` schema | Done |
| **List custom statuses** | `list_custom_statuses` tool added | Done |
| **`get_ticket` tags field** | Added `tags` to `get_ticket` response | Done |
| **Add tag non-destructively** | `add_tag` and `remove_tag` tools added (fetch-merge-write internally) | Done |
| **Create Jira link** | `create_jira_link` tool added | Done |
| **Delete Jira link** | `delete_jira_link` tool added | Done |
| **Knowledge base search** | `search_articles`, `get_article`, `list_sections` tools added | Done |
