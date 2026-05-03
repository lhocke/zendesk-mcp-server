from typing import Dict, Any, List
import json
import logging
import os
import urllib.request
import urllib.parse
import base64
import requests as _requests

logger = logging.getLogger(__name__)

from zenpy import Zenpy
from zenpy.lib.api_objects import Comment
from zenpy.lib.api_objects import Link
from zenpy.lib.api_objects import Ticket as ZenpyTicket

from html.parser import HTMLParser

from zendesk_mcp_server.oauth import OAuthTokenManager, retry_on_401


def _make_snippet(html: str, max_chars: int = 200) -> str:
    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: List[str] = []
        def handle_data(self, data: str):
            self.parts.append(data)

    stripper = _Stripper()
    stripper.feed(html)
    text = ' '.join(stripper.parts).split()
    text = ' '.join(text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    boundary = truncated.rfind(' ')
    return (truncated[:boundary] if boundary > 0 else truncated) + '...'


def _serialize_custom_fields(fields) -> list:
    """Normalize Zenpy custom_fields — handles both ProxyDict and attribute-based objects."""
    result = []
    for f in (fields or []):
        if hasattr(f, 'get'):
            result.append({'id': f.get('id'), 'value': f.get('value')})
        else:
            result.append({'id': getattr(f, 'id', None), 'value': getattr(f, 'value', None)})
    return result


class ZendeskClient:
    """Zendesk API client supporting two auth modes (API token and OAuth).

    Construct via the factory classmethods only. Direct __init__ raises TypeError.

    Methods carrying a non-idempotent side effect are NOT decorated with
    @retry_on_401 — a retry would replay the side effect:
      - post_comment       (duplicate comment)
      - apply_macro        (replays macro actions: comments, tag changes, etc.)
      - create_jira_link   (duplicate link)
    """

    def __init__(self, *args, **kwargs):
        raise TypeError(
            "ZendeskClient must be constructed via ZendeskClient.from_api_token(...) "
            "or ZendeskClient.from_oauth(...). Direct construction is not supported."
        )

    @classmethod
    def from_api_token(cls, subdomain: str, email: str, token: str) -> "ZendeskClient":
        inst = cls.__new__(cls)
        inst._email = email
        inst._api_token = token
        inst._token_manager = None
        inst.client = Zenpy(subdomain=subdomain, email=email, token=token)
        inst.subdomain = subdomain
        inst.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        return inst

    @classmethod
    def from_oauth(cls, subdomain: str, token_manager: OAuthTokenManager) -> "ZendeskClient":
        inst = cls.__new__(cls)
        inst._email = None
        inst._api_token = None
        inst._token_manager = token_manager
        initial_token = token_manager.get_valid_token()
        inst.client = Zenpy(subdomain=subdomain, oauth_token=initial_token)
        inst.subdomain = subdomain
        inst.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        token_manager.register_post_refresh_hook(inst._on_token_refreshed)
        return inst

    @property
    def auth_header(self) -> str:
        if self._token_manager is None:
            credentials = f"{self._email}/token:{self._api_token}"
            return f"Basic {base64.b64encode(credentials.encode()).decode('ascii')}"
        return f"Bearer {self._token_manager.get_valid_token()}"

    def _on_token_refreshed(self, new_access_token: str) -> None:
        # Per spike S2: zenpy stores its requests.Session on each API helper's
        # .session attribute, and all helpers share the same instance. Updating
        # one propagates everywhere. Pinned via zenpy==2.0.56 in pyproject.toml.
        self.client.tickets.session.headers["Authorization"] = f"Bearer {new_access_token}"

    @retry_on_401
    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """
        Query a ticket by its ID
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            return {
                'id': ticket.id,
                'subject': ticket.subject,
                'description': ticket.description,
                'status': ticket.status,
                'priority': ticket.priority,
                'created_at': str(ticket.created_at),
                'updated_at': str(ticket.updated_at),
                'requester_id': ticket.requester_id,
                'assignee_id': ticket.assignee_id,
                'organization_id': ticket.organization_id,
                'tags': list(getattr(ticket, 'tags', []) or []),
                'custom_fields': _serialize_custom_fields(getattr(ticket, 'custom_fields', None)),
            }
        except Exception as e:
            raise Exception(f"Failed to get ticket {ticket_id}: {str(e)}")

    @retry_on_401
    def get_ticket_comments(self, ticket_id: int) -> List[Dict[str, Any]]:
        """
        Get all comments for a specific ticket, including attachment metadata.
        """
        try:
            comments = self.client.tickets.comments(ticket=ticket_id)
            result = []
            for comment in comments:
                attachments = []
                for a in getattr(comment, 'attachments', []) or []:
                    attachments.append({
                        'id': a.id,
                        'file_name': a.file_name,
                        'content_url': a.content_url,
                        'content_type': a.content_type,
                        'size': a.size,
                    })
                result.append({
                    'id': comment.id,
                    'author_id': comment.author_id,
                    'body': comment.body,
                    'html_body': comment.html_body,
                    'public': comment.public,
                    'created_at': str(comment.created_at),
                    'attachments': attachments,
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to get comments for ticket {ticket_id}: {str(e)}")

    # Allowed image MIME types. SVG is excluded — it can contain active XML/JS content.
    _ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

    # Magic bytes (file signatures) for each allowed type.
    _MAGIC_BYTES: Dict[str, List[bytes]] = {
        'image/jpeg': [b'\xff\xd8\xff'],
        'image/png':  [b'\x89PNG\r\n\x1a\n'],
        'image/gif':  [b'GIF87a', b'GIF89a'],
        'image/webp': [b'RIFF'],  # RIFF....WEBP — checked further below
    }

    # 10 MB hard cap to guard against image bombs and token budget blowout.
    _MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

    @retry_on_401
    def get_ticket_attachment(self, content_url: str) -> Dict[str, Any]:
        """
        Fetch an image attachment and return base64-encoded data.

        Security measures applied:
        - Allowlist of safe image MIME types (no SVG or arbitrary binary).
        - Magic byte validation so the file header must match the declared type.
        - 10 MB size cap to prevent image bombs and excessive token usage.

        Zendesk attachment URLs redirect to zdusercontent.com (Zendesk's CDN).
        requests strips the Authorization header on cross-origin redirects,
        which is required — the CDN returns 403 if it receives an auth header.
        """
        try:
            response = _requests.get(
                content_url,
                headers={'Authorization': self.auth_header},
                timeout=30,
                stream=True,
            )
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()

            if content_type not in self._ALLOWED_IMAGE_TYPES:
                raise ValueError(
                    f"Attachment type '{content_type}' is not allowed. "
                    f"Supported types: {sorted(self._ALLOWED_IMAGE_TYPES)}"
                )

            # Read with size cap — stops download as soon as limit is exceeded.
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > self._MAX_ATTACHMENT_BYTES:
                    raise ValueError(
                        f"Attachment exceeds the {self._MAX_ATTACHMENT_BYTES // (1024*1024)} MB size limit."
                    )
                chunks.append(chunk)
            content = b''.join(chunks)

            # Validate magic bytes to catch MIME type spoofing.
            magic_signatures = self._MAGIC_BYTES.get(content_type, [])
            if magic_signatures and not any(content.startswith(sig) for sig in magic_signatures):
                raise ValueError(
                    f"File header does not match declared content type '{content_type}'. "
                    "The attachment may be spoofed."
                )
            # Extra check for WebP: bytes 8–12 must be b'WEBP'.
            if content_type == 'image/webp' and content[8:12] != b'WEBP':
                raise ValueError("File header does not match declared content type 'image/webp'.")

            return {
                'data': base64.b64encode(content).decode('ascii'),
                'content_type': content_type,
            }
        except (ValueError, _requests.HTTPError):
            raise
        except Exception as e:
            raise Exception(f"Failed to fetch attachment from {content_url}: {str(e)}")

    @retry_on_401
    def upload_file(self, filename: str, content_base64: str, content_type: str = 'application/octet-stream') -> Dict[str, Any]:
        """
        Upload a file to Zendesk and return the upload token, which can then be passed
        to create_ticket_comment via the `uploads` parameter to attach it.
        """
        try:
            content = base64.b64decode(content_base64)
            url = f"{self.base_url}/uploads.json?{urllib.parse.urlencode({'filename': filename})}"
            req = urllib.request.Request(url, data=content, method='POST')
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', content_type)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            upload = data.get('upload', {})
            attachment = upload.get('attachment', {}) or {}
            return {
                'token': upload.get('token'),
                'attachment_id': attachment.get('id'),
                'file_name': attachment.get('file_name'),
                'content_type': attachment.get('content_type'),
                'size': attachment.get('size'),
                'content_url': attachment.get('content_url'),
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to upload file '{filename}': HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to upload file '{filename}': {str(e)}")

    # NOT decorated with @retry_on_401 — a retry would post a duplicate comment.
    def post_comment(self, ticket_id: int, comment: str, public: bool = True, uploads: List[str] | None = None) -> str:
        """
        Post a comment to an existing ticket.
        uploads: list of upload tokens from POST /api/v2/uploads.json
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            ticket.comment = Comment(
                html_body=comment,
                public=public,
                uploads=uploads or [],
            )
            self.client.tickets.update(ticket)
            return comment
        except Exception as e:
            raise Exception(f"Failed to post comment on ticket {ticket_id}: {str(e)}")

    @retry_on_401
    def get_tickets(self, page: int = 1, per_page: int = 25, sort_by: str = 'created_at', sort_order: str = 'desc') -> Dict[str, Any]:
        """
        Get the latest tickets with proper pagination support using direct API calls.

        Args:
            page: Page number (1-based)
            per_page: Number of tickets per page (max 100)
            sort_by: Field to sort by (created_at, updated_at, priority, status)
            sort_order: Sort order (asc or desc)

        Returns:
            Dict containing tickets and pagination info
        """
        try:
            # Cap at reasonable limit
            per_page = min(int(per_page), 100)

            # Build URL with parameters for offset pagination
            params = {
                'page': str(page),
                'per_page': str(per_page),
                'sort_by': sort_by,
                'sort_order': sort_order
            }
            query_string = urllib.parse.urlencode(params)
            url = f"{self.base_url}/tickets.json?{query_string}"

            # Create request with auth header
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')

            # Make the API request
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())

            tickets_data = data.get('tickets', [])

            # Process tickets to return only essential fields
            ticket_list = []
            for ticket in tickets_data:
                ticket_list.append({
                    'id': ticket.get('id'),
                    'subject': ticket.get('subject'),
                    'status': ticket.get('status'),
                    'priority': ticket.get('priority'),
                    'description': ticket.get('description'),
                    'created_at': ticket.get('created_at'),
                    'updated_at': ticket.get('updated_at'),
                    'requester_id': ticket.get('requester_id'),
                    'assignee_id': ticket.get('assignee_id'),
                    'organization_id': ticket.get('organization_id'),
                    'group_id': ticket.get('group_id'),
                    'tags': ticket.get('tags', []),
                    'custom_fields': ticket.get('custom_fields', []),
                })

            return {
                'tickets': ticket_list,
                'page': page,
                'per_page': per_page,
                'count': len(ticket_list),
                'sort_by': sort_by,
                'sort_order': sort_order,
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
                'previous_page': page - 1 if data.get('previous_page') and page > 1 else None
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get latest tickets: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get latest tickets: {str(e)}")

    @retry_on_401
    def get_all_articles(self) -> Dict[str, Any]:
        """
        Fetch help center articles as knowledge base.
        Returns a Dict of section -> [article].
        """
        try:
            # Get all sections
            sections = self.client.help_center.sections()

            # Get articles for each section
            kb = {}
            for section in sections:
                articles = self.client.help_center.sections.articles(section.id)
                kb[section.name] = {
                    'section_id': section.id,
                    'description': section.description,
                    'articles': [{
                        'id': article.id,
                        'title': article.title,
                        'body': article.body,
                        'updated_at': str(article.updated_at),
                        'url': article.html_url
                    } for article in articles]
                }

            return kb
        except Exception as e:
            raise Exception(f"Failed to fetch knowledge base: {str(e)}")

    @retry_on_401
    def search_articles(
        self,
        query: str,
        limit: int = 10,
        label_names: List[str] | None = None,
        section_id: int | None = None,
        category_id: int | None = None,
    ) -> List[Dict[str, Any]]:
        try:
            limit = min(limit, 25)
            kwargs: Dict[str, Any] = {}
            if label_names:
                kwargs['label_names'] = label_names
            if section_id is not None:
                kwargs['section'] = section_id
            if category_id is not None:
                kwargs['category'] = category_id

            results = self.client.help_center.articles.search(query, **kwargs)
            hits = []
            for article in results:
                if len(hits) >= limit:
                    break
                section = self.client.help_center._get_section(article.section_id) if article.section_id else None
                category = self.client.help_center._get_category(section.category_id) if section and section.category_id else None
                hits.append({
                    'id': article.id,
                    'title': article.title,
                    'snippet': _make_snippet(article.body or ''),
                    'url': article.html_url,
                    'section': {'id': section.id, 'name': section.name} if section else None,
                    'category': {'id': category.id, 'name': category.name} if category else None,
                    'labels': list(article.label_names or []),
                })
            return hits
        except Exception as e:
            raise Exception(f"Failed to search articles: {str(e)}")

    @retry_on_401
    def get_article(self, article_id: int) -> Dict[str, Any]:
        try:
            article = self.client.help_center._get_article(article_id)
            section = self.client.help_center._get_section(article.section_id) if article.section_id else None
            category = self.client.help_center._get_category(section.category_id) if section and section.category_id else None
            return {
                'id': article.id,
                'title': article.title,
                'body': article.body,
                'url': article.html_url,
                'section': {'id': section.id, 'name': section.name} if section else None,
                'category': {'id': category.id, 'name': category.name} if category else None,
                'labels': list(article.label_names or []),
                'updated_at': str(article.updated_at),
            }
        except Exception as e:
            raise Exception(f"Failed to fetch article {article_id}: {str(e)}")

    @retry_on_401
    def list_sections(self) -> List[Dict[str, Any]]:
        try:
            categories = {c.id: c for c in self.client.help_center.categories()}
            sections = []
            for section in self.client.help_center.sections():
                category = categories.get(section.category_id)
                sections.append({
                    'id': section.id,
                    'name': section.name,
                    'description': section.description,
                    'category': {'id': category.id, 'name': category.name} if category else None,
                })
            return sections
        except Exception as e:
            raise Exception(f"Failed to list sections: {str(e)}")

    @retry_on_401
    def create_ticket(
        self,
        subject: str,
        description: str,
        requester_id: int | None = None,
        assignee_id: int | None = None,
        priority: str | None = None,
        type: str | None = None,
        tags: List[str] | None = None,
        custom_fields: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new Zendesk ticket using Zenpy and return essential fields.

        Args:
            subject: Ticket subject
            description: Ticket description (plain text). Will also be used as initial comment.
            requester_id: Optional requester user ID
            assignee_id: Optional assignee user ID
            priority: Optional priority (low, normal, high, urgent)
            type: Optional ticket type (problem, incident, question, task)
            tags: Optional list of tags
            custom_fields: Optional list of dicts: {id: int, value: Any}
        """
        try:
            ticket = ZenpyTicket(
                subject=subject,
                description=description,
                requester_id=requester_id,
                assignee_id=assignee_id,
                priority=priority,
                type=type,
                tags=tags,
                custom_fields=custom_fields,
            )
            created_audit = self.client.tickets.create(ticket)
            # Fetch created ticket id from audit
            created_ticket_id = getattr(getattr(created_audit, 'ticket', None), 'id', None)
            if created_ticket_id is None:
                # Fallback: try to read id from audit events
                created_ticket_id = getattr(created_audit, 'id', None)

            # Fetch full ticket to return consistent data
            created = self.client.tickets(id=created_ticket_id) if created_ticket_id else None

            return {
                'id': getattr(created, 'id', created_ticket_id),
                'subject': getattr(created, 'subject', subject),
                'description': getattr(created, 'description', description),
                'status': getattr(created, 'status', 'new'),
                'priority': getattr(created, 'priority', priority),
                'type': getattr(created, 'type', type),
                'created_at': str(getattr(created, 'created_at', '')),
                'updated_at': str(getattr(created, 'updated_at', '')),
                'requester_id': getattr(created, 'requester_id', requester_id),
                'assignee_id': getattr(created, 'assignee_id', assignee_id),
                'organization_id': getattr(created, 'organization_id', None),
                'tags': list(getattr(created, 'tags', tags or []) or []),
                'custom_fields': _serialize_custom_fields(getattr(created, 'custom_fields', None)),
            }
        except Exception as e:
            raise Exception(f"Failed to create ticket: {str(e)}")

    @retry_on_401
    def search_tickets(self, query: str, sort_by: str = 'created_at', sort_order: str = 'asc', per_page: int = 10) -> Dict[str, Any]:
        try:
            per_page = min(int(per_page), 100)
            params = {'query': query, 'sort_by': sort_by, 'sort_order': sort_order, 'per_page': str(per_page)}
            url = f"{self.base_url}/search.json?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            ticket_list = [
                {
                    'id': t.get('id'),
                    'subject': t.get('subject'),
                    'status': t.get('status'),
                    'priority': t.get('priority'),
                    'created_at': t.get('created_at'),
                    'updated_at': t.get('updated_at'),
                    'assignee_id': t.get('assignee_id'),
                    'organization_id': t.get('organization_id'),
                    'group_id': t.get('group_id'),
                    'tags': t.get('tags', []),
                    'custom_fields': t.get('custom_fields', []),
                }
                for t in data.get('results', [])
                if t.get('result_type') == 'ticket'
            ]
            return {
                'tickets': ticket_list,
                'count': len(ticket_list),
                'total_count': data.get('count', len(ticket_list)),
                'has_more': data.get('next_page') is not None,
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to search tickets: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to search tickets: {str(e)}")

    @retry_on_401
    def get_organization(self, organization_id: int) -> Dict[str, Any]:
        try:
            url = f"{self.base_url}/organizations/{organization_id}.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            org = data.get('organization', {})
            return {
                'id': org.get('id'),
                'name': org.get('name'),
                'organization_fields': org.get('organization_fields', {}),
                'tags': org.get('tags', []),
                'created_at': org.get('created_at'),
                'updated_at': org.get('updated_at'),
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get organization {organization_id}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get organization {organization_id}: {str(e)}")

    @retry_on_401
    def search_users(self, query: str) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/users/search.json?{urllib.parse.urlencode({'query': query})}"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            return [
                {'id': u.get('id'), 'name': u.get('name'), 'email': u.get('email'), 'role': u.get('role')}
                for u in data.get('users', [])
            ]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to search users: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to search users: {str(e)}")

    @retry_on_401
    def get_group_users(self, group_id: int) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/groups/{group_id}/users.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            return [
                {'id': u.get('id'), 'name': u.get('name'), 'email': u.get('email')}
                for u in data.get('users', [])
            ]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get users for group {group_id}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get users for group {group_id}: {str(e)}")

    @retry_on_401
    def get_groups(self) -> List[Dict[str, Any]]:
        try:
            url = f"{self.base_url}/groups.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            return [
                {'id': g.get('id'), 'name': g.get('name')}
                for g in data.get('groups', [])
                if not g.get('deleted', False)
            ]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get groups: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get groups: {str(e)}")

    @retry_on_401
    def list_custom_statuses(self) -> List[Dict[str, Any]]:
        """
        List all custom ticket statuses defined in Zendesk.
        """
        try:
            url = f"{self.base_url}/custom_statuses"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            return [
                {
                    'id': s.get('id'),
                    'agent_label': s.get('agent_label'),
                    'end_user_label': s.get('end_user_label'),
                    'status_category': s.get('status_category'),
                    'active': s.get('active'),
                    'default': s.get('default'),
                }
                for s in data.get('custom_statuses', [])
            ]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to list custom statuses: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to list custom statuses: {str(e)}")

    @retry_on_401
    def get_jira_links(self, ticket_id: int) -> List[Dict[str, Any]]:
        try:
            links = self.client.jira_links(ticket_id=ticket_id)
            return [
                {
                    'id': l.id,
                    'ticket_id': l.ticket_id,
                    'issue_id': l.issue_id,
                    'issue_key': l.issue_key,
                    'url': l.url,
                    'created_at': str(l.created_at),
                    'updated_at': str(l.updated_at),
                }
                for l in links
            ]
        except Exception as e:
            raise Exception(f"Failed to get Jira links for ticket {ticket_id}: {str(e)}")

    @retry_on_401
    def get_zendesk_tickets_for_jira_issue(self, issue_id: str) -> List[Dict[str, Any]]:
        try:
            links = self.client.jira_links(issue_id=issue_id)
            return [
                {
                    'id': l.id,
                    'ticket_id': l.ticket_id,
                    'issue_id': l.issue_id,
                    'issue_key': l.issue_key,
                    'url': l.url,
                    'created_at': str(l.created_at),
                    'updated_at': str(l.updated_at),
                }
                for l in links
            ]
        except Exception as e:
            raise Exception(f"Failed to get Zendesk tickets for Jira issue {issue_id}: {str(e)}")

    @retry_on_401
    def list_ticket_fields(self) -> List[Dict[str, Any]]:
        try:
            return [
                {
                    'id': f.id,
                    'title': f.title,
                    'type': f.type,
                    'description': f.description,
                    'active': f.active,
                    'required': f.required,
                }
                for f in self.client.ticket_fields()
                if getattr(f, 'active', True)
            ]
        except Exception as e:
            raise Exception(f"Failed to list ticket fields: {str(e)}")

    @retry_on_401
    def list_macros(self) -> List[Dict[str, Any]]:
        try:
            result = []
            for m in self.client.macros():
                if not getattr(m, 'active', True):
                    continue
                actions = [
                    {'field': getattr(a, 'field', None), 'value': getattr(a, 'value', None)}
                    for a in (getattr(m, 'actions', []) or [])
                ]
                result.append({
                    'id': m.id,
                    'title': m.title,
                    'description': m.description,
                    'actions': actions,
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to list macros: {str(e)}")

    @retry_on_401
    def preview_macro(self, macro_id: int) -> Dict[str, Any]:
        try:
            url = f"{self.base_url}/macros/{macro_id}/apply.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            return data.get('result', {})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to preview macro {macro_id}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to preview macro {macro_id}: {str(e)}")

    # NOT decorated with @retry_on_401 — macros can have non-idempotent side
    # effects (post comment, change tags, mutate ticket state). A retry would
    # replay them.
    def apply_macro(self, ticket_id: int, macro_id: int) -> Dict[str, Any]:
        try:
            url = f"{self.base_url}/tickets/{ticket_id}/macros/{macro_id}/apply.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            result = data.get('result', {})
            ticket_changes = result.get('ticket', {})
            comment_data = result.get('comment', {})

            if ticket_changes:
                ticket = self.client.tickets(id=ticket_id)
                skip = {'id', 'url', 'created_at', 'updated_at'}
                for key, value in ticket_changes.items():
                    if key not in skip:
                        setattr(ticket, key, value)
                self.client.tickets.update(ticket)

            comment_added = False
            if comment_data:
                body = comment_data.get('html_body') or comment_data.get('body')
                if body:
                    self.post_comment(ticket_id, body, public=comment_data.get('public', True))
                    comment_added = True

            refreshed = self.client.tickets(id=ticket_id)
            return {
                'id': refreshed.id,
                'status': refreshed.status,
                'tags': list(getattr(refreshed, 'tags', []) or []),
                'applied_changes': ticket_changes,
                'comment_added': comment_added,
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to apply macro {macro_id} to ticket {ticket_id}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to apply macro {macro_id} to ticket {ticket_id}: {str(e)}")

    @retry_on_401
    def get_view(self, view_id: int) -> Dict[str, Any]:
        try:
            url = f"{self.base_url}/views/{view_id}.json"
            req = urllib.request.Request(url)
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            v = data.get('view', {})
            return {
                'id': v.get('id'),
                'title': v.get('title'),
                'active': v.get('active'),
                'conditions': v.get('conditions'),
                'execution': v.get('execution'),
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to get view {view_id}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to get view {view_id}: {str(e)}")

    @retry_on_401
    def list_views(self) -> List[Dict[str, Any]]:
        try:
            return [
                {'id': v.id, 'title': v.title}
                for v in self.client.views.active()
            ]
        except Exception as e:
            raise Exception(f"Failed to list views: {str(e)}")

    @retry_on_401
    def get_view_tickets(self, view_id: int) -> List[Dict[str, Any]]:
        try:
            return [
                {
                    'id': t.id,
                    'subject': t.subject,
                    'status': t.status,
                    'priority': t.priority,
                    'assignee_id': t.assignee_id,
                    'requester_id': t.requester_id,
                    'organization_id': t.organization_id,
                    'group_id': t.group_id,
                    'created_at': str(t.created_at),
                    'updated_at': str(t.updated_at),
                    'tags': list(getattr(t, 'tags', []) or []),
                    'custom_fields': _serialize_custom_fields(getattr(t, 'custom_fields', None)),
                }
                for t in self.client.views.tickets(view_id)
            ]
        except Exception as e:
            raise Exception(f"Failed to get tickets for view {view_id}: {str(e)}")

    @retry_on_401
    def add_tag(self, ticket_id: int, tag: str) -> List[str]:
        try:
            ticket = self.client.tickets(id=ticket_id)
            current = list(getattr(ticket, 'tags', []) or [])
            if tag not in current:
                current.append(tag)
                ticket.tags = current
                self.client.tickets.update(ticket)
            refreshed = self.client.tickets(id=ticket_id)
            return list(getattr(refreshed, 'tags', []) or [])
        except Exception as e:
            raise Exception(f"Failed to add tag '{tag}' to ticket {ticket_id}: {str(e)}")

    @retry_on_401
    def remove_tag(self, ticket_id: int, tag: str) -> List[str]:
        try:
            ticket = self.client.tickets(id=ticket_id)
            current = list(getattr(ticket, 'tags', []) or [])
            if tag in current:
                current.remove(tag)
                ticket.tags = current
                self.client.tickets.update(ticket)
            refreshed = self.client.tickets(id=ticket_id)
            return list(getattr(refreshed, 'tags', []) or [])
        except Exception as e:
            raise Exception(f"Failed to remove tag '{tag}' from ticket {ticket_id}: {str(e)}")

    # NOT decorated with @retry_on_401 — a retry would create a duplicate Jira link.
    def create_jira_link(self, ticket_id: int, issue_key: str, issue_id: str) -> Dict[str, Any]:
        # Zenpy's Link() never sends issue_id, causing a 422 from the endpoint.
        # POST directly to /api/services/jira/links instead.
        try:
            base = self.base_url.replace('/api/v2', '')
            url = f"{base}/api/services/jira/links"
            payload = json.dumps({'ticket_id': ticket_id, 'issue_key': issue_key, 'issue_id': str(issue_id)}).encode()
            req = urllib.request.Request(url, data=payload, method='POST')
            req.add_header('Authorization', self.auth_header)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
            link = data.get('link', data)
            return {
                'id': link.get('id'),
                'ticket_id': link.get('ticket_id'),
                'issue_id': link.get('issue_id'),
                'issue_key': link.get('issue_key'),
                'url': link.get('url'),
                'created_at': str(link.get('created_at', '')),
            }
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Failed to create Jira link for ticket {ticket_id} / {issue_key}: HTTP {e.code} - {e.reason}. {error_body}")
        except Exception as e:
            raise Exception(f"Failed to create Jira link for ticket {ticket_id} / {issue_key}: {str(e)}")

    @retry_on_401
    def delete_jira_link(self, link_id: int) -> None:
        try:
            self.client.jira_links.delete(Link(id=link_id))
        except Exception as e:
            raise Exception(f"Failed to delete Jira link {link_id}: {str(e)}")

    @retry_on_401
    def update_ticket(self, ticket_id: int, **fields: Any) -> Dict[str, Any]:
        """
        Update a Zendesk ticket with provided fields using Zenpy.

        Supported fields include common ticket attributes like:
        subject, status, priority, type, assignee_id, requester_id,
        tags (list[str]), custom_fields (list[dict]), due_at, etc.
        Pass assignee_id=null to unassign the ticket.
        """
        try:
            # Load the ticket, mutate fields directly, and update
            ticket = self.client.tickets(id=ticket_id)
            for key, value in fields.items():
                setattr(ticket, key, value)

            # This call returns a TicketAudit (not a Ticket). Don't read attrs from it.
            self.client.tickets.update(ticket)

            # Fetch the fresh ticket to return consistent data
            refreshed = self.client.tickets(id=ticket_id)

            return {
                'id': refreshed.id,
                'subject': refreshed.subject,
                'description': refreshed.description,
                'status': refreshed.status,
                'priority': refreshed.priority,
                'type': getattr(refreshed, 'type', None),
                'created_at': str(refreshed.created_at),
                'updated_at': str(refreshed.updated_at),
                'requester_id': refreshed.requester_id,
                'assignee_id': refreshed.assignee_id,
                'organization_id': refreshed.organization_id,
                'tags': list(getattr(refreshed, 'tags', []) or []),
                'custom_fields': _serialize_custom_fields(getattr(refreshed, 'custom_fields', None)),
            }
        except Exception as e:
            raise Exception(f"Failed to update ticket {ticket_id}: {str(e)}")


def build_zendesk_client() -> ZendeskClient:
    """Construct a ZendeskClient based on environment configuration.

    Mode selection:
      - If ZENDESK_CLIENT_ID is set (truthy — empty string falls through to
        API-token mode), uses OAuth. Requires a token file written by
        `zendesk-auth`. Hard-fails if the file is missing.
      - Otherwise uses the legacy API-token path.
    """
    subdomain = os.getenv("ZENDESK_SUBDOMAIN")
    if not subdomain:
        raise EnvironmentError("ZENDESK_SUBDOMAIN is required.")

    client_id = os.getenv("ZENDESK_CLIENT_ID")
    if client_id:  # truthy — empty string falls through to API-token mode
        client_secret = os.getenv("ZENDESK_CLIENT_SECRET")
        if not client_secret:
            raise EnvironmentError(
                "ZENDESK_CLIENT_ID is set but ZENDESK_CLIENT_SECRET is missing."
            )
        try:
            token_manager = OAuthTokenManager(subdomain, client_id, client_secret)
        except FileNotFoundError as e:
            raise EnvironmentError(
                f"OAuth token file missing for subdomain '{subdomain}'. "
                f"Run zendesk-auth to authenticate."
            ) from e
        logger.warning("auth_mode=oauth subdomain=%s", subdomain)
        return ZendeskClient.from_oauth(subdomain, token_manager)

    email = os.getenv("ZENDESK_EMAIL")
    api_token = os.getenv("ZENDESK_API_KEY")
    if not email or not api_token:
        missing = [
            name
            for name, val in [("ZENDESK_EMAIL", email), ("ZENDESK_API_KEY", api_token)]
            if not val
        ]
        raise EnvironmentError(
            f"API-token mode selected but missing: {', '.join(missing)}. "
            f"Set ZENDESK_CLIENT_ID to use OAuth instead."
        )
    return ZendeskClient.from_api_token(subdomain, email, api_token)
