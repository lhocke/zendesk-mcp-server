# Zendesk MCP Server

![ci](https://github.com/reminia/zendesk-mcp-server/actions/workflows/ci.yml/badge.svg)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Model Context Protocol server for Zendesk.

This server provides a comprehensive integration with Zendesk. It offers:

- Tools for retrieving and managing Zendesk tickets and comments
- Specialized prompts for ticket analysis and response drafting
- Full access to the Zendesk Help Center articles as knowledge base

![demo](https://res.cloudinary.com/leecy-me/image/upload/v1736410626/open/zendesk_yunczu.gif)

## Setup

Build the project first:

```bash
uv venv && uv pip install -e .
```

The server supports two authentication modes. OAuth is preferred — it ties comments to your individual Zendesk identity so customers see the correct agent name. API token auth is available as a simpler fallback.

### OAuth (recommended)

OAuth requires a one-time admin step to register an OAuth client, then a one-time per-user browser authorization.

**Admin setup (once per team):**

1. In Zendesk Admin Center, go to **Apps and Integrations → APIs → OAuth Clients**.
2. Click **Add OAuth client**. Set the redirect URI to `http://localhost:8085/callback`. Note the `client_id` and `client_secret`.
3. Distribute `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`, and `ZENDESK_SUBDOMAIN` to your team (e.g. via a shared `.env.example`).

**Per-user setup:**

1. Copy `.env.example` to `.env` and fill in `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`, and `ZENDESK_SUBDOMAIN`.
2. Run the auth command:

   ```bash
   uv run zendesk-auth
   ```

   This opens a browser window to authorize the OAuth client. After authorizing, your token is saved to `~/.zendesk_mcp/{subdomain}.json`. You will not need to repeat this step unless the token expires (refresh tokens last up to 90 days).

3. Verify authentication succeeded:

   ```bash
   uv run zendesk-auth --check
   ```

4. Configure Claude Desktop or Claude Code:

   ```json
   {
     "mcpServers": {
       "zendesk": {
         "command": "uv",
         "args": [
           "--directory",
           "/path/to/zendesk-mcp-server",
           "run",
           "zendesk"
         ]
       }
     }
   }
   ```

### API Token (fallback)

Use this if your team does not have an OAuth client registered, or for automated/service accounts that only post internal notes.

1. A Zendesk admin must generate an API token in **Admin Center → Apps and Integrations → APIs → API Tokens**.
2. Copy `.env.example` to `.env` and fill in `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL` (your own email address), and `ZENDESK_API_KEY`.
3. Configure Claude Desktop or Claude Code as above.

**Note:** Attribution for public comments depends on `ZENDESK_EMAIL` being set to your own email. Do not share a configured instance with other users — each person should run their own with their own email.

### Docker

You can containerize the server if you prefer an isolated runtime:

1. Build the image:

   ```bash
   docker build -t zendesk-mcp-server .
   ```

2. Create a `.env` file with your credentials (see `.env.example`). Keep this file outside version control.

3. Run the server:

   ```bash
   docker run --rm -i --env-file /path/to/.env zendesk-mcp-server
   ```

   For daemonized runs, add `-d --name zendesk-mcp`.

The image installs dependencies from `requirements.lock`, drops privileges to a non-root user, and expects configuration exclusively via environment variables.

#### Docker with OAuth

The OAuth browser flow cannot run inside a Docker container. Run `zendesk-auth` on your host machine first, then mount the token file into the container:

```bash
# Step 1: authenticate on the host (one-time, or when token expires)
uv run zendesk-auth

# Step 2: run the container with the token file mounted
docker run --rm -i \
  --env-file /path/to/.env \
  -v ~/.zendesk_mcp:/home/zendesk/.zendesk_mcp \
  zendesk-mcp-server
```

The server will silently refresh the access token as needed and write the updated token back to the mounted file. Ensure the mount is read-write (the default) so refreshed tokens are persisted across container restarts.

If you are in a headless environment without a browser, use `--no-browser` to print the authorization URL instead of opening it:

```bash
uv run zendesk-auth --no-browser
```

#### Claude MCP Integration

To use the Dockerized server from Claude Code/Desktop, add an entry to Claude Code's `settings.json`. For OAuth, include the token file mount:

```json
{
  "mcpServers": {
    "zendesk": {
      "command": "/usr/local/bin/docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/path/to/zendesk-mcp-server/.env",
        "-v",
        "/Users/yourname/.zendesk_mcp:/home/zendesk/.zendesk_mcp",
        "zendesk-mcp-server"
      ]
    }
  }
}
```

For API token auth, omit the `-v` lines.

Adjust the paths to match your environment. After saving the file, restart Claude for the new MCP server to be detected.

## Resources

- zendesk://knowledge-base, get access to the whole help center articles.

## Prompts

### analyze-ticket

Analyze a Zendesk ticket and provide a detailed analysis of the ticket.

### draft-ticket-response

Draft a response to a Zendesk ticket.

## Tools

### get_tickets

Fetch the latest tickets with pagination support

- Input:
  - `page` (integer, optional): Page number (defaults to 1)
  - `per_page` (integer, optional): Number of tickets per page, max 100 (defaults to 25)
  - `sort_by` (string, optional): Field to sort by - created_at, updated_at, priority, or status (defaults to created_at)
  - `sort_order` (string, optional): Sort order - asc or desc (defaults to desc)

- Output: Returns a list of tickets with essential fields including id, subject, status, priority, description, timestamps, and assignee information, along with pagination metadata

### get_ticket

Retrieve a Zendesk ticket by its ID

- Input:
  - `ticket_id` (integer): The ID of the ticket to retrieve

### get_ticket_comments

Retrieve all comments for a Zendesk ticket by its ID

- Input:
  - `ticket_id` (integer): The ID of the ticket to get comments for

### create_ticket_comment

Create a new comment on an existing Zendesk ticket

- Input:
  - `ticket_id` (integer): The ID of the ticket to comment on
  - `comment` (string): The comment content as HTML (not plain text or markdown). Use HTML tags like `<p>`, `<strong>`, `<code>`, `<ol>`, `<li>` for formatting.
  - `public` (boolean, optional): Whether the comment should be public (defaults to true)

**Note:** Comments are sent as `html_body` to Zendesk. Plain text without HTML tags will render as a single unformatted block.

### create_ticket

Create a new Zendesk ticket

- Input:
  - `subject` (string): Ticket subject
  - `description` (string): Ticket description
  - `requester_id` (integer, optional)
  - `assignee_id` (integer, optional)
  - `priority` (string, optional): one of `low`, `normal`, `high`, `urgent`
  - `type` (string, optional): one of `problem`, `incident`, `question`, `task`
  - `tags` (array[string], optional)
  - `custom_fields` (array[object], optional)

### update_ticket

Update fields on an existing Zendesk ticket (e.g., status, priority, assignee)

- Input:
  - `ticket_id` (integer): The ID of the ticket to update
  - `subject` (string, optional)
  - `status` (string, optional): one of `new`, `open`, `pending`, `on-hold`, `solved`, `closed`
  - `priority` (string, optional): one of `low`, `normal`, `high`, `urgent`
  - `type` (string, optional)
  - `assignee_id` (integer or null, optional): Assignee ID, or pass `null` to unassign the ticket
  - `requester_id` (integer, optional)
  - `tags` (array[string], optional)
  - `custom_fields` (array[object], optional)
  - `due_at` (string, optional): ISO8601 datetime
  - `custom_status_id` (integer, optional): Custom ticket status ID (for non-standard statuses beyond the built-in `status` enum)
  - `group_id` (integer, optional): Zendesk group ID to assign the ticket to

### search_tickets

Search Zendesk tickets using a query string with support for filtering by assignee, status, priority, organization, and date.

- Input:
  - `query` (string): Zendesk search query, e.g. `type:ticket status:open assignee:me`
  - `sort_by` (string, optional): Field to sort by — `created_at`, `updated_at`, `priority`, or `status` (defaults to `created_at`)
  - `sort_order` (string, optional): `asc` or `desc` (defaults to `asc`)
  - `per_page` (integer, optional): Results per page, max 100 (defaults to 10)

- Output: Returns matching tickets with id, subject, status, priority, timestamps, assignee_id, and organization_id, along with total count and pagination info.

### get_organization

Retrieve a Zendesk organization by ID, including custom fields.

- Input:
  - `organization_id` (integer): The ID of the organization to retrieve

- Output: Returns id, name, organization_fields (full dict of custom fields), tags, and timestamps.

### search_users

Search for Zendesk users by name or email.

- Input:
  - `query` (string): Name or email to search for

- Output: Returns a list of matching users with id, name, and email.

### get_group_users

List all users in a Zendesk group.

- Input:
  - `group_id` (integer): The ID of the group

- Output: Returns a list of group members with id, name, and email.

### get_groups

List all active Zendesk groups (support teams).

- Input: None

- Output: Returns a list of groups with id and name.

### list_custom_statuses

List all custom ticket statuses defined in Zendesk, including their IDs and status categories.

- Input: None

- Output: Returns a list of custom statuses with id, agent_label, end_user_label, status_category, active, and default flag.

### get_jira_links

Get all Jira issues linked to a Zendesk ticket via the Jira integration.

- Input:
  - `ticket_id` (integer): The Zendesk ticket ID to look up linked Jira issues for

- Output: Returns a list of Jira links with `id`, `ticket_id`, `issue_id`, `issue_key` (e.g. `ENG-123`), `url`, `created_at`, and `updated_at`.

### get_zendesk_tickets_for_jira_issue

Get all Zendesk tickets linked to a given Jira issue — the reverse lookup of `get_jira_links`.

- Input:
  - `issue_id` (string): The numeric Jira issue ID (e.g. `'60747'`) to look up linked Zendesk tickets for

- Output: Same shape as `get_jira_links` — each entry includes `ticket_id`, `issue_key`, and timestamps.

### get_ticket_attachment

Fetch a Zendesk ticket attachment by its content URL and return the file as base64-encoded data.

- Input:
  - `content_url` (string): The `content_url` of the attachment from `get_ticket_comments`

- Output: Returns base64-encoded file data and content type. Images are returned as image content; other file types as JSON with a `data_base64` field. Supports JPEG, PNG, GIF, and WebP only (max 10 MB).

## Limitations

### Comment Attribution (API token mode only)

When using API token auth, public comments are attributed to whichever email address is set in `ZENDESK_EMAIL`. Zendesk API tokens are account-level — any token can be paired with any account member's email — so attribution is determined entirely by how the server is configured, not by the token itself.

**Do not share a single configured instance across multiple people.** Each user should run their own instance with their own email, otherwise all public replies appear to come from the same person.

OAuth mode does not have this limitation — tokens are tied to the authorizing user's Zendesk identity at the platform level.
