# Zendesk MCP — Capability Gaps

Fork: `github.com/lhocke/zendesk-mcp-server`. Dev repo at `~/zendesk-mcp-server`.

## Potential additions (skills project benefit)

| Tool | Value | Notes |
|------|-------|-------|
| **`get_ticket_metrics`** | SLA breach details per ticket — breach timestamps, reply/resolution/wait times, next breach window | zenpy already has `TicketMetric`, `TicketMetricEvent`, `TicketMetricItem` in `api_objects/__init__.py` and `client.ticket_metrics(ticket_id)` in `api.py:127`. Pair with `search_tickets(sla_breach:true)` to get the breach list then call this for per-ticket detail. No urllib needed — pure zenpy. See implementation notes below. |
| **`list_triggers`** | Exposes event-driven rules (conditions + actions) as a structured spec for skill authoring | Same conditions/actions shape as macros; zenpy: `client.triggers` |
| **`list_automations`** | Exposes time-based rules (conditions + actions) for the same purpose | zenpy: `client.automations` |

### `get_ticket_metrics` — implementation notes

**`zendesk_client.py`** — add method:
```python
def get_ticket_metrics(self, ticket_id: int) -> dict:
    metrics = self.zenpy_client.ticket_metrics(ticket_id)
    return {
        "ticket_id": ticket_id,
        "reply_time_in_minutes": metrics.reply_time_in_minutes,
        "first_resolution_time_in_minutes": metrics.first_resolution_time_in_minutes,
        "full_resolution_time_in_minutes": metrics.full_resolution_time_in_minutes,
        "requester_wait_time_in_minutes": metrics.requester_wait_time_in_minutes,
        "breach_at": str(metrics.breach_at) if metrics.breach_at else None,
        "next_breach_at": str(metrics.next_breach_at) if metrics.next_breach_at else None,
    }
```

**`server.py`** — register as a new tool following the same shape as `get_ticket`. Input: `ticket_id: int`. Output: the dict above.

**SLA breach list workflow:**
1. `search_tickets(query="sla_breach:true status:open assignee:me")` — get the breach list (test this first; the filter may already work through existing search passthrough)
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
