# KB Search Tools

## Goal

Add three Help Center tools — `search_articles`, `get_article`, `list_sections` — so skills can do targeted retrieval (search → optionally fetch full body) instead of pulling the entire knowledge base into context every time. The existing `zendesk://knowledge-base` resource stays in place until skills are validated to no longer use it.

## Motivation

Today, the only way for a skill to consult Help Center content is to read `zendesk://knowledge-base`, which dumps every section's full article bodies in one JSON blob. For ticket-analysis skills that only need a few relevant articles per ticket, that's a context flood. The new tools give skills a search-then-fetch pattern using Zendesk's existing article search API.

## Tools

### `search_articles`

Search Help Center articles by query, with optional filters.

**Params**
- `query` (string, required) — search text.
- `limit` (integer, optional) — default 10, max 25.
- `label_names` (array of string, optional) — filter to articles tagged with any of these labels.
- `section_id` (integer, optional) — restrict to a section.
- `category_id` (integer, optional) — restrict to a category.

**Response** — array of hits, each:
- `id` (integer)
- `title` (string)
- `snippet` (string) — ~200-char excerpt synthesized from the article body with HTML stripped; appends `...` if truncated.
- `url` (string) — `html_url` (Help Center web URL).
- `section` (object `{id, name}`)
- `category` (object `{id, name}`)
- `labels` (array of string)

Empty results return `[]`, not an error.

zenpy entry point: `client.help_center.articles.search(query=..., section=..., category=..., label_names=...)`. Exact zenpy parameter names should be verified on the work machine — adjust the wrapper if they diverge.

### `get_article`

Fetch one article's full body by ID.

**Params**
- `article_id` (integer, required)

**Response**
- `id`, `title`, `body` (HTML, as Zendesk returns it), `url`, `section` (`{id, name}`), `category` (`{id, name}`), `labels`, `updated_at`.

zenpy: `client.help_center.articles(id=article_id)` — verify the call shape on the work machine; if zenpy uses a different accessor (e.g. `articles.show`), match it.

### `list_sections`

List all Help Center sections with their parent category. No filters — the deployment is single-brand and section count is bounded.

**Params** — none.

**Response** — array of sections, each:
- `id`, `name`, `description`, `category` (`{id, name}`)

zenpy: `client.help_center.sections()` (already used in `get_all_articles`). Category lookup may require an extra call (`client.help_center.categories()`); cache the category list for the duration of the request rather than calling per section.

## OAuth scope

The current OAuth client requests `"read write"` (`auth.py:111`). Zendesk's documented scope model has separate `hc:read` / `hc:write` for Help Center. The existing `get_all_articles` works in production today, but it's not certain whether that's because:
- (a) the deployment runs in API-token mode, which has full access regardless of scopes, or
- (b) Zendesk's `read` scope implicitly grants Help Center read.

**Action for the work machine**: before implementing, test the existing `zendesk://knowledge-base` resource under OAuth mode. If it works, no scope change needed. If it returns 403, add `hc:read` to the OAuth client config in Zendesk Admin and have users re-run `zendesk-auth` to acquire a token with the new scope. Flag this in `HANDOFF.md`'s setup deltas if it turns out to be required.

## Non-goals

- No `create_article` / `update_article` / `delete_article` — authoring stays in the Zendesk UI.
- No standalone `list_categories` — category info is surfaced inside `list_sections` results and search hits, which covers the disambiguation use case.
- No `locale` parameter — single-brand deployment, brand default locale is fine.
- No deprecation of `zendesk://knowledge-base` in this work. After skills migrate, schedule a follow-up to remove the resource and `get_all_articles`.
- No caching on the new tools. The existing resource has a 1hr TTL because it's expensive to build; the new tools are cheap per-call and skills should always see fresh data.

## Implementation notes

- All three new client methods follow the existing `@retry_on_401` pattern from `zendesk_client.py`.
- Tool registration in `server.py` matches the pattern used for `search_tickets`, `get_ticket`, etc. — JSON Schema input, dispatcher in the tool handler.
- Snippet synthesis: strip HTML with `html.parser` (stdlib, already a likely indirect dep) or a tiny custom regex stripper. Take the first 200 chars of the stripped text; if longer, truncate at the last word boundary before 200 and append `...`.
- The existing `zendesk://knowledge-base` resource and `get_cached_kb` TTL cache are not touched.

## Validation (work machine)

- `search_articles("permissions")` returns at least one hit; results include `section` and `category` populated.
- `search_articles("permissions", section_id=<known_id>)` narrows the result set correctly.
- `get_article(<known_id>)` returns full HTML body matching the Help Center UI rendering.
- `list_sections()` returns all sections, each with its parent category id+name correctly populated.
- Existing `zendesk://knowledge-base` resource still works (regression check).
- All three tools work end-to-end under OAuth mode (after any required scope adjustment).
