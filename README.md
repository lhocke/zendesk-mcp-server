# Zendesk MCP Server

![ci](https://github.com/reminia/zendesk-mcp-server/actions/workflows/ci.yml/badge.svg)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Model Context Protocol server for Zendesk. Provides tools for retrieving and managing tickets, comments, users, and organizations, plus prompts for ticket analysis and response drafting.

![demo](https://res.cloudinary.com/leecy-me/image/upload/v1736410626/open/zendesk_yunczu.gif)

## Setup

```bash
uv venv && uv pip install -e .
```

## Authentication

The server supports two modes. OAuth is preferred — comments appear under your own Zendesk identity. API token auth is available as a simpler fallback.

**Mode selection:** if `ZENDESK_CLIENT_ID` is set, the server runs in OAuth mode and requires a valid token file (created by `zendesk-auth`). If not set, it falls back to API-token mode using `ZENDESK_EMAIL` and `ZENDESK_API_KEY`. There is no silent fallback between modes.

### OAuth (recommended)

**Admin setup (once per team):**

1. In Zendesk Admin Center, go to **Apps and Integrations → APIs → OAuth Clients**.
2. Click **Add OAuth client**. Set the redirect URI to `http://127.0.0.1:47890/callback` (Zendesk requires a byte-for-byte match). Note the `client_id` and `client_secret`.
3. Distribute `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`, and `ZENDESK_SUBDOMAIN` to your team via `.env.example`.

**Per-user setup:**

1. Copy `.env.example` to `.env` and fill in `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`, and `ZENDESK_SUBDOMAIN`.
2. Run the auth flow:

   ```bash
   uv run zendesk-auth
   ```

   Opens a browser to authorize. Token is saved to `~/.config/zendesk-mcp/{subdomain}.json`. Use `--no-browser` in headless environments, or `--port N` if 47890 is in use (register the new redirect URI in Zendesk first).

3. Verify:

   ```bash
   uv run zendesk-auth --check
   ```

4. Configure your MCP client (example for Claude Desktop / Claude Code):

   ```json
   {
     "mcpServers": {
       "zendesk": {
         "command": "uv",
         "args": ["--directory", "/path/to/zendesk-mcp-server", "run", "zendesk"]
       }
     }
   }
   ```

### API Token (fallback)

1. Generate a token in **Admin Center → Apps and Integrations → APIs → API Tokens**.
2. Copy `.env.example` to `.env` and fill in `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, and `ZENDESK_API_KEY`.
3. Configure your MCP client as above.

**Note:** each user must run their own instance with their own email — public comments are attributed to `ZENDESK_EMAIL`, so sharing a single configured instance will make all replies appear to come from the same person.

### Docker

```bash
docker build -t zendesk-mcp-server .
docker run --rm -i --env-file /path/to/.env zendesk-mcp-server
```

For OAuth, run `zendesk-auth` on the host first, then mount the token file:

```bash
docker run --rm -i \
  --env-file /path/to/.env \
  -v ~/.config/zendesk-mcp:/home/zendesk/.config/zendesk-mcp \
  zendesk-mcp-server
```

## Tools

### Tickets

| Tool | Description |
|------|-------------|
| `get_ticket` | Fetch a ticket by ID |
| `get_tickets` | List tickets with pagination and sort options |
| `search_tickets` | Search using Zendesk query syntax (e.g. `status:open assignee:me`) |
| `create_ticket` | Create a new ticket |
| `update_ticket` | Update status, priority, assignee, group, custom status, and more |
| `get_ticket_comments` | Retrieve the full comment thread for a ticket |
| `create_ticket_comment` | Post a public or internal comment (accepts HTML) |
| `get_ticket_attachment` | Fetch an attachment by content URL, returned as base64 |
| `add_tag` / `remove_tag` | Add or remove a tag on a ticket |

### Views & Macros

| Tool | Description |
|------|-------------|
| `list_views` | List all saved views |
| `get_view` | Get a view's filter conditions |
| `get_view_tickets` | Fetch tickets in a view |
| `list_macros` | List available macros |
| `preview_macro` | Preview the effect of a macro on a ticket |
| `apply_macro` | Apply a macro to a ticket |

### Users, Groups & Organizations

| Tool | Description |
|------|-------------|
| `search_users` | Find users by name or email |
| `get_groups` | List all active groups |
| `get_group_users` | List members of a group |
| `get_organization` | Fetch an organization including custom fields |
| `list_custom_statuses` | List all custom ticket statuses and their IDs |

### Jira Integration

| Tool | Description |
|------|-------------|
| `get_jira_links` | Get Jira issues linked to a Zendesk ticket |
| `get_zendesk_tickets_for_jira_issue` | Reverse lookup — Zendesk tickets for a Jira issue ID |
| `create_jira_link` | Link a Jira issue to a ticket |
| `delete_jira_link` | Remove a Jira link from a ticket |

## Prompts

- **analyze-ticket** — detailed analysis of a ticket
- **draft-ticket-response** — draft a reply to a ticket

## Resources

- `zendesk://knowledge-base` — full access to Zendesk Help Center articles
