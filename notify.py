"""Tell the user, in the chat where they approved, that Habit has a new proposal.

Delivery uses only the public `PluginContext.post_message(text)` (Hermes 0.23): it posts into the
conversation bound to the calling hook, so Habit never chooses a chat. It runs on a short-lived thread
that inherits the hook's context, so a slow or stuck gateway never holds up the approval itself. A
failed post is logged and dropped; the proposal stays listed in /habit proposals and /habit status.
Posting never accepts anything: only a person typing /habit accept writes command_allowlist.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from typing import Any, Callable, Optional

from .patterns import exact_entry

log = logging.getLogger("plugin.habit")

_MAX_CMD = 100


def _shown(text: str) -> str:
    one_line = " ".join(str(text or "").split()).replace("`", "'")
    return one_line if len(one_line) <= _MAX_CMD else one_line[: _MAX_CMD - 1] + "…"


def proposal_message(*, proposal_id: int, command: str, entry: str, approve_count: int) -> str:
    """The one line a user sees when a proposal is created."""
    times = "1 time" if approve_count == 1 else f"{approve_count} times"
    if entry == exact_entry(command):
        what = "for exactly this command"
    else:
        scope = "service" if entry.startswith("docker compose ") else "container"
        what = f"for `{_shown(entry)}` (any {scope}, any options)"
    return (f"Habit: you've approved `{_shown(command)}` {times}. "
            f"Reply /habit accept {proposal_id} to stop being asked {what}, "
            f"or /habit reject {proposal_id} to keep asking.")


class Announcer:
    """Posts each proposal once. Never raises; never blocks the caller when `background` is true."""

    def __init__(self, poster: Optional[Callable[[str], Any]], *, background: bool = True):
        self._poster = poster
        self._background = background
        self._lock = threading.Lock()
        self._seen: set[int] = set()
        self.outcomes: dict[int, str] = {}

    def announce(self, proposal_id: int, text: str) -> Optional[threading.Thread]:
        with self._lock:
            if proposal_id in self._seen:
                return None
            self._seen.add(proposal_id)
        if self._poster is None:
            self._record(proposal_id, "not posted: this Hermes has no post_message")
            log.info("habit proposal #%d not posted (no post_message); see /habit proposals", proposal_id)
            return None
        if not self._background:
            self._post(proposal_id, text)
            return None
        ctx = contextvars.copy_context()  # keeps the hook's session binding, which post_message reads
        thread = threading.Thread(target=ctx.run, args=(self._post, proposal_id, text),
                                  name=f"habit-notify-{proposal_id}", daemon=True)
        thread.start()
        return thread

    def _record(self, proposal_id: int, outcome: str) -> None:
        with self._lock:
            self.outcomes[proposal_id] = outcome

    def _post(self, proposal_id: int, text: str) -> None:
        try:
            handle = self._poster(text)
            ok = bool(getattr(handle, "ok", False))
            err = str(getattr(handle, "error", "") or "")
            result = getattr(handle, "result", None)
            if ok and isinstance(result, dict) and result.get("delivered") is False:
                ok, err = False, "not_delivered (no one is viewing this chat)"
        except Exception as exc:  # post_message never raises; a stand-in context still might
            ok, err = False, f"{type(exc).__name__}: {exc}"
        if ok:
            self._record(proposal_id, "posted in chat")
            log.info("habit proposal #%d posted in chat", proposal_id)
        elif err == "timeout":
            # Hermes 0.23 gave up waiting after 30 s but keeps delivering; the message may still arrive.
            self._record(proposal_id, "post still pending (slow gateway)")
            log.warning("habit proposal #%d post still pending after Hermes's 30 s wait (slow gateway); "
                        "it may still arrive and is in /habit proposals", proposal_id)
        else:
            self._record(proposal_id, f"not posted: {err or 'unknown error'}")
            log.warning("habit proposal #%d could not be posted in chat (%s); it is still in /habit proposals",
                        proposal_id, err or "unknown error")
