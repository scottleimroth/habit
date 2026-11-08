"""Write/remove Habit entries on Hermes command_allowlist.

Updates the in-memory permanent set via approve_permanent (do NOT nest the
approval module lock — it is a non-reentrant threading.Lock) and persists to
HERMES_HOME/config.yaml via hermes_cli.config.save_config when possible.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional


def _hermes_home() -> Path:
    raw = os.environ.get("HERMES_HOME") or ""
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


def add_exact_command(command: str, *, writer: Optional[Callable[[str], None]] = None) -> str:
    cmd = (command or "").strip()
    if not cmd:
        return "empty command — skipped"
    if writer is not None:
        writer(cmd)
        return f"wrote via injected writer: {cmd[:80]}"

    mem = _memory_add(cmd)
    disk = _merge_config_yaml(cmd)
    return f"{mem}; {disk}"


def _memory_add(command: str) -> str:
    try:
        from tools.approval import approve_permanent

        # Must NOT wrap in tools.approval._lock — approve_permanent already locks,
        # and that lock is non-reentrant.
        approve_permanent(command)
        return "memory ok"
    except Exception as e:
        return f"memory skipped ({type(e).__name__})"


def _merge_config_yaml(command: str) -> str:
    home = _hermes_home()
    path = home / "config.yaml"
    # Hermes's own config saver first: it needs no PyYAML, which the official image does not ship.
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cur = cfg.get("command_allowlist") or []
        if not isinstance(cur, list):
            cur = [cur] if cur else []
        if command in cur:
            return f"already on disk: {command[:80]}"
        cur.append(command)
        cfg["command_allowlist"] = cur
        save_config(cfg)
        return f"config.yaml allowlist += {command[:80]}"
    except Exception:
        try:
            import yaml
        except ImportError:
            return f"cannot write allowlist (Hermes config saver failed, no PyYAML): {path}"
        data = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
        entries = data.get("command_allowlist") or []
        if not isinstance(entries, list):
            entries = [entries] if entries else []
        if command in entries:
            return f"already on disk: {command[:80]}"
        entries.append(command)
        data["command_allowlist"] = entries
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        return f"raw yaml allowlist += {command[:80]}"


def remove_habit_entries(entries: list[str]) -> int:
    wanted = {e for e in entries if e}
    if not wanted:
        return 0
    removed_mem = 0
    try:
        from tools.approval import _permanent_set, _lock

        with _lock:
            governing = _permanent_set()
            for e in list(governing):
                if e in wanted:
                    governing.discard(e)
                    removed_mem += 1
    except Exception:
        pass
    removed_disk = _remove_from_config_yaml(wanted)
    return max(removed_mem, removed_disk)


def _remove_from_config_yaml(wanted: set[str]) -> int:
    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        entries = cfg.get("command_allowlist") or []
        if not isinstance(entries, list):
            return 0
        new = [e for e in entries if e not in wanted]
        removed = len(entries) - len(new)
        if removed:
            cfg["command_allowlist"] = new
            save_config(cfg)
        return removed
    except Exception:
        home = _hermes_home()
        path = home / "config.yaml"
        if not path.exists():
            return 0
        try:
            import yaml
            data = yaml.safe_load(path.read_text()) or {}
            entries = data.get("command_allowlist") or []
            if not isinstance(entries, list):
                return 0
            new = [e for e in entries if e not in wanted]
            removed = len(entries) - len(new)
            if removed:
                data["command_allowlist"] = new
                path.write_text(yaml.safe_dump(data, sort_keys=False))
            return removed
        except Exception:
            return 0
