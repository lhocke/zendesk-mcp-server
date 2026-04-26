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

- build: `uv venv && uv pip install -e .` or `uv build` in short.
- setup zendesk credentials in `.env` file, refer to [.env.example](.env.example).
- configure in Claude desktop:

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

### Docker

You can containerize the server if you prefer an isolated runtime:

1. Copy `.env.example` to `.env` and fill in your Zendesk credentials. Keep this file outside version control.
2. Build the image:

   ```bash
   docker build -t zendesk-mcp-server .
   ```

3. Run the server, providing the environment file:

   ```bash
   docker run --rm --env-file /path/to/.env zendesk-mcp-server
   ```

   Add `-i` when wiring the container to MCP clients over STDIN/STDOUT (Claude Code uses this mode). For daemonized runs, add `-d --name zendesk-mcp`.

The image installs dependencies from `requirements.lock`, drops privileges to a non-root user, and expects configuration exclusively via environment variables.

#### Claude MCP Integration

To use the Dockerized server from Claude Code/Desktop, add an entry to Claude Code's `settings.json` similar to:

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
        "zendesk-mcp-server"
      ]
    }
  }
}
```

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
