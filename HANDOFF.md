# Handoff: Connection Skill (Lifecycle for HTTP MCP Server)

**Branch:** `feat/connection-skill`
**Spec authored:** 2026-04-26
**Status:** Ready for implementation. HTTP transport already shipped via `feat/http-transport`, so this branch can be picked up whenever it surfaces as useful.

## What's in this branch

- `specs/connection-skill/spec.md` — feature spec (no test-strategy or implementation-plan; surface is a script + a hook snippet + a skill markdown file)

## Setup deltas (work machine)

- **Verify the HTTP entry point shape**: the spec's lifecycle script assumes the server can be started as `zendesk-mcp-server --http` (or equivalent). HTTP transport already shipped, so check the actual entry point that landed in `main` and adjust the script's `nohup` line to match if it diverges from the spec's assumption.
- **Look at an existing skill before writing the SKILL.md**: the spec deliberately leaves the skill frontmatter schema unspecified. On the work machine, open one of the user's existing skills in `~/.claude/skills/` to confirm the current `name`/`description`/`tools` keys and frontmatter shape, then mirror that.
- **`jq` for the optional `install-hook.sh` helper**: if you build the helper, it needs `jq` (or graceful fallback). `jq` is on most dev machines but not guaranteed.
- **Bash version**: macOS ships bash 3.2. Test the script on the work machine's macOS bash, not just zsh. Avoid bash-4-only features.

No new Python dependencies. No OAuth scope changes.

## Validation checklist (post-implementation)

- [ ] `scripts/ensure-zendesk-mcp.sh` is `chmod +x` and runs from a fresh checkout.
- [ ] No server running: script starts the server, exits 0 within 10s with a clear stdout summary.
- [ ] Server already running: script exits 0 immediately, no duplicate process (`pgrep -af uvicorn` shows one).
- [ ] `ZENDESK_MCP_PORT=9000 scripts/ensure-zendesk-mcp.sh`: starts on port 9000.
- [ ] Crash recovery: `pkill -f "uvicorn.*zendesk_mcp_server"`, then run the script — server is back up.
- [ ] Concurrency: running the script in parallel (`scripts/ensure-zendesk-mcp.sh & scripts/ensure-zendesk-mcp.sh & wait`) doesn't double-start.
- [ ] `SessionStart` hook configured in `~/.claude/settings.local.json`: a fresh `claude` session in this repo fires the hook and the server is reachable before the first tool call (no `/mcp reconnect` needed).
- [ ] Log file `/tmp/zendesk-mcp.log` (or `$ZENDESK_MCP_LOG`) contains uvicorn output after a fresh start.
- [ ] Recovery skill installed at `~/.claude/skills/zendesk-recovery/`: invoking it after killing the server runs the script, restarts the server, and gives the user the right next-step instruction (retry tool call vs. `/mcp reconnect zendesk`).
- [ ] README has a new "Lifecycle" section with the script path, hook snippet, and skill install instructions.
- [ ] `install-hook.sh` (if built) merges into existing `settings.local.json` without clobbering other hooks, OR prints the snippet and asks the user to add it manually if `jq` is missing / the file shape is unexpected.

## Open questions for the implementer

- **Skill name**: `zendesk-recovery` is a reasonable default but not load-bearing. Pick whatever name reads well in `/skill-name` invocations and matches Dylan's existing skill naming pattern.
- **`install-hook.sh` helper**: build it if it shaves real friction; skip it if the README snippet is good enough. Dylan's call during implementation.
- **Where the skill source lives in the repo**: spec says `skills/zendesk-recovery/SKILL.md`. If there's a strong reason to put it elsewhere (e.g. a top-level `tools/` dir that already exists), use that. The repo currently has no skills directory, so we're establishing the convention.

## After merge

- Delete this `HANDOFF.md` from `main` in the merge commit (or a follow-up).
- Leave `specs/connection-skill/` in place as the durable record.
- Update README's getting-started section so first-time users know the SessionStart hook is the recommended setup.
- If the team adopts the SessionStart hook universally and confirms the recovery skill is rarely needed, that's a useful signal — capture it as a one-line note for future maintainers.
