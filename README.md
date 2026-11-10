# Habit

**Learns which commands you already approve, proposes a safe allowlist pattern, and only writes it after you confirm — dangerous shapes never auto-allow.**

![Habit](docs/banner-hero.jpg)

**Demo video (57 seconds):** https://x.com/ScottLeimroth/status/2119407230940488173


## Why a plugin (not a skill / prompt)

A skill can only *remind* the model. Habit uses Hermes’s real approval hooks (`pre_approval_request` / `post_approval_response`), stores your decisions locally, and — in **enforce** mode — **proposes** a safe generalised pattern after a threshold of matching approvals. A person must run `/habit accept` (CLI or messaging gateway) before anything is written to Hermes’s `command_allowlist`. That keeps catalog **rule 12**: Habit never auto-approves and never disables guards.

No extra LLM. Deterministic.

## Modes

| mode | behaviour |
|------|-----------|
| `off` | do nothing |
| `observe` (**default**) | record decisions; `/habit why` works; **no proposals, no allowlist writes** |
| `enforce` | after `threshold` matching approvals, create a **pending proposal**; still no write until `/habit accept` |

## Habit tells you when it has an offer

When enforce mode creates a proposal, Habit posts one message in the chat where you just approved:

```text
Habit: you've approved `docker stop web` 2 times. Reply /habit accept 1 to stop being asked for `docker stop *` (any container, any options), or /habit reject 1 to keep asking.
```

For any other command it says "to stop being asked for exactly this command". It is sent once per proposal and
never in observe mode. Posting accepts nothing; only your `/habit accept` writes the allowlist. Pending proposals
also show in `/habit status`, with whether the message was posted. Turn the message off with
`hermes config set plugins.entries.habit.settings.notify false`.

It uses Hermes's public `ctx.post_message`, which needs a running Hermes gateway in the same process: a messaging
chat, or a Desktop/TUI chat attached to the gateway. A process with no running gateway (for example a standalone
`hermes serve`), or `plugins.isolation: host`, cannot post. Habit then logs the failure and the proposal stays in
`/habit proposals` and `/habit status`. The post runs on its own short-lived thread, so it never delays the
approval. Chat approvals without an approver identity (Hermes 0.23 Matrix and Telegram) are still not learned,
so no proposal and no message come from them.

## Confirm step (required)

```text
/habit proposals          list pending
/habit accept <id>        write that pattern to command_allowlist
/habit accept all         accept every pending proposal
/habit reject <id>|all    drop proposal(s)
```

Unattended runs (cron, gateway with no person, YOLO/oneshot) never call accept — so they never add allowlist entries.

### Messaging gateway (Telegram / Discord / …)

`/habit` is registered via `ctx.register_command`, so the same slash commands work on the gateway. On Telegram, type `/habit accept 1` (or `/habit_accept` autocomplete forms Hermes may expose). The reply text comes back in the chat. Gateway approvals count only when Hermes supplies an approver identity, and only an owner's approvals (the id is in
`owner_ids`, the same rule as the owner lock) can lead to a proposal; anyone else's are kept apart and never proposed. Unidentified chat approvals (including Hermes 0.23 Matrix/Telegram events) are ignored. Local keyboard approvals still count. Only explicit accept writes the allowlist.

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

| May propose | Never proposes |
|-------------|----------------|
| `docker stop *`, `docker restart *`: stop or restart **any** container, with any stop/restart options | Home / recursive wipe shapes |
| `docker compose stop *`, `docker compose restart *`: **any** service, with any options | Download-and-execute pipes |
| Any other command you approved: **that exact command only** | `git push` (incl. force); `git branch` force delete or force reset |
| | Secret paths; shell chains; `docker run`/`exec`/`rm`/`kill`, `compose down`, remote daemons |

Hermes matches an allowlist entry against the whole command line, and `*` there matches `/`, spaces and any extra
arguments. A glob is therefore only as narrow as every option of the command behind it: `cat ./*` would also match
`cat ./a ~/.ssh/id_rsa`, `git log *` would also allow `git log --output=<file>` (writes a file), and `pytest *` would
also allow `pytest --basetemp=<dir>` (deletes that directory's contents). So Habit proposes a glob only for the
container lifecycle commands above, and proposes everything else exactly as you approved it. An exact command that
contains `*`, `?` or `[` is written with those characters bracketed (`ls [*].py`), so Hermes matches only that command.

Hermes 0.23 asks for approval on shell commands only when they are on its own dangerous-command list, so those are
the only commands Habit learns; in practice that is mostly container lifecycle and repeats of other flagged commands
you keep approving. Approvals are counted per Hermes rule and per approver, so different rules never add up.
An exact command containing a shell operator (`|`, `;`, `&`, `>`, `<`, backtick, `$(`) is never proposed, because
Hermes never matches an allowlist entry against such a command.

The same approval hooks also fire for prompts that are not shell commands. Habit never learns from them: nothing is
recorded, counted, proposed or posted. These are plugin `pre_tool_call` rules (`plugin_rule:` keys, shown as
`<tool> (plugin approval rule)`), computer_use actions, SSH config and protected-file writes, execute_code scripts,
MCP elicitation and editor diffs. Those checks are meant to be seen by a person every time.

**Upgrading from 0.1.5 or earlier:** older versions could learn from plugin approval rules and propose the label
`<terminal> (plugin approval rule)`. It never matched a command, so it allowed nothing. On load, 0.1.6 forgets those
recorded approvals and marks such pending proposals ignored. An accepted label stays in `command_allowlist` until you
remove it; `/habit status` points it out, and `/habit forget <terminal> (plugin approval rule)` (or `/habit undo` if
it was the last accept) removes it.

**Upgrading from 0.1.2:** entries 0.1.2 proposed and you accepted (for example `pytest *`, `git log *`, `cat ./*`)
stay in `command_allowlist` until you remove them. `/habit status` lists them; `/habit forget <entry>` removes one
and `/habit uninstall` removes every entry Habit added.

## Other commands

```text
/habit why          why it asked / pending proposals
/habit status       pending (and whether Habit told you in chat) + accepted
/habit forget <p>   drop accepted entry + allowlist row
/habit undo         undo last accept
/habit uninstall    remove every allowlist entry Habit added + clear pending
```

## Install

```bash
# Requires installed Hermes 0.23.0 or newer.
hermes plugins install https://github.com/scottleimroth/habit --no-enable
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

Then `hermes plugins disable habit`. Allowlist edits take effect on the next approval check in Hermes 0.23 and survive a restart. Removal does not stop an already-running command, revoke a separate session approval, or remove another overlapping allowlist rule.

## Safety / disclosure

- Observer hooks only — if Habit errors, Hermes asks as usual.
- Plugin-escalated approvals (plugin `pre_tool_call` rules) and other non-command prompts are never learned.
- Smart/AI approver decisions are never learned. Hermes 0.23 identifies them with `surface=smart`, `decided_by=aux_llm`, and `choice=smart_approve|smart_deny`; any one marker is enough to ignore the event. Human decisions after escalation still count.
- **Never auto-writes `command_allowlist`.** Human `/habit accept` only.
- Never proposes the never-auto set.
- No telemetry. Local SQLite via `plugin_db`. No secrets from disk.
- Chat message: when it creates a proposal, Habit posts one line into the conversation where you approved, through Hermes's public `ctx.post_message` (Hermes picks the chat; Habit never names one). It runs on a short-lived thread and never retries. Set `notify: false` to turn it off.
- Disclosure: accept and removal persist `command_allowlist` through `hermes_cli.config.load_config` / `save_config`. Hermes 0.23 has no public single-entry revocation helper; its bulk saver merges grants instead of replacing the list. Habit does not write private approval state or override core functions.
- Non-plugin-API dependencies: `gateway.session_context.get_session_env` reads caller identity and surface fields (read-only). Habit classifies unknown surfaces as messaging using its own local allowlist of keyboard/service surfaces. This context reader and config persistence are Hermes implementation helpers, not stable plugin context APIs. Next-check synchronisation was tested on 0.23.0. No underscore-prefixed core helpers are imported.
- Config write errors are reported, with no raw-YAML fallback. Accept stays pending if saving fails. Keep allowlist edits serial: read/modify/save is not a cross-process transaction.

## Develop

```bash
python -m pytest -q                      # needs pytest
python doctor.py && python validate.py   # need PyYAML
python eval/run_eval.py
HERMES_HOME=... hermes plugins doctor habit
HERMES_HOME=... hermes plugins validate .
```

See [installation details](INSTALL.md) and [change history](CHANGELOG.md).
