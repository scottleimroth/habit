"""Allowlist entries Habit may propose — deterministic, explainable, and no wider than their label.

How Hermes reads an entry (tools/approval_floors.py, Hermes 0.23): a command containing a shell operator never
matches; otherwise an entry matches when it equals the command, or when it contains `*`, `?` or `[` and
`fnmatch.fnmatchcase(command, entry)` is true. So `*` matches `/`, spaces and any further arguments: `cat ./*`
also matches `cat ./a ~/.ssh/id_rsa`, `git log *` also matches `git log --output=<file>` (writes a file) and
`pytest *` also matches `pytest --basetemp=<dir>` (deletes that directory's contents).

Rule: Habit proposes a glob only where every command the glob can match is what its label says. Today that is
the container lifecycle family Hermes itself asks about (`docker stop|restart *`, `docker compose stop|restart *`).
Everything else is proposed as the exact approved command, escaped so Hermes reads it literally (see
`exact_entry`). Hermes 0.23 only asks for approval on its dangerous-command list, so commands such as cat, ls,
pytest or `git status` never reach Habit's hooks in the first place.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .never_auto import is_never_auto


@dataclass(frozen=True)
class Generalized:
    pattern: str          # what we may write to command_allowlist (fnmatch glob)
    reason: str           # one line saying exactly what the glob allows
    kind: str             # container-lifecycle (the only glob family)


_GLOB_CHARS = re.compile(r"[*?\[]")


def exact_entry(command: str) -> str:
    """The allowlist entry that matches exactly this command and nothing else.

    A command containing `*`, `?` or `[` would be a glob to Hermes, so each of those characters is wrapped in
    brackets (`[*]`, `[?]`, `[[]`), in one pass so an escape is never escaped again. Hermes then takes its
    fnmatch path, where a bracketed character matches only itself. A command without them is returned as is.
    """
    cmd = (command or "").strip()
    return _GLOB_CHARS.sub(lambda m: "[" + m.group() + "]", cmd)


def _bin_name(argv0: str) -> str:
    return Path(argv0).name.lower()


def _has_shell_operators(command: str) -> bool:
    # Hermes refuses allowlist matches for commands with shell operators; keep at least the same bar.
    for ch in ("|", ";", "&", ">", "<", "`", "\n", "$(", "${"):
        if ch in command:
            return True
    return False


def _redirects_daemon(argv: list[str]) -> bool:
    for a in argv[1:]:
        if a in ("-H", "--host", "-c", "--context") or a.startswith(("--host=", "-H=", "--context=", "-c=")):
            return True
    joined = " ".join(argv).upper()
    return "DOCKER_HOST" in joined or "CONTAINER_HOST" in joined or "DOCKER_CONTEXT" in joined


def generalize(command: str, project_root: str | None = None) -> Generalized | None:
    """Return a glob for this command, or None to propose the exact command (see `exact_entry`).

    `project_root` is accepted for compatibility; no glob depends on paths any more.
    """
    cmd = (command or "").strip()
    if not cmd or _has_shell_operators(cmd):
        return None
    if is_never_auto(None, cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if len(argv) < 2 or _bin_name(argv[0]) != "docker" or _redirects_daemon(argv):
        return None

    # Hermes asks before `docker stop|restart` and `docker compose stop|restart` (container lifecycle).
    if argv[1] in ("stop", "restart"):
        return Generalized(
            pattern=f"docker {argv[1]} *",
            reason=(f"docker {argv[1]} of any container or containers, with any {argv[1]} options; "
                    "not run, exec, rm, kill or a remote daemon"),
            kind="container-lifecycle",
        )
    if argv[1] == "compose" and len(argv) >= 3 and argv[2] in ("stop", "restart"):
        return Generalized(
            pattern=f"docker compose {argv[2]} *",
            reason=(f"docker compose {argv[2]} of any service or services, with any {argv[2]} options; "
                    "not down, rm, kill or up"),
            kind="container-lifecycle",
        )
    return None


def matches_learned(command: str, pattern: str, project_root: str | None = None) -> bool:
    """True if command matches a learned allowlist entry AND still passes safety."""
    cmd = (command or "").strip()
    if not pattern or not cmd:
        return False
    if is_never_auto(None, cmd) or _has_shell_operators(cmd):
        return False
    gen = generalize(cmd, project_root)
    if gen is not None and gen.pattern == pattern:
        return True
    # Exact entries: the escaped form Habit writes, or a pre-0.1.3 entry stored verbatim.
    return pattern == exact_entry(cmd) or pattern == cmd


def hermes_would_match(command: str, entry: str) -> bool:
    """Hermes 0.23's own allowlist test, reproduced for tests and the eval (tools/approval_floors.py).

    Shell-operator refusal is approximated with Habit's stricter `_has_shell_operators`.
    """
    command = (command or "").strip()
    entry = (entry or "").strip()
    if not command or not entry or _has_shell_operators(command):
        return False
    return command == entry or (any(ch in entry for ch in "*?[") and fnmatch.fnmatchcase(command, entry))
