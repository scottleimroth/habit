"""Pure policy: record / propose / refuse — never auto-write allowlist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .never_auto import is_never_auto, never_auto_reason


APPROVE_CHOICES = frozenset({"once", "session", "always"})


@dataclass
class PolicyResult:
    action: str  # ignore | record | propose | refuse
    reason: str


def after_decision(
    *,
    mode: str,
    command: str,
    fingerprint: str,
    pattern_key: str,
    choice: str,
    approve_count_after: int,
    deny_count: int,
    threshold: int,
    already_promoted: bool,
    already_proposed: bool = False,
    generalized: Optional[str] = None,
    generalize_reason: Optional[str] = None,
) -> PolicyResult:
    """Decide what Habit should do after a human approval/deny.

    In enforce mode, crossing the threshold yields **propose** (a pending
    suggestion). Writing command_allowlist happens only later via an explicit
    `/habit accept` from a person — never from this path (catalog rule 12).
    Observe mode only records.
    """
    if mode == "off":
        return PolicyResult("ignore", "mode off")
    if not fingerprint:
        return PolicyResult("ignore", "empty command")

    if is_never_auto(pattern_key, command):
        return PolicyResult(
            "refuse",
            never_auto_reason(pattern_key, command) or "never-auto",
        )

    if choice == "deny":
        return PolicyResult("record", "user denied — will not propose")

    if choice not in APPROVE_CHOICES:
        return PolicyResult("record", f"unhandled choice {choice!r}")

    if deny_count > 0:
        return PolicyResult("record", "prior deny for this fingerprint/pattern — will not propose")

    if already_promoted:
        return PolicyResult("record", "already accepted into allowlist")

    if already_proposed:
        return PolicyResult("record", "already proposed — waiting for /habit accept")

    target = generalized or fingerprint
    label = f"pattern {generalized}" if generalized else f"exact {fingerprint[:60]}"

    if mode != "enforce":
        extra = f"; would propose {label}" + (f" ({generalize_reason})" if generalize_reason else "")
        return PolicyResult(
            "record",
            f"observe: {approve_count_after} approve(s); need {threshold} in enforce{extra}",
        )

    if approve_count_after < threshold:
        return PolicyResult(
            "record",
            f"{approve_count_after}/{threshold} approvals toward {label} — not yet",
        )

    why = generalize_reason or "exact command fingerprint"
    return PolicyResult(
        "propose",
        f"approved {approve_count_after}×; propose {label} because {why} — "
        f"run /habit accept to write command_allowlist (human confirm required)",
    )


def ask_reason(
    *,
    fingerprint: str,
    pattern_key: str,
    command: str,
    approve_count: int,
    deny_count: int,
    promoted: bool,
    learned_pattern: Optional[str] = None,
    pending_proposal: Optional[str] = None,
) -> str:
    if is_never_auto(pattern_key, command):
        return never_auto_reason(pattern_key, command) or "never-auto"
    if learned_pattern:
        return f"matches learned pattern {learned_pattern!r} — Hermes should skip if allowlist applied"
    if pending_proposal:
        return f"proposed {pending_proposal!r} — waiting for /habit accept (not yet on allowlist)"
    if promoted:
        return f"already learned ({fingerprint[:60]}); Hermes should skip the prompt"
    if deny_count:
        return f"you denied this {deny_count}× earlier — asking again is safer"
    if approve_count:
        return f"new or not yet learned ({approve_count} prior approve(s))"
    return "first time seeing this command — not yet a habit"
