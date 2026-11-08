# Habit

**Learns which commands you already approve, proposes a safe allowlist pattern, and only writes it after you confirm — dangerous shapes never auto-allow.**

![Habit](docs/banner-hero.jpg)


## Why a plugin (not a skill / prompt)

A skill can only *remind* the model. Habit uses Hermes’s real approval hooks (`pre_approval_request` / `post_approval_response`), stores your decisions locally, and — in **enforce** mode — **proposes** a safe generalised pattern after a threshold of matching approvals. A person must run `/habit accept` (CLI or messaging gateway) before anything is written to Hermes’s `command_allowlist`. That keeps catalog **rule 12**: Habit never auto-approves and never disables guards.

No extra LLM. Deterministic.

## Modes

| mode | behaviour |
|------|-----------|
| `off` | do nothing |
| `observe` (**default**) | record decisions; `/habit why` works; **no proposals, no allowlist writes** |
| `enforce` | after `threshold` matching approvals, create a **pending proposal**; still no write until `/habit accept` |

## Confirm step (required)

```text
/habit proposals          list pending
/habit accept <id>        write that pattern to command_allowlist
/habit accept all         accept every pending proposal
/habit reject <id>|all    drop proposal(s)
```

Unattended runs (cron, gateway with no person, YOLO/oneshot) never call accept — so they never add allowlist entries.

### Messaging gateway (Telegram / Discord / …)

`/habit` is registered via `ctx.register_command`, so the same slash commands work on the gateway. On Telegram, type `/habit accept 1` (or `/habit_accept` autocomplete forms Hermes may expose). The reply text comes back in the chat. Approvals you click in the gateway still feed Habit’s counters; only the explicit accept writes the allowlist.

### Owner-lock (gateway)

Mutating commands — `accept`, `reject`, `undo`, `forget`, `uninstall` — are **owner-locked** on the messaging gateway. Only user ids listed in `plugins.entries.habit.settings.owner_ids` may run them. Everyone else gets a refusal (logged). If Hermes does not expose a sender id, Habit **fails closed** (refuses). Local CLI / TUI / desktop are exempt (you are at the keyboard). Read-only `why` / `status` / `proposals` / `help` stay open.

```yaml
plugins:
  entries:
    habit:
      settings:
        mode: enforce
        threshold: 2
        owner_ids: ["123456789"]   # Telegram / Discord / … user id(s)
```


## What it may propose vs never

| May propose (examples) | Never proposes |
|------------------------|----------------|
| `docker stop *`, `docker restart *` | Home / recursive wipe shapes |
| `pytest *`, `python -m pytest *` | Download-and-execute pipes |
| `git status *`, `git diff *`, `git log *` | `git push` (incl. force) |
| Workspace-scoped `ls` / `cat` / `head` / `tail` / `rg` | Secret paths; out-of-project; shell chains |

Accept broad patterns only where you trust the project: `pytest *` runs the project's own test code, and some `git diff` options can write files.

## Other commands

```text
/habit why          why it asked / pending proposals
/habit status       pending + accepted
/habit forget <p>   drop accepted entry + allowlist row
/habit undo         undo last accept
/habit uninstall    remove every allowlist entry Habit added + clear pending
```

## Install

```bash
# symlink / copy into $HERMES_HOME/plugins/habit && enable
hermes plugins enable habit
hermes plugins doctor habit
# leave observe until you want proposals:
hermes config set plugins.entries.habit.settings.mode observe
# when ready to propose (still needs /habit accept to write):
hermes config set plugins.entries.habit.settings.mode enforce
hermes config set plugins.entries.habit.settings.threshold 3
```

## Uninstall (clean)

```text
/habit uninstall
```

Then `hermes plugins disable habit`.

## Safety / disclosure

- Observer hooks only — if Habit errors, Hermes asks as usual.
- **Never auto-writes `command_allowlist`.** Human `/habit accept` only.
- Never proposes the never-auto set.
- No telemetry. Local SQLite via `plugin_db`. No secrets from disk.
- Disclosure: after accept, Habit writes `command_allowlist` in the active `HERMES_HOME` (official Always path).

## Develop

```bash
python -m pytest -q                      # needs pytest
python doctor.py && python validate.py   # need PyYAML
python eval/run_eval.py
HERMES_HOME=... hermes plugins doctor habit
HERMES_HOME=... hermes plugins validate .
```

See `INSTALL.md`, `DEMO.md`, `CHANGELOG.md`, `catalog-draft/CHECKLIST.md`.
