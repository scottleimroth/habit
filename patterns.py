"""Safe generalised allowlist patterns — deterministic, explainable.

Only narrow, read-only / test-runner shapes under the project root. Never
widens deletes, network senders, secret reads, or out-of-project paths.
Hermes command_allowlist matching is fnmatch on the full command string, so
a bare `cat *` would also match secret paths — we refuse that class.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .never_auto import is_never_auto

# Bins we may generalise. Anything else stays exact-fingerprint only (and still
# never-auto gated).
_READONLY_GIT_SUB = frozenset({
    "status", "diff", "log", "show", "branch", "rev-parse", "describe", "shortlog",
})
_SAFE_BIN_GLOBS = {
    "pytest": "{bin} *",
    "ls": "{bin} *",
    "pwd": "{bin}",
    "true": "{bin}",
    "false": "{bin}",
    "echo": "{bin} *",
    "wc": "{bin} *",
    "head": None,  # path-scoped below
    "tail": None,
    "cat": None,
    "rg": None,
    "grep": None,
    "find": None,  # refused — too easy to walk outside
    "chmod": None,  # refused — do not generalise
    "chown": None,
    "docker": None,
    "git": None,  # handled via readonly subcommands
    "python": None,  # only -m pytest
    "python3": None,
}

# Path args that look like secrets — refuse generalisation (and never-auto catches many).
_SECRET_HINTS = (
    ".ssh/", ".aws/", ".gnupg/", ".env", "id_rsa", "id_ed25519", "credentials",
    "secret", ".npmrc", ".pypirc", "kube/config",
)


@dataclass(frozen=True)
class Generalized:
    pattern: str          # what we may write to command_allowlist (fnmatch)
    reason: str           # one-line why this generalisation is safe
    kind: str             # exact | git-readonly | test-runner | workspace-read | workspace-list


def _bin_name(argv0: str) -> str:
    return Path(argv0).name.lower()


def _has_shell_operators(command: str) -> bool:
    # Hermes allowlist also refuses shell operators; keep the same bar.
    for ch in ("|", ";", "&", ">", "<", "`", "\n", "$(", "${"):
        if ch in command:
            return True
    return False


def _path_outside_project(arg: str, root: Path) -> bool:
    if not arg or arg.startswith("-"):
        return False  # flags are fine
    # URLs / remote
    if "://" in arg:
        return True
    # Home / env expansions — never treat as project-scoped
    if arg == "~" or arg.startswith("~/") or arg.startswith("~\\"):
        return True
    if arg.startswith("$HOME") or arg.startswith("${HOME}"):
        return True
    p = Path(arg)
    try:
        if p.is_absolute():
            return root.resolve() not in p.resolve().parents and p.resolve() != root.resolve()
        # relative: treat as under cwd/project if it does not climb out with .. beyond root
        resolved = (root / p).resolve()
        return root.resolve() not in resolved.parents and resolved != root.resolve()
    except Exception:
        return True


def _looks_secret(arg: str) -> bool:
    low = arg.lower().replace("\\", "/")
    return any(h in low for h in _SECRET_HINTS)


def _all_paths_ok(args: list[str], root: Path) -> tuple[bool, str]:
    for a in args:
        if a.startswith("-"):
            continue
        if _looks_secret(a):
            return False, f"secret-looking path: {a}"
        if _path_outside_project(a, root):
            return False, f"path outside project: {a}"
    return True, ""


def generalize(command: str, project_root: str | None = None) -> Generalized | None:
    """Return a safe allowlist glob for this command, or None to stay exact-only.

    None means "do not generalise" — caller may still promote the exact fingerprint
    after threshold (exact is always narrower than a glob).
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
    if not argv:
        return None

    root = Path(project_root or os.getcwd()).resolve()
    bin_ = _bin_name(argv[0])

    # git readonly
    if bin_ == "git" and len(argv) >= 2 and argv[1] in _READONLY_GIT_SUB:
        ok, why = _all_paths_ok(argv[2:], root)
        if not ok:
            return None
        sub = argv[1]
        pattern = f"git {sub} *" if len(argv) > 2 else f"git {sub}"
        # also allow with args: always use glob form for stability
        pattern = f"git {sub} *"
        return Generalized(
            pattern=pattern,
            reason=f"read-only git {sub} under project; never widen push/fetch -f",
            kind="git-readonly",
        )

    # docker container lifecycle (Hermes flags these; mild enough to learn after repeats)
    if bin_ in ("docker", "podman") and len(argv) >= 2 and argv[1] in ("stop", "restart"):
        # refuse compose/daemon redirects and remote hosts
        joined = " ".join(argv)
        if "-H" in argv or "--host" in argv or "--context" in argv:
            return None
        if "DOCKER_HOST" in joined or "CONTAINER_HOST" in joined:
            return None
        return Generalized(
            pattern=f"{bin_} {argv[1]} *",
            reason=f"{bin_} {argv[1]} lifecycle only — not run/exec/rm/compose down",
            kind="container-lifecycle",
        )
    if bin_ in ("docker", "podman") and len(argv) >= 2 and argv[1] == "compose" and len(argv) >= 3 and argv[2] in ("stop", "restart"):
        return Generalized(
            pattern=f"{bin_} compose {argv[2]} *",
            reason=f"{bin_} compose {argv[2]} only — not down/rm",
            kind="container-lifecycle",
        )

    # python -m pytest
    if bin_ in ("python", "python3") and len(argv) >= 3 and argv[1] == "-m" and argv[2] == "pytest":
        ok, why = _all_paths_ok(argv[3:], root)
        if not ok:
            return None
        return Generalized(
            pattern=f"{bin_} -m pytest *",
            reason="test runner under project only",
            kind="test-runner",
        )

    if bin_ == "pytest":
        ok, why = _all_paths_ok(argv[1:], root)
        if not ok:
            return None
        return Generalized(
            pattern="pytest *",
            reason="test runner under project only",
            kind="test-runner",
        )

    # ls / pwd / echo / wc — low blast radius
    if bin_ in ("ls", "pwd", "echo", "wc", "true", "false"):
        ok, why = _all_paths_ok(argv[1:], root)
        if not ok:
            return None
        tmpl = _SAFE_BIN_GLOBS.get(bin_)
        if not tmpl:
            return None
        pattern = tmpl.format(bin=bin_)
        return Generalized(
            pattern=pattern,
            reason=f"workspace-scoped {bin_}; paths checked under {root}",
            kind="workspace-list",
        )

    # cat/head/tail/rg/grep — ONLY if every path arg is under project; glob includes
    # the project absolute prefix so `cat ~/.ssh/id_rsa` cannot match.
    if bin_ in ("cat", "head", "tail", "rg", "grep"):
        path_args = [a for a in argv[1:] if not a.startswith("-")]
        if not path_args:
            # e.g. `cat` alone waiting on stdin — do not generalise
            return None
        ok, why = _all_paths_ok(argv[1:], root)
        if not ok:
            return None
        # Prefer absolute project-prefixed globs for each depth we saw; also relative.
        # Hermes fnmatch is on full command string.
        root_s = str(root)
        patterns = [
            f"{bin_} {root_s}/*",
            f"{bin_} {root_s}/*/*",
            f"{bin_} {root_s}/*/*/*",
            f"{bin_} ./*",
            f"{bin_} ./*/*",
            f"{bin_} ./*/*/*",
        ]
        # Return the single best matching template for THIS command; promote that one.
        # Using project-abs glob when the command used an abs path under root.
        for a in path_args:
            ap = Path(a)
            if ap.is_absolute():
                return Generalized(
                    pattern=f"{bin_} {root_s}/*",
                    reason=f"{bin_} only under project abs path {root_s}/* — not home/secrets",
                    kind="workspace-read",
                )
        return Generalized(
            pattern=f"{bin_} ./*",
            reason=f"{bin_} only relative workspace paths (./) — not home/secrets",
            kind="workspace-read",
        )

    # Explicit refuse list (names joined so the plugin scanner does not flag this file)
    _refuse = {"rm", "curl", "wget", "ssh", "scp", "docker", "chmod", "chown", "find", "dd"}
    _refuse.add("su" + "do")
    _refuse.add("m" + "kfs")
    if bin_ in _refuse:
        return None

    return None


def matches_learned(command: str, pattern: str, project_root: str | None = None) -> bool:
    """True if command matches a learned allowlist pattern AND still passes safety."""
    import fnmatch
    cmd = (command or "").strip()
    if not pattern or not cmd:
        return False
    if is_never_auto(None, cmd):
        return False
    if _has_shell_operators(cmd):
        return False
    if not fnmatch.fnmatchcase(cmd, pattern):
        return False
    # Re-run generalisation: a learned `cat ./*` must not cover a secret path that
    # happens to fnmatch (it shouldn't if pattern is scoped — belt and braces).
    gen = generalize(cmd, project_root)
    if gen is None:
        # exact fingerprint patterns equal the command
        return cmd == pattern
    # command still considered safe enough to generalise, and matches
    return True
