"""Normalize shell command text into a stable fingerprint for habit learning.

Exact-command grain (safer than Hermes Always, which promotes a whole pattern
class). Collapse whitespace; keep flags and paths — different paths = different habits.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def fingerprint(command: str) -> str:
    cmd = (command or "").strip()
    if not cmd:
        return ""
    return _WS.sub(" ", cmd)
