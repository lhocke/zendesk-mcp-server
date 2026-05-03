# Zendesk MCP — Capability Gaps

Fork: `github.com/lhocke/zendesk-mcp-server`. Dev repo at `~/zendesk-mcp-server`.

## Potential additions (skills project benefit)

_None currently. See ISSUES.md for the active backlog of field gaps and smaller bugs._

**SLA breach list workflow** (now wired up):
1. `search_tickets(query="sla_breach:true status:open assignee:me")` — get the breach list (verify the `sla_breach` filter on the work machine; it's a passthrough to Zendesk search)
2. `get_ticket_metrics(ticket_id)` — per-ticket breach detail (timestamps, time windows)

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
| **SLA breach detail** | `get_ticket_metrics` tool added — pair with `search_tickets(sla_breach:true)` | Done |
| **Trigger / automation introspection** | `list_triggers` and `list_automations` tools added | Done |
