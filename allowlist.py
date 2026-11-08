"""Persist allowlist changes through Hermes's public config functions.

Hermes 0.23 synchronises command_allowlist on its next approval check.
Habit never imports or mutates Hermes's in-memory approval sets.
"""

from __future__ import annotations

from typing import Callable, Optional


def add_exact_command(command: str, *, writer: Optional[Callable[[str], None]] = None) -> str:
    cmd = (command or "").strip()
    if not cmd:
        return "empty command — skipped"
    if writer is not None:
        writer(cmd)
        return f"wrote via injected writer: {cmd[:80]}"

    return _merge_config_yaml(cmd)


def _merge_config_yaml(command: str) -> str:
    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    cur = cfg.get("command_allowlist") or []
    if not isinstance(cur, list):
        raise ValueError("command_allowlist must be a list")
    if command in cur:
        return f"already on disk: {command[:80]}"
    cfg["command_allowlist"] = [*cur, command]
    save_config(cfg)
    return f"config.yaml allowlist += {command[:80]}; effective on next approval check"


def remove_habit_entries(entries: list[str]) -> int:
    wanted = {e for e in entries if e}
    return _remove_from_config_yaml(wanted) if wanted else 0


def _remove_from_config_yaml(wanted: set[str]) -> int:
    from hermes_cli.config import load_config, save_config

    cfg = load_config()
    entries = cfg.get("command_allowlist") or []
    if not isinstance(entries, list):
        raise ValueError("command_allowlist must be a list")
    new = [e for e in entries if e not in wanted]
    removed = len(entries) - len(new)
    if removed:
        cfg["command_allowlist"] = new
        save_config(cfg)
    return removed
