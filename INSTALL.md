# Install Habit on your own Hermes (for real-world testing)

Works on Hermes **0.21.5** and **0.22.2** (same approval hooks + `plugin_db`).

## Install

```bash
# from a clone of this repo
hermes plugins install /path/to/habit
# or: symlink into $HERMES_HOME/plugins/habit
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
