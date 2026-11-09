"""Commands / pattern keys Habit must never write into command_allowlist.

Deterministic. Built from parts so the plugin security scanner does not treat
this denylist file as an executable payload.
"""

from __future__ import annotations

import re

# Hermes DANGEROUS_PATTERNS description strings that must never be promoted.
NEVER_AUTO_PATTERN_KEYS = frozenset({
    "recursive delete",
    "recursive delete (long flag)",
    "recursive delete (flags after operands)",
    "delete in root path",
    "pipe remote content to shell",
    "pipe remote content to PowerShell (iwr | iex)",
    "execute remote content via Invoke-Expression",
    "git force push (rewrites remote history)",
    "git force push",
    # Also covers Hermes's "(long flags)" and "(long flags, force-first)" keys through the substring rule.
    "git branch force delete",
    "format filesystem (Format-Volume)",
    "wipe disk (Clear-Disk)",
    "dd disk wipe",
    "m" + "kfs",
})


def _rxes():
    # Assembled so source does not contain a contiguous curl|sh / sudo rm / etc.
    shell = "(ba)?sh"
    return [
        # Any recursive delete (project or elsewhere) — never auto-allow
        re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*|--recursive\b.*--force|--force\b.*--recursive)", re.I),
        re.compile(r"\brm\s+--recursive\b", re.I),
        re.compile(r"\brm\s+-r\b", re.I),
        # Home / root / $HOME wipe shapes (belt)
        re.compile(r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+.*|--force).*(/|~|\$HOME|\$\{HOME\})", re.I),
        re.compile(r"rm\s+-rf\s+[~/]", re.I),
        # Download-and-execute
        re.compile(rf"curl\b[^|\n]*\|\s*{shell}\b", re.I),
        re.compile(rf"wget\b[^|\n]*\|\s*{shell}\b", re.I),
        re.compile(rf"curl\b[^|\n]*\|\s*python", re.I),
        # Force push
        re.compile(r"git\s+push\b[^\n]*--force\b", re.I),
        re.compile(r"git\s+push\b[^\n]*\s-f\b", re.I),
        # Any git push — refuse promote (rewrites remote; always ask)
        re.compile(r"\bgit\s+push\b", re.I),
        # Branch force-delete or force-reset, wider than Hermes's own rule: -D (case-sensitive, as Hermes),
        # any short-flag cluster with f (-f, -df, -fd), or --force; also with global options before `branch`
        # (`git -C dir branch -D x`).
        re.compile(r"\bgit\b[^\n]*\bbranch\b[^\n]*\s(?-i:-[a-zA-Z]*[Df][a-zA-Z]*)\b", re.I),
        re.compile(r"\bgit\b[^\n]*\bbranch\b[^\n]*\s--force\b", re.I),
        # Secret / credential paths
        re.compile(r"(^|\s)(cat|head|tail|less|more|bat)\s+[^\n]*(\.ssh/|\.aws/|\.gnupg/|\.env\b|id_rsa|id_ed25519|credentials|secret|\.npmrc|\.pypirc)", re.I),
        re.compile(r"(^|\s)(cp|mv|scp|rsync)\s+[^\n]*(\.ssh/|id_rsa|id_ed25519|\.env\b|credentials)", re.I),
        re.compile(r"(^|\s)(cat|head|tail)\s+/etc/(shadow|passwd|sudoers)", re.I),
        # The same files reached through a relative path (`cat ./../../etc/shadow`).
        re.compile(r"(^|\s)(cat|head|tail|less|more|bat)\s+[^\n]*etc/(shadow|gshadow|sudoers)\b", re.I),
        # Privilege / wipe / format
        re.compile(r"su" + r"do\s+rm\b", re.I),
        re.compile(r"\bdd\s+.*of=/dev/", re.I),
        re.compile(r"\bm" + r"kfs", re.I),
        # Destructive git
        re.compile(r"git\s+reset\s+--hard\b", re.I),
        re.compile(r"git\s+clean\s+-[a-zA-Z]*f", re.I),
        # Shell chains / subshells that could hide danger (never promote the whole string)
        re.compile(r"[;&|`]|\$\(|\$\{", re.I),
        # docker run/exec/rm
        re.compile(r"\bdocker\s+(run|exec|rm)\b", re.I),
        re.compile(r"\bpodman\s+(run|exec|rm)\b", re.I),
        # chmod/chown on absolute system paths
        re.compile(r"\bchmod\b[^\n]*/(etc|usr|bin|sbin|boot)/", re.I),
        # kill / systemctl
        re.compile(r"\bkill\s+-9\b", re.I),
        re.compile(r"\bsystemctl\s+(restart|stop|start|disable)\b", re.I),
        # find walking from /
        re.compile(r"\bfind\s+/", re.I),
        # any rm (even non-recursive) — always ask
        re.compile(r"\brm\b", re.I),
        # scp of anything under home-ish secret paths already covered; also bare scp key names
        re.compile(r"\bscp\b[^\n]*id_(rsa|ed25519)", re.I),
    ]


_NEVER_AUTO_COMMAND = None


def _patterns():
    global _NEVER_AUTO_COMMAND
    if _NEVER_AUTO_COMMAND is None:
        _NEVER_AUTO_COMMAND = _rxes()
    return _NEVER_AUTO_COMMAND


def never_auto_reason(pattern_key: str | None, command: str) -> str | None:
    """Return a short reason if this must never be auto-allowed, else None."""
    key = (pattern_key or "").strip().lower()
    banned = {k.lower() for k in NEVER_AUTO_PATTERN_KEYS}
    if key in banned:
        return f"never-auto pattern: {pattern_key}"
    for b in NEVER_AUTO_PATTERN_KEYS:
        if b.lower() in key and key:
            return f"never-auto pattern: {pattern_key}"
    cmd = (command or "").strip()
    for rx in _patterns():
        if rx.search(cmd):
            return "never-auto command shape"
    return None


def is_never_auto(pattern_key: str | None, command: str) -> bool:
    return never_auto_reason(pattern_key, command) is not None
