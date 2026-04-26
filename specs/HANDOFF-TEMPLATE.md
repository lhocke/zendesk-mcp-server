# Handoff: <feature name>

**Branch:** `feat/<name>`
**Spec authored:** <YYYY-MM-DD>
**Status:** Ready for implementation

## What's in this branch

- `specs/<feature>/spec.md` — feature spec
- `specs/<feature>/test-strategy.md` — test plan (only if scope warranted one)
- `specs/<feature>/implementation-plan.md` — phased build order (only if scope warranted one)

## Setup deltas (work machine)

<New env vars, dependencies, Zendesk admin config, OAuth scopes, etc. that the work machine needs before implementation. Leave blank if none.>

## Validation checklist (post-implementation)

<Tickets, articles, or scenarios to test against. The spec-authoring machine has no prod credentials — these checks must run on the work machine.>

- [ ] <example: `search_articles("billing")` returns at least 3 hits with non-empty titles>
- [ ] <example: `get_article(<known_id>)` returns full body matching what's in the Help Center UI>

## Open questions for the implementer

<Anything the spec deferred or that came up after spec convergence. Empty is fine.>

## After merge

- Delete this `HANDOFF.md` from `main` in the merge commit (or a follow-up).
- Leave `specs/<feature>/` in place as the durable record.
- Update `GAPS.md` if the feature closed a gap.
