"""Habit runtime: approval observer hooks + /habit slash command.

Fail-safe: every public entrypoint catches exceptions and returns None / an
error string so Hermes keeps asking as usual when Habit breaks.

Catalog rule 12: Habit never auto-writes command_allowlist. Crossing the
threshold only creates a **proposal**. A person must run `/habit accept`
(CLI or gateway / Telegram) before any allowlist entry is written.
Unattended paths (cron / YOLO / oneshot with no human) never call accept.
On the messaging gateway, accept/reject/undo/forget/uninstall are OWNER-LOCKED
(plugins.entries.habit.settings.owner_ids); local CLI is exempt. Missing sender
id on a messaging surface fails closed.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .allowlist import add_exact_command, remove_habit_entries
from .normalize import fingerprint as make_fp
from .patterns import generalize, matches_learned
from .policy import after_decision, ask_reason
from .store import Decision, HabitStore
from .never_auto import is_never_auto, never_auto_reason
from .owner_gate import check_owner_lock, is_messaging_surface

log = logging.getLogger("plugin.habit")


def _cfg(get_config: Callable, key: str, default):
    """Hermes PluginContext.get_config(key, default) — not a full-dict getter."""
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
    if key == "mode" and value is False:  # YAML 1.1 reads unquoted `off` as bool false
        return "off"
    return value


def _event_command(event: dict) -> str:
    command = event.get("command") or event.get("args") or ""
    if isinstance(command, dict):
        command = command.get("command") or ""
    return str(command)


class Habit:
    def __init__(
        self,
        config: Callable[[], dict],
        store_factory: Callable[[], HabitStore],
        allowlist_writer: Optional[Callable[[str], None]] = None,
        allowlist_remover: Optional[Callable[[list[str]], int]] = None,
        project_root: Optional[str] = None,
    ):
        self._config = config
        self._store_factory = store_factory
        self._store: Optional[HabitStore] = None
        self._allowlist_writer = allowlist_writer
        self._allowlist_remover = allowlist_remover
        self._project_root = project_root
        self._last_ask: dict[str, Any] = {}

    def _db(self) -> HabitStore:
        if self._store is None:
            self._store = self._store_factory()
        return self._store

    def _root(self) -> str:
        import os
        return self._project_root or os.environ.get("HABIT_PROJECT_ROOT") or os.getcwd()

    def on_pre_approval_request(self, **event) -> None:
        try:
            if _cfg(self._config, "mode", "observe") == "off":
                return
            command = _event_command(event)
            pattern_key = str(event.get("pattern_key") or event.get("description") or "")
            fp = make_fp(command)
            store = self._db()
            learned = store.find_matching_pattern(command, self._root())
            pending = store.find_pending_for_command(command, self._root())
            reason = ask_reason(
                fingerprint=fp,
                pattern_key=pattern_key,
                command=command,
                approve_count=store.approve_count(fp),
                deny_count=store.deny_count(fp),
                promoted=store.is_promoted(fp) or bool(learned),
                learned_pattern=learned,
                pending_proposal=pending,
            )
            self._last_ask = {
                "command": command,
                "fingerprint": fp,
                "pattern_key": pattern_key,
                "reason": reason,
                "learned_pattern": learned,
                "pending_proposal": pending,
            }
        except Exception:
            log.exception("habit pre_approval_request failed — Hermes will ask as usual")

    def on_post_approval_response(self, **event) -> None:
        try:
            mode = _cfg(self._config, "mode", "observe")
            if mode == "off":
                return
            command = _event_command(event)
            pattern_key = str(event.get("pattern_key") or event.get("description") or "")
            choice = str(event.get("choice") or "").lower().strip()
            # Hermes 0.23 approval_smart emits all three markers. Treat any
            # one as sufficient, so partial payloads cannot become human votes.
            provenance = {str(event.get(key) or "").strip().lower()
                          for key in ("decided_by", "source", "surface")}
            if choice.startswith("smart_") or provenance & {"aux_llm", "smart"}:
                return
            decided_by = str(event.get("decided_by") or event.get("source") or "")
            user_id = str(event.get("user_id") or event.get("approver_id") or "").strip()
            # Local keyboard approvals have no sender id; chat must identify it.
            if not user_id and is_messaging_surface():
                log.warning("habit ignored messaging approval without approver identity")
                return
            is_owner = event.get("is_owner")
            scope = "owner"
            if user_id and is_owner is False:
                scope = f"guest:{user_id}"
            elif user_id and is_owner is True:
                scope = f"owner:{user_id}"

            fp = make_fp(command)
            if not fp or not choice:
                return

            store = self._db()
            na = is_never_auto(pattern_key, command)
            gen = None if na else generalize(command, self._root())
            store.record_decision(Decision(
                command=command,
                fingerprint=fp,
                pattern_key=pattern_key,
                choice=choice,
                decided_by=decided_by,
                never_auto=na,
                reason=never_auto_reason(pattern_key, command) or "",
                session_id=str(event.get("session_id") or event.get("session_key") or ""),
                scope=scope,
                generalized=gen.pattern if gen else "",
            ))

            threshold = int(_cfg(self._config, "threshold", 3) or 3)
            count_key = gen.pattern if gen else fp
            approve_n = store.pattern_approve_count(count_key, scope=scope) if gen else store.approve_count(fp)
            deny_n = store.pattern_deny_count(count_key, scope=scope) if gen else store.deny_count(fp)
            already = store.is_pattern_promoted(count_key) if gen else store.is_promoted(fp)
            entry = (gen.pattern if gen else command)
            already_proposed = store.is_entry_proposed(entry, scope=scope)

            result = after_decision(
                mode=mode,
                command=command,
                fingerprint=fp,
                pattern_key=pattern_key,
                choice=choice,
                approve_count_after=approve_n,
                deny_count=deny_n,
                threshold=threshold,
                already_promoted=already,
                already_proposed=already_proposed,
                generalized=gen.pattern if gen else None,
                generalize_reason=gen.reason if gen else None,
            )
            # Propose only — never write allowlist here (rule 12).
            if result.action == "propose":
                store.add_proposal(
                    fingerprint=fp,
                    command=command,
                    pattern_key=pattern_key,
                    proposed_entry=entry,
                    reason=result.reason,
                    approve_count=approve_n,
                    scope=scope,
                )
        except Exception:
            log.exception("habit post_approval_response failed — Hermes will ask as usual")

    def _accept_one(self, store: HabitStore, prop: dict) -> str:
        entry = prop["proposed_entry"]
        cmd = prop["command"]
        if is_never_auto(prop.get("pattern_key") or "", cmd) or is_never_auto(None, entry):
            store.set_proposal_status(prop["id"], "rejected")
            return f"#{prop['id']} refused (never-auto): {entry}"
        status = add_exact_command(entry, writer=self._allowlist_writer)
        store.mark_promoted(
            fingerprint=prop["fingerprint"],
            command=cmd,
            allowlist_entry=entry,
            approve_count=int(prop.get("approve_count") or 0),
            reason=f"accepted proposal #{prop['id']} | {status}",
            scope=prop.get("scope") or "owner",
            pattern=entry,
        )
        store.set_proposal_status(prop["id"], "accepted")
        return f"#{prop['id']} accepted → allowlist {entry!r} ({status})"

    def command(self, args: str = "") -> str:
        try:
            parts = (args or "").strip().split()
            sub = (parts[0].lower() if parts else "why")
            refused = check_owner_lock(sub, self._config)
            if refused:
                return refused
            store = self._db()
            if sub in ("why", "ask", "allow"):
                ev = store.last_event()
                ask = self._last_ask
                lines = ["habit — why"]
                if ask:
                    lines.append(f"last ask: {ask.get('command', '')[:100]}")
                    lines.append(f"  reason: {ask.get('reason', '')}")
                    if ask.get("learned_pattern"):
                        lines.append(f"  learned pattern: {ask['learned_pattern']}")
                    if ask.get("pending_proposal"):
                        lines.append(f"  pending proposal: {ask['pending_proposal']} — /habit accept")
                    lines.append(f"  pattern_key: {ask.get('pattern_key') or '(none)'}")
                if ev:
                    lines.append(
                        f"last event: {ev['kind']} choice={ev.get('choice')!s} "
                        f"cmd={ev.get('command', '')[:80]}"
                    )
                    if ev.get("detail"):
                        lines.append(f"  detail: {ev['detail']}")
                    if ev.get("pattern"):
                        lines.append(f"  pattern: {ev['pattern']}")
                pending = store.list_proposals("pending")
                if pending:
                    lines.append(f"pending proposals ({len(pending)}):")
                    for p in pending[:10]:
                        lines.append(f"  #{p['id']} {p['proposed_entry'][:80]}")
                    lines.append("confirm with: /habit accept <id> | /habit accept all")
                if not ask and not ev and not pending:
                    lines.append("no approval traffic recorded yet")
                return "\n".join(lines)
            if sub in ("status", "list"):
                mode = _cfg(self._config, "mode", "observe")
                th = _cfg(self._config, "threshold", 3)
                promos = store.list_promotions()
                pending = store.list_proposals("pending")
                lines = [f"habit mode={mode} threshold={th}"]
                lines.append(f"pending proposals ({len(pending)}):")
                if not pending:
                    lines.append("  (none)")
                for p in pending:
                    lines.append(
                        f"  #{p['id']} [{p['approve_count']}×] {p['proposed_entry'][:100]} "
                        f"(from {p['command'][:50]})"
                    )
                lines.append(f"accepted on allowlist ({len(promos)}):")
                if not promos:
                    lines.append("  (none yet)")
                for p in promos:
                    lines.append(
                        f"  [{p['approve_count']}×] {p['allowlist_entry'][:100]} "
                        f"(from {p['command'][:60]})"
                    )
                return "\n".join(lines)
            if sub == "proposals":
                pending = store.list_proposals("pending")
                if not pending:
                    return "habit: no pending proposals"
                lines = ["habit pending proposals:"]
                for p in pending:
                    lines.append(f"  #{p['id']} {p['proposed_entry']} — {p['reason'][:80]}")
                lines.append(" /habit accept <id> | /habit accept all | /habit reject <id>")
                return "\n".join(lines)
            if sub == "accept":
                rest = " ".join(parts[1:]).strip().lower()
                if not rest:
                    return "usage: /habit accept <id>|all   (human confirm — writes command_allowlist)"
                if rest == "all":
                    pending = store.list_proposals("pending")
                    if not pending:
                        return "habit: nothing to accept"
                    return "habit accept all:\n" + "\n".join(
                        self._accept_one(store, p) for p in pending
                    )
                try:
                    pid = int(rest)
                except ValueError:
                    return "usage: /habit accept <id>|all"
                prop = store.get_proposal(pid)
                if not prop:
                    return f"habit: no proposal #{pid}"
                if prop["status"] != "pending":
                    return f"habit: proposal #{pid} is {prop['status']}, not pending"
                return "habit: " + self._accept_one(store, prop)
            if sub == "reject":
                rest = " ".join(parts[1:]).strip().lower()
                if not rest:
                    return "usage: /habit reject <id>|all"
                if rest == "all":
                    pending = store.list_proposals("pending")
                    if not pending:
                        return "habit: nothing to reject"
                    outs = []
                    for p in pending:
                        store.set_proposal_status(p["id"], "rejected")
                        outs.append(f"#{p['id']} rejected: {p['proposed_entry']}")
                    return "habit reject all:\n" + "\n".join(outs)
                try:
                    pid = int(rest)
                except ValueError:
                    return "usage: /habit reject <id>|all"
                prop = store.get_proposal(pid)
                if not prop:
                    return f"habit: no proposal #{pid}"
                if prop["status"] != "pending":
                    return f"habit: proposal #{pid} is {prop['status']}"
                store.set_proposal_status(pid, "rejected")
                return f"habit: rejected #{pid} {prop['proposed_entry']}"
            if sub == "forget":
                target = " ".join(parts[1:]).strip()
                if not target:
                    return "usage: habit forget <pattern-or-fingerprint>"
                removed = store.forget(target)
                n = 0
                if self._allowlist_remover and removed:
                    n = self._allowlist_remover(removed)
                elif removed:
                    n = remove_habit_entries(removed)
                return f"forgot {len(removed)} entr(y/ies); allowlist removed={n}: {removed}; effective on next approval check"
            if sub == "undo":
                undone = store.undo_last_promotion()
                if not undone:
                    return "nothing to undo"
                n = 0
                if self._allowlist_remover:
                    n = self._allowlist_remover([undone])
                else:
                    n = remove_habit_entries([undone])
                return f"undo: removed {undone!r} (allowlist removed={n}); effective on next approval check"
            if sub == "uninstall":
                entries = store.habit_allowlist_entries()
                if self._allowlist_remover:
                    n = self._allowlist_remover(entries)
                else:
                    n = remove_habit_entries(entries)
                store.clear_promotions()
                for p in store.list_proposals("pending"):
                    store.set_proposal_status(p["id"], "rejected")
                return (
                    f"habit uninstall: removed {n} allowlist entr(y/ies) Habit added (effective on next approval check); "
                    f"pending proposals cleared. Disable with: hermes plugins disable habit"
                )
            if sub == "help":
                return (
                    "habit why | status | proposals | accept <id>|all | reject <id>|all | "
                    "forget <pattern> | undo | uninstall | help\n"
                    "Note: allowlist writes only on accept (human confirm). "
                    "Gateway: accept/reject/undo/forget/uninstall require owner_ids. "
                    "Local CLI is exempt. Read-only: why/status/proposals."
                )
            return f"unknown subcommand {sub!r} — try: habit help"
        except Exception as e:
            log.exception("habit command failed")
            return f"habit error (Hermes approvals unchanged): {e}"
