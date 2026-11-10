## 0.1.4

- Habit now tells you when it has an offer. When enforce mode creates a proposal it posts one message in the chat
  where you approved, for example: "Habit: you've approved `docker stop web` 2 times. Reply /habit accept 1 to stop
  being asked for `docker stop *` (any container, any options), or /habit reject 1 to keep asking."
- Sent once per proposal, never in observe mode, never for never-auto or smart-approver decisions. Posting accepts
  nothing. New setting `notify` (default true) turns it off.
- Uses only the public `ctx.post_message` (Hermes 0.23). The post runs on a short-lived thread that keeps the hook's
  session, so a slow gateway never delays the approval. A failed post is logged; the proposal stays in
  `/habit proposals`, and `/habit status` shows whether the message was posted.
- `/habit status` adds how to answer pending proposals.
- Tests: message on creation, exact and glob wording, no repeats (same entry, other container, store re-add), new
  proposal after reject, failed, raising and undelivered posts tolerated, hook not blocked, session context kept,
  nothing in observe mode or with notify off, nothing written to the allowlist.

## 0.1.3

Review of 973100ab (NousResearch/hermes-agent#151289):
- `git branch` is no longer generalised: approving `git branch -D x` proposed `git branch *`, which also allowed
  every force-delete. "git branch force delete" is now never-auto, and Habit's own rule is wider than Hermes's
  (`-D`, any short-flag cluster with `f`, `--force`, and global options before `branch`).
- No more path globs. Hermes matches `*` across `/`, spaces and extra arguments, so `cat ./*` was not path-scoped.
  cat, head, tail, rg, grep, ls and wc are proposed as the exact approved command.
- Checked every remaining glob the same way: `git diff|log|show|shortlog *` allow `--output=<file>` (writes a
  file) and `pytest *` / `python -m pytest *` allow `--basetemp=<dir>` (deletes that directory's contents), so all
  git and pytest commands are exact-only too. The only globs left are `docker stop|restart *` and
  `docker compose stop|restart *`, labelled as any container or service with any options; podman and echo globs removed.
- Exact entries containing `*`, `?` or `[` are written bracket-escaped (`ls [*].py`), so Hermes reads them literally.
- `cat ./../../etc/shadow`-style relative paths to shadow/sudoers are never-auto.
- Tests: three approved `git branch -D x` propose nothing; no proposal for a corpus of approved commands matches any
  of a corpus of wider commands under Hermes's own matching rule; escaped exact entries round-trip through accept,
  lookup and undo. Eval: 4 review cases added (79 samples).
- Entries accepted under 0.1.2 stay in `command_allowlist` until removed with `/habit forget` or `/habit uninstall`.

## 0.1.2

- Persist allowlist edits through public config helpers only, without private-state mutation.
- Ignore unidentified chat approvals and built-in smart/AI approver decisions.
- Require tested Hermes 0.23.0 behaviour; clarify installation, dependencies and removal limits.

# Changelog

## 0.1.1 — 2026-11-05

- Gateway owner-lock: `/habit accept|reject|undo|forget|uninstall` only for `settings.owner_ids`; missing sender id fails closed; local CLI exempt. Refusals logged.
- Docs + tests for owner-lock; `plugin.yaml` schema adds `owner_ids`.
- **Confirm step (catalog rule 12):** enforce mode only *proposes* after threshold; `/habit accept` / `reject` required to write `command_allowlist`. Observe default records only.
- Commands: `proposals`, `accept <id>|all`, `reject <id>|all`.
- Unattended paths never write allowlist (accept is human-only; works on gateway slash too).
- Eval + tests updated; doctor/validate green.

## 0.1.0 — 2026-11-05

- Initial Habit plugin for Hermes ≥0.21.5 (hooks compatible with 0.22.x).
- Modes: `off` / `observe` / `enforce`.
- Safe generalised patterns; never-auto set; `/habit why|status|forget|undo|uninstall`.
- Local `plugin_db`; tracks Habit-owned allowlist entries for clean uninstall.
