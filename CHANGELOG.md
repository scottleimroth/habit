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
