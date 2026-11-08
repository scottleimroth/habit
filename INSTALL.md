# Install Habit on your own Hermes (for real-world testing)

Requires Hermes **0.23.0 or newer**; this release was tested on 0.23.0.

## Install

```bash
git clone https://github.com/scottleimroth/habit
cd habit
hermes plugins validate .
hermes plugins install "file://$(pwd)" --no-enable
hermes plugins enable habit
hermes plugins doctor habit
```

Set mode in `$HERMES_HOME/config.yaml`:

```yaml
plugins:
  enabled: [habit]
  entries:
    habit:
      settings:
        mode: enforce          # example: enforce + owner lock
        threshold: 2
        owner_ids: ["YOUR_TELEGRAM_OR_DISCORD_USER_ID"]
```

`owner_ids` gates `/habit accept|reject|undo|forget|uninstall` on the messaging gateway.
Local CLI is always allowed. Empty `owner_ids` on gateway → refuse mutating commands (fail closed).
Missing sender id on gateway → refuse. Read-only `/habit why|status|proposals` stay open for everyone.

## Uninstall (clean)

```text
/habit uninstall
```

That removes **every** `command_allowlist` entry Habit tracked, then:

```bash
hermes plugins disable habit
# optional: hermes plugins remove habit
```

## Fail-safe

If Habit errors, hooks swallow the exception and Hermes asks as usual. Habit never auto-answers the approval prompt.

## Gateway owner-lock

Mutating slash commands (`accept` / `reject` / `undo` / `forget` / `uninstall`) require the sender’s id to be in `owner_ids`. Habit reads `HERMES_SESSION_USER_ID` (and `_ALT`) from the gateway session context Hermes already sets for plugin commands. Refusals are logged at WARNING (`habit owner-lock refuse …`). Approval *recording* still separates guest vs owner scopes when hooks expose `user_id` / `is_owner`.

Requires Hermes 0.23.0 or newer. Allowlist edits apply on the next approval check and survive restart. Unidentified chat approvals are ignored; local keyboard approvals still count. See README for core-helper disclosure and removal limits.
