"""Habit: learn approve/deny habits; promote safe patterns; explain with /habit why."""

from __future__ import annotations

import logging

from .runtime import Habit

PLUGIN_NAME = "habit"
log = logging.getLogger("plugin.habit")


def _open_store():
    from plugins.plugin_storage import plugin_db

    from .store import HabitStore

    return HabitStore(plugin_db(PLUGIN_NAME))


def register(ctx):
    try:
        habit = Habit(config=ctx.get_config, store_factory=_open_store)
        ctx.register_hook("pre_approval_request", habit.on_pre_approval_request)
        ctx.register_hook("post_approval_response", habit.on_post_approval_response)
        ctx.register_command(
            "habit",
            habit.command,
            description="Habit: why / proposals / accept|reject (human confirm) / undo",
            args_hint="[why|status|proposals|accept <id>|reject <id>|forget|undo|uninstall|help]",
        )
        return habit
    except Exception:
        log.exception("habit register failed — plugin inert; Hermes approvals unchanged")
        return None
