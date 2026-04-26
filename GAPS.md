# Zendesk MCP — Capability Gaps

Fork: `github.com/lhocke/zendesk-mcp-server`. Dev repo at `~/zendesk-mcp-server`.

## Open gaps (require extension)

| Gap | Workaround today | Notes |
|-----|-----------------|-------|
| **Comment redaction** | `curl PUT /api/v2/tickets/{id}/comments/{comment_id}/redact.json` | No MCP tool; Zendesk doesn't support comment deletion — only body redaction |

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
