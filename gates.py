"""Which approvals are about a shell command Habit may learn from.

Hermes 0.23 fires pre_approval_request / post_approval_response for every human approval gate, not only
dangerous shell commands. The other gates pass a synthetic label or other text as `command`:

- plugin pre_tool_call rules (tools/approval.py request_tool_approval): pattern_key `plugin_rule:<rule>`,
  command `<tool> (plugin approval rule)`
- computer_use: `cua:<action>:<mode>`, command `computer_use: ...`
- SSH config writes: `ssh_config_write`, command `<write to ...>`
- protected instruction files: `protected_instruction_file`
- execute_code scripts: `execute_code` (the command is Python source)
- MCP elicitation: `mcp_elicitation` (the command is the server's message)
- ACP editor diffs: `editor-<id>`, command `Edit <path>`

None of these is a terminal command that command_allowlist can match, and each is meant to be seen by a person
every time. Habit ignores them completely: nothing is recorded, counted, proposed or posted.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

_NON_COMMAND_KEYS = frozenset({
    "execute_code", "ssh_config_write", "protected_instruction_file", "mcp_elicitation",
})
_NON_COMMAND_PREFIXES = ("plugin_rule:", "cua:", "editor-")
PLUGIN_LABEL = re.compile(r"^<[^>]+> \(plugin approval rule\)$")


def _key_reason(key: str) -> Optional[str]:
    key = (key or "").strip()
    if key.startswith("plugin_rule:"):
        return "plugin approval rule"
    if key in _NON_COMMAND_KEYS or key.startswith(_NON_COMMAND_PREFIXES):
        return f"not a shell-command approval ({key.split(':')[0]})"
    return None


def not_a_command(pattern_key: str = "", pattern_keys: Iterable[str] = (), command: str = "") -> Optional[str]:
    """Why this approval is not one Habit may learn from, or None for a dangerous shell command."""
    if isinstance(pattern_keys, str):
        pattern_keys = [pattern_keys]
    for key in [pattern_key, *(pattern_keys or [])]:
        why = _key_reason(str(key or ""))
        if why:
            return why
    cmd = " ".join(str(command or "").split())
    if PLUGIN_LABEL.match(cmd):
        return "plugin approval rule"
    if cmd.startswith("<") or cmd.startswith("computer_use: "):
        return "synthetic approval label, not a command"
    return None
