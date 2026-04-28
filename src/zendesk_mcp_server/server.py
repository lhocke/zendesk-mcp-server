import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Dict

from cachetools.func import ttl_cache
from dotenv import load_dotenv
import mcp.types as types
from mcp.server import InitializationOptions, NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from zendesk_mcp_server.zendesk_client import build_zendesk_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("zendesk-mcp-server")
logger.info("zendesk mcp server started")

load_dotenv()
zendesk_client = build_zendesk_client()

server = Server("Zendesk Server")

# HTTP transport (Streamable HTTP via Starlette + uvicorn)
_session_manager = StreamableHTTPSessionManager(app=server, stateless=False)


async def _handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
    await _session_manager.handle_request(scope, receive, send)


@contextlib.asynccontextmanager
async def _lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
    async with _session_manager.run():
        yield


app = Starlette(
    routes=[Mount("/mcp", app=_handle_streamable_http)],
    lifespan=_lifespan,
)

TICKET_ANALYSIS_TEMPLATE = """
You are a helpful Zendesk support analyst. You've been asked to analyze ticket #{ticket_id}.

Please fetch the ticket info and comments to analyze it and provide:
1. A summary of the issue
2. The current status and timeline
3. Key points of interaction

Remember to be professional and focus on actionable insights.
"""

COMMENT_DRAFT_TEMPLATE = """
You are a helpful Zendesk support agent. You need to draft a response to ticket #{ticket_id}.

Please fetch the ticket info, comments and knowledge base to draft a professional and helpful response that:
1. Acknowledges the customer's concern
2. Addresses the specific issues raised
3. Provides clear next steps or ask for specific details need to proceed
4. Maintains a friendly and professional tone
5. Ask for confirmation before commenting on the ticket

The response should be formatted well and ready to be posted as a comment.
"""


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts"""
    return [
        types.Prompt(
            name="analyze-ticket",
            description="Analyze a Zendesk ticket and provide insights",
            arguments=[
                types.PromptArgument(
                    name="ticket_id",
                    description="The ID of the ticket to analyze",
                    required=True,
                )
            ],
        ),
        types.Prompt(
            name="draft-ticket-response",
            description="Draft a professional response to a Zendesk ticket",
            arguments=[
                types.PromptArgument(
                    name="ticket_id",
                    description="The ID of the ticket to respond to",
                    required=True,
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Dict[str, str] | None) -> types.GetPromptResult:
    """Handle prompt requests"""
    if not arguments or "ticket_id" not in arguments:
        raise ValueError("Missing required argument: ticket_id")

    ticket_id = int(arguments["ticket_id"])
    try:
        if name == "analyze-ticket":
            prompt = TICKET_ANALYSIS_TEMPLATE.format(
                ticket_id=ticket_id
            )
            description = f"Analysis prompt for ticket #{ticket_id}"

        elif name == "draft-ticket-response":
            prompt = COMMENT_DRAFT_TEMPLATE.format(
                ticket_id=ticket_id
            )
            description = f"Response draft prompt for ticket #{ticket_id}"

        else:
            raise ValueError(f"Unknown prompt: {name}")

        return types.GetPromptResult(
            description=description,
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt.strip()),
                )
            ],
        )

    except Exception as e:
        logger.error(f"Error generating prompt: {e}")
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available Zendesk tools"""
    return [
        types.Tool(
            name="get_ticket",
            description="Retrieve a Zendesk ticket by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": ["integer", "string"],
                        "description": "The ID of the ticket to retrieve"
                    }
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="create_ticket",
            description="Create a new Zendesk ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Ticket subject"},
                    "description": {"type": "string", "description": "Ticket description"},
                    "requester_id": {"type": ["integer", "string"]},
                    "assignee_id": {"type": ["integer", "string"]},
                    "priority": {"type": "string", "description": "low, normal, high, urgent"},
                    "type": {"type": "string", "description": "problem, incident, question, task"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "custom_fields": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["subject", "description"],
            }
        ),
        types.Tool(
            name="get_tickets",
            description="Fetch the latest tickets with pagination support",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": ["integer", "string"],
                        "description": "Page number",
                        "default": 1
                    },
                    "per_page": {
                        "type": ["integer", "string"],
                        "description": "Number of tickets per page (max 100)",
                        "default": 25
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Field to sort by (created_at, updated_at, priority, status)",
                        "default": "created_at"
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "Sort order (asc or desc)",
                        "default": "desc"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_ticket_comments",
            description="Retrieve all comments for a Zendesk ticket by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": ["integer", "string"],
                        "description": "The ID of the ticket to get comments for"
                    }
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="create_ticket_comment",
            description="Create a new comment on an existing Zendesk ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": ["integer", "string"],
                        "description": "The ID of the ticket to comment on"
                    },
                    "comment": {
                        "type": "string",
                        "description": "The comment text/content to add"
                    },
                    "public": {
                        "type": "boolean",
                        "description": "Whether the comment should be public",
                        "default": True
                    },
                    "uploads": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Upload tokens from POST /api/v2/uploads.json to attach files to the comment"
                    }
                },
                "required": ["ticket_id", "comment"]
            }
        ),
        types.Tool(
            name="get_ticket_attachment",
            description="Fetch a Zendesk ticket attachment by its content_url and return the file as base64-encoded data. Use the attachment URLs returned by get_ticket_comments.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_url": {
                        "type": "string",
                        "description": "The content_url of the attachment from get_ticket_comments"
                    }
                },
                "required": ["content_url"]
            }
        ),
        types.Tool(
            name="search_tickets",
            description="Search Zendesk tickets using a query string (supports assignee, status, priority, org, date filters)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Zendesk search query, e.g. 'type:ticket status:open assignee:me'"},
                    "sort_by": {"type": "string", "description": "Field to sort by (created_at, updated_at, priority, status)", "default": "created_at"},
                    "sort_order": {"type": "string", "description": "asc or desc", "default": "asc"},
                    "per_page": {"type": ["integer", "string"], "description": "Results per page (max 100)", "default": 10}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="get_organization",
            description="Retrieve a Zendesk organization by ID, including custom fields",
            inputSchema={
                "type": "object",
                "properties": {
                    "organization_id": {"type": ["integer", "string"], "description": "The ID of the organization to retrieve"}
                },
                "required": ["organization_id"]
            }
        ),
        types.Tool(
            name="search_users",
            description="Search for Zendesk users by name or email",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name or email to search for"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="get_group_users",
            description="List all users in a Zendesk group",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": ["integer", "string"], "description": "The ID of the group"}
                },
                "required": ["group_id"]
            }
        ),
        types.Tool(
            name="get_groups",
            description="List all active Zendesk groups (support teams)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="list_custom_statuses",
            description="List all custom ticket statuses defined in Zendesk, including their IDs and status categories (new, open, pending, hold, solved)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="get_jira_links",
            description="Get all Jira issues linked to a Zendesk ticket via the Jira integration",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": ["integer", "string"],
                        "description": "The Zendesk ticket ID to look up linked Jira issues for"
                    }
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="get_zendesk_tickets_for_jira_issue",
            description="Get all Zendesk tickets linked to a given Jira issue ID via the Jira integration",
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "The Jira issue ID (numeric, e.g. '60747') to look up linked Zendesk tickets for"
                    }
                },
                "required": ["issue_id"]
            }
        ),
        types.Tool(
            name="list_ticket_fields",
            description="List all active Zendesk ticket fields, including custom fields with their IDs and types",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="list_macros",
            description="List all active Zendesk macros with their actions, for use with apply_macro",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="preview_macro",
            description="Return the field changes and comment a macro would make, without applying anything. Useful for understanding what a macro does before calling apply_macro.",
            inputSchema={
                "type": "object",
                "properties": {
                    "macro_id": {"type": ["integer", "string"], "description": "The ID of the macro to preview (obtain via list_macros)"},
                },
                "required": ["macro_id"]
            }
        ),
        types.Tool(
            name="apply_macro",
            description="Apply a macro to a Zendesk ticket — updates ticket fields and posts any comment the macro defines",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": ["integer", "string"], "description": "The ticket to apply the macro to"},
                    "macro_id": {"type": ["integer", "string"], "description": "The ID of the macro to apply (obtain via list_macros)"},
                },
                "required": ["ticket_id", "macro_id"]
            }
        ),
        types.Tool(
            name="list_views",
            description="List all active Zendesk views (saved ticket queues) with their IDs and titles",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_view",
            description="Return the full definition of a Zendesk view including its filter conditions, for understanding what a view captures without executing it",
            inputSchema={
                "type": "object",
                "properties": {
                    "view_id": {"type": ["integer", "string"], "description": "The ID of the view (obtain via list_views)"},
                },
                "required": ["view_id"]
            }
        ),
        types.Tool(
            name="get_view_tickets",
            description="Return the tickets in a Zendesk view",
            inputSchema={
                "type": "object",
                "properties": {
                    "view_id": {"type": ["integer", "string"], "description": "The ID of the view (obtain via list_views)"},
                },
                "required": ["view_id"]
            }
        ),
        types.Tool(
            name="add_tag",
            description="Add a single tag to a Zendesk ticket without overwriting existing tags",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": ["integer", "string"], "description": "The ID of the ticket"},
                    "tag": {"type": "string", "description": "The tag to add"},
                },
                "required": ["ticket_id", "tag"]
            }
        ),
        types.Tool(
            name="remove_tag",
            description="Remove a single tag from a Zendesk ticket without affecting other tags",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": ["integer", "string"], "description": "The ID of the ticket"},
                    "tag": {"type": "string", "description": "The tag to remove"},
                },
                "required": ["ticket_id", "tag"]
            }
        ),
        types.Tool(
            name="create_jira_link",
            description="Link a Zendesk ticket to a Jira issue",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": ["integer", "string"], "description": "The Zendesk ticket ID"},
                    "issue_key": {"type": "string", "description": "The Jira issue key, e.g. ENG-123"},
                    "issue_id": {"type": ["integer", "string"], "description": "The numeric Jira issue ID (required by Zendesk's API — obtain via get_jira_links or Jira)"},
                },
                "required": ["ticket_id", "issue_key", "issue_id"]
            }
        ),
        types.Tool(
            name="delete_jira_link",
            description="Remove a Zendesk–Jira link by its link ID (obtain via get_jira_links)",
            inputSchema={
                "type": "object",
                "properties": {
                    "link_id": {"type": ["integer", "string"], "description": "The ID of the Jira link to delete"},
                },
                "required": ["link_id"]
            }
        ),
        types.Tool(
            name="search_articles",
            description="Search Help Center articles by keyword. Returns a list of hits with id, title, snippet, url, section, category, and labels. Use get_article to fetch the full body of a specific article.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "limit": {"type": ["integer", "string"], "description": "Max results (default 10, max 25)"},
                    "label_names": {"type": "array", "items": {"type": "string"}, "description": "Filter to articles with any of these labels"},
                    "section_id": {"type": ["integer", "string"], "description": "Restrict to a specific section"},
                    "category_id": {"type": ["integer", "string"], "description": "Restrict to a specific category"},
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="get_article",
            description="Fetch a single Help Center article by ID, including its full HTML body",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {"type": ["integer", "string"], "description": "The article ID"},
                },
                "required": ["article_id"]
            }
        ),
        types.Tool(
            name="list_sections",
            description="List all Help Center sections with their parent category",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="update_ticket",
            description="Update fields on an existing Zendesk ticket (e.g., status, priority, assignee_id)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": ["integer", "string"], "description": "The ID of the ticket to update"},
                    "subject": {"type": "string"},
                    "status": {"type": "string", "description": "new, open, pending, on-hold, solved, closed"},
                    "priority": {"type": "string", "description": "low, normal, high, urgent"},
                    "type": {"type": "string"},
                    "assignee_id": {"type": ["integer", "string", "null"], "description": "Assignee ID or null to unassign"},
                    "requester_id": {"type": ["integer", "string"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "custom_fields": {"type": "array", "items": {"type": "object"}},
                    "due_at": {"type": "string", "description": "ISO8601 datetime"},
                    "custom_status_id": {"type": ["integer", "string"], "description": "Custom ticket status ID (e.g. Feature Request Created, On-Hold/Engineering)"},
                    "group_id": {"type": ["integer", "string"], "description": "Zendesk group ID to assign the ticket to"}
                },
                "required": ["ticket_id"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(
        name: str,
        arguments: dict[str, Any] | None
) -> list[types.TextContent]:
    """Handle Zendesk tool execution requests"""
    try:
        if name == "get_ticket":
            if not arguments:
                raise ValueError("Missing arguments")
            ticket = zendesk_client.get_ticket(int(arguments["ticket_id"]))
            return [types.TextContent(
                type="text",
                text=json.dumps(ticket)
            )]

        elif name == "create_ticket":
            if not arguments:
                raise ValueError("Missing arguments")
            created = zendesk_client.create_ticket(
                subject=arguments.get("subject"),
                description=arguments.get("description"),
                requester_id=arguments.get("requester_id"),
                assignee_id=arguments.get("assignee_id"),
                priority=arguments.get("priority"),
                type=arguments.get("type"),
                tags=arguments.get("tags"),
                custom_fields=arguments.get("custom_fields"),
            )
            return [types.TextContent(
                type="text",
                text=json.dumps({"message": "Ticket created successfully", "ticket": created}, indent=2)
            )]

        elif name == "get_tickets":
            page = arguments.get("page", 1) if arguments else 1
            per_page = arguments.get("per_page", 25) if arguments else 25
            sort_by = arguments.get("sort_by", "created_at") if arguments else "created_at"
            sort_order = arguments.get("sort_order", "desc") if arguments else "desc"

            tickets = zendesk_client.get_tickets(
                page=page,
                per_page=per_page,
                sort_by=sort_by,
                sort_order=sort_order
            )
            return [types.TextContent(
                type="text",
                text=json.dumps(tickets, indent=2)
            )]

        elif name == "get_ticket_comments":
            if not arguments:
                raise ValueError("Missing arguments")
            comments = zendesk_client.get_ticket_comments(
                int(arguments["ticket_id"]))
            return [types.TextContent(
                type="text",
                text=json.dumps(comments)
            )]

        elif name == "create_ticket_comment":
            if not arguments:
                raise ValueError("Missing arguments")
            public = arguments.get("public", True)
            result = zendesk_client.post_comment(
                ticket_id=int(arguments["ticket_id"]),
                comment=arguments["comment"],
                public=public,
                uploads=arguments.get("uploads"),
            )
            return [types.TextContent(
                type="text",
                text=f"Comment created successfully: {result}"
            )]

        elif name == "get_ticket_attachment":
            if not arguments:
                raise ValueError("Missing arguments")
            result = zendesk_client.get_ticket_attachment(arguments["content_url"])
            content_type = result["content_type"]
            if content_type.startswith("image/"):
                return [types.ImageContent(
                    type="image",
                    data=result["data"],
                    mimeType=content_type,
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"content_type": content_type, "data_base64": result["data"]})
                )]

        elif name == "search_tickets":
            if not arguments:
                raise ValueError("Missing arguments")
            results = zendesk_client.search_tickets(
                query=arguments["query"],
                sort_by=arguments.get("sort_by", "created_at"),
                sort_order=arguments.get("sort_order", "asc"),
                per_page=arguments.get("per_page", 10)
            )
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_organization":
            if not arguments:
                raise ValueError("Missing arguments")
            org = zendesk_client.get_organization(int(arguments["organization_id"]))
            return [types.TextContent(type="text", text=json.dumps(org, indent=2))]

        elif name == "search_users":
            if not arguments:
                raise ValueError("Missing arguments")
            users = zendesk_client.search_users(arguments["query"])
            return [types.TextContent(type="text", text=json.dumps(users, indent=2))]

        elif name == "get_group_users":
            if not arguments:
                raise ValueError("Missing arguments")
            users = zendesk_client.get_group_users(int(arguments["group_id"]))
            return [types.TextContent(type="text", text=json.dumps(users, indent=2))]

        elif name == "get_groups":
            groups = zendesk_client.get_groups()
            return [types.TextContent(type="text", text=json.dumps(groups, indent=2))]

        elif name == "list_custom_statuses":
            statuses = zendesk_client.list_custom_statuses()
            return [types.TextContent(type="text", text=json.dumps(statuses, indent=2))]

        elif name == "get_jira_links":
            if not arguments:
                raise ValueError("Missing arguments")
            links = zendesk_client.get_jira_links(int(arguments["ticket_id"]))
            return [types.TextContent(type="text", text=json.dumps(links, indent=2))]

        elif name == "get_zendesk_tickets_for_jira_issue":
            if not arguments:
                raise ValueError("Missing arguments")
            links = zendesk_client.get_zendesk_tickets_for_jira_issue(str(arguments["issue_id"]))
            return [types.TextContent(type="text", text=json.dumps(links, indent=2))]

        elif name == "list_ticket_fields":
            fields = zendesk_client.list_ticket_fields()
            return [types.TextContent(type="text", text=json.dumps(fields, indent=2))]

        elif name == "list_macros":
            macros = zendesk_client.list_macros()
            return [types.TextContent(type="text", text=json.dumps(macros, indent=2))]

        elif name == "preview_macro":
            if not arguments:
                raise ValueError("Missing arguments")
            result = zendesk_client.preview_macro(int(arguments["macro_id"]))
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "apply_macro":
            if not arguments:
                raise ValueError("Missing arguments")
            result = zendesk_client.apply_macro(int(arguments["ticket_id"]), int(arguments["macro_id"]))
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "list_views":
            views = zendesk_client.list_views()
            return [types.TextContent(type="text", text=json.dumps(views, indent=2))]

        elif name == "get_view":
            if not arguments:
                raise ValueError("Missing arguments")
            view = zendesk_client.get_view(int(arguments["view_id"]))
            return [types.TextContent(type="text", text=json.dumps(view, indent=2))]

        elif name == "get_view_tickets":
            if not arguments:
                raise ValueError("Missing arguments")
            tickets = zendesk_client.get_view_tickets(int(arguments["view_id"]))
            return [types.TextContent(type="text", text=json.dumps(tickets, indent=2))]

        elif name == "add_tag":
            if not arguments:
                raise ValueError("Missing arguments")
            tags = zendesk_client.add_tag(int(arguments["ticket_id"]), str(arguments["tag"]))
            return [types.TextContent(type="text", text=json.dumps({"tags": tags}, indent=2))]

        elif name == "remove_tag":
            if not arguments:
                raise ValueError("Missing arguments")
            tags = zendesk_client.remove_tag(int(arguments["ticket_id"]), str(arguments["tag"]))
            return [types.TextContent(type="text", text=json.dumps({"tags": tags}, indent=2))]

        elif name == "create_jira_link":
            if not arguments:
                raise ValueError("Missing arguments")
            link = zendesk_client.create_jira_link(int(arguments["ticket_id"]), str(arguments["issue_key"]), str(arguments["issue_id"]))
            return [types.TextContent(type="text", text=json.dumps(link, indent=2))]

        elif name == "delete_jira_link":
            if not arguments:
                raise ValueError("Missing arguments")
            zendesk_client.delete_jira_link(int(arguments["link_id"]))
            return [types.TextContent(type="text", text=json.dumps({"message": f"Jira link {arguments['link_id']} deleted"}))]

        elif name == "search_articles":
            if not arguments:
                raise ValueError("Missing arguments")
            results = zendesk_client.search_articles(
                query=str(arguments["query"]),
                limit=int(arguments.get("limit", 10)),
                label_names=arguments.get("label_names"),
                section_id=int(arguments["section_id"]) if arguments.get("section_id") is not None else None,
                category_id=int(arguments["category_id"]) if arguments.get("category_id") is not None else None,
            )
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_article":
            if not arguments:
                raise ValueError("Missing arguments")
            article = zendesk_client.get_article(int(arguments["article_id"]))
            return [types.TextContent(type="text", text=json.dumps(article, indent=2))]

        elif name == "list_sections":
            sections = zendesk_client.list_sections()
            return [types.TextContent(type="text", text=json.dumps(sections, indent=2))]

        elif name == "update_ticket":
            if not arguments:
                raise ValueError("Missing arguments")
            ticket_id = arguments.get("ticket_id")
            if ticket_id is None:
                raise ValueError("ticket_id is required")
            update_fields = {k: v for k, v in arguments.items() if k != "ticket_id"}
            updated = zendesk_client.update_ticket(ticket_id=int(ticket_id), **update_fields)
            return [types.TextContent(
                type="text",
                text=json.dumps({"message": "Ticket updated successfully", "ticket": updated}, indent=2)
            )]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    logger.debug("Handling list_resources request")
    return [
        types.Resource(
            uri=AnyUrl("zendesk://knowledge-base"),
            name="Zendesk Knowledge Base",
            description="Access to Zendesk Help Center articles and sections",
            mimeType="application/json",
        )
    ]


@ttl_cache(ttl=3600)
def get_cached_kb():
    return zendesk_client.get_all_articles()


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    logger.debug(f"Handling read_resource request for URI: {uri}")
    if uri.scheme != "zendesk":
        logger.error(f"Unsupported URI scheme: {uri.scheme}")
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    path = str(uri).replace("zendesk://", "")
    if path != "knowledge-base":
        logger.error(f"Unknown resource path: {path}")
        raise ValueError(f"Unknown resource path: {path}")

    try:
        kb_data = get_cached_kb()
        return json.dumps({
            "knowledge_base": kb_data,
            "metadata": {
                "sections": len(kb_data),
                "total_articles": sum(len(section['articles']) for section in kb_data.values()),
            }
        }, indent=2)
    except Exception as e:
        logger.error(f"Error fetching knowledge base: {e}")
        raise


async def main():
    transport = os.getenv("ZENDESK_MCP_TRANSPORT", "stdio")
    port = int(os.getenv("ZENDESK_MCP_PORT", "8000"))

    if transport == "http":
        import uvicorn
        logger.info(f"Starting HTTP transport on 127.0.0.1:{port}")
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
        server_instance = uvicorn.Server(config)
        await server_instance.serve()
    else:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream=read_stream,
                write_stream=write_stream,
                initialization_options=InitializationOptions(
                    server_name="Zendesk",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )


if __name__ == "__main__":
    asyncio.run(main())
