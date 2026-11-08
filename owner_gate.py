"""Owner-lock for Habit mutating slash commands on the messaging gateway.

Local CLI / TUI / desktop may accept|reject|undo|forget|uninstall freely.
On a messaging surface (Telegram, Discord, …), only configured owner ids
may run those subcommands. Missing sender identity → fail closed (refuse)
and log. Read-only subs (why/status/proposals/help) stay open.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Optional, Sequence

log = logging.getLogger("plugin.habit")

OWNER_LOCKED_SUBS = frozenset({
    "accept", "reject", "undo", "forget", "uninstall",
})

# Surfaces Hermes treats as non-messaging (see gateway.session_context).
_NON_MESSAGING = frozenset({
    "", "api_server", "cli", "codex", "desktop", "gateway", "kanban", "local",
    "msgraph_webhook", "tool", "tui", "webhook",
})


def _cfg(get_config: Callable, key: str, default):
    try:
        value = get_config(key, default)
    except TypeError:
        try:
            cfg = get_config() or {}
            value = cfg.get(key, default)
        except Exception:
            return default
    except Exception:
        return default
    return value


def normalize_owner_ids(raw) -> list[str]:
    """Accept list/tuple/set/comma-string/None → deduped non-empty str ids."""
    if raw is None or raw is False:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            s = str(item).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out
    s = str(raw).strip()
    return [s] if s else []


def configured_owner_ids(get_config: Callable) -> list[str]:
    """Read ``owner_ids`` (preferred) or legacy ``owners`` from Habit settings."""
    ids = normalize_owner_ids(_cfg(get_config, "owner_ids", None))
    if ids:
        return ids
    return normalize_owner_ids(_cfg(get_config, "owners", None))


def _session_env(name: str, default: str = "") -> str:
    try:
        from gateway.session_context import get_session_env
        return str(get_session_env(name, default) or "")
    except Exception:
        import os
        return str(os.environ.get(name, default) or "")


def is_messaging_surface() -> bool:
    """True when this slash invocation is on a human messaging channel."""
    # Read the session fields instead of depending on Hermes's private
    # surface-classification helper. Unknown surfaces remain messaging.
    import os
    platform = (
        os.environ.get("HERMES_PLATFORM")
        or _session_env("HERMES_SESSION_PLATFORM", "")
        or ""
    ).strip().lower()
    source = _session_env("HERMES_SESSION_SOURCE", "").strip().lower()
    for ident in (platform, source):
        if ident and ident not in _NON_MESSAGING:
            return True
    return False


def caller_user_ids() -> tuple[str, str]:
    """Return (user_id, user_id_alt) from the gateway session context / env."""
    uid = _session_env("HERMES_SESSION_USER_ID", "").strip()
    alt = _session_env("HERMES_SESSION_USER_ID_ALT", "").strip()
    return uid, alt


def is_local_cli_surface() -> bool:
    """True for local interactive CLI/TUI/desktop (not a messaging gateway)."""
    return not is_messaging_surface()


def caller_is_owner(owner_ids: Sequence[str]) -> bool:
    if not owner_ids:
        return False
    allowed = {str(x).strip() for x in owner_ids if str(x).strip()}
    uid, alt = caller_user_ids()
    return bool(uid and uid in allowed) or bool(alt and alt in allowed)


def check_owner_lock(sub: str, get_config: Callable) -> Optional[str]:
    """Return a refusal string when *sub* must not run for this caller; else None.

    Policy:
    - Read-only subs: always allowed.
    - Local CLI / TUI / desktop: mutating subs allowed (operator is at the keyboard).
    - Messaging gateway: only ``owner_ids`` may mutate; missing sender id → refuse;
      empty ``owner_ids`` → refuse everyone on the gateway (fail closed until configured).
    """
    sub_l = (sub or "").strip().lower()
    if sub_l not in OWNER_LOCKED_SUBS:
        return None
    if is_local_cli_surface():
        return None

    owners = configured_owner_ids(get_config)
    uid, alt = caller_user_ids()
    platform = _session_env("HERMES_SESSION_PLATFORM", "") or _session_env("HERMES_SESSION_SOURCE", "") or "?"

    if not uid and not alt:
        msg = (
            f"habit: refused `/{sub_l}` — no sender id on messaging surface "
            f"({platform}); owner-lock fail-closed. Configure plugins.entries.habit.settings.owner_ids "
            f"and ensure the gateway exposes HERMES_SESSION_USER_ID."
        )
        log.warning(
            "habit owner-lock refuse sub=%s platform=%s reason=missing_sender owners_configured=%d",
            sub_l, platform, len(owners),
        )
        return msg

    if not owners:
        msg = (
            f"habit: refused `/{sub_l}` — owner_ids not configured; "
            f"gateway mutating commands are locked until the owner id(s) are set."
        )
        log.warning(
            "habit owner-lock refuse sub=%s platform=%s user_id=%s reason=no_owner_ids",
            sub_l, platform, uid or alt,
        )
        return msg

    if caller_is_owner(owners):
        return None

    msg = (
        f"habit: refused `/{sub_l}` — only the configured owner/admin may run this "
        f"(your id is not in owner_ids)."
    )
    log.warning(
        "habit owner-lock refuse sub=%s platform=%s user_id=%s alt=%s reason=not_owner",
        sub_l, platform, uid or "-", alt or "-",
    )
    return msg
