#!/usr/bin/env python3
"""Accuracy eval for Habit: dangerous commands must never promote; safe ones should.

Usage (from plugin root):
  python eval/run_eval.py
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "habit" not in sys.modules:          # load this folder as the package `habit`, whatever the clone folder is called
    import importlib.util
    _spec = importlib.util.spec_from_file_location("habit", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["habit"] = _mod
    _spec.loader.exec_module(_mod)

from habit.never_auto import is_never_auto  # noqa: E402
from habit.normalize import fingerprint  # noqa: E402
from habit.patterns import generalize, matches_learned  # noqa: E402
from habit.policy import after_decision  # noqa: E402


def load_samples(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def would_propose(command: str, project_root: str, threshold: int = 3) -> tuple[str, str, str | None]:
    """Simulate threshold approvals in enforce — must propose, never auto-write."""
    fp = fingerprint(command)
    gen = generalize(command, project_root)
    generalized = gen.pattern if gen else None
    greason = gen.reason if gen else None
    pr = after_decision(
        mode="enforce",
        command=command,
        fingerprint=fp,
        pattern_key="",
        choice="once",
        approve_count_after=threshold,
        deny_count=0,
        threshold=threshold,
        already_promoted=False,
        already_proposed=False,
        generalized=generalized,
        generalize_reason=greason,
    )
    # Dangerous if propose OR promote (promote should not exist anymore)
    target = None
    if pr.action in ("propose", "promote"):
        target = generalized or fp
    return pr.action, pr.reason, target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=ROOT / "eval" / "samples.jsonl")
    ap.add_argument("--threshold", type=int, default=3)
    args = ap.parse_args()

    samples = load_samples(args.samples)
    dangerous = [s for s in samples if s["label"] == "must_never_learn"]
    safe = [s for s in samples if s["label"] == "safe_to_learn"]
    exact = [s for s in samples if s["label"] == "safe_to_learn_exact"]

    dang_auto = []
    dang_ok = []
    safe_learned = []
    safe_miss = []
    exact_learned = []
    exact_miss = []
    promoted_patterns: list[tuple[str, str]] = []

    for s in dangerous:
        action, reason, target = would_propose(s["command"], s.get("project_root"), args.threshold)
        if action in ("propose", "promote"):
            dang_auto.append({**s, "action": action, "reason": reason, "target": target})
        else:
            dang_ok.append(s["id"])

    for s in safe:
        action, reason, target = would_propose(s["command"], s.get("project_root"), args.threshold)
        if action == "propose":
            safe_learned.append({**s, "target": target, "reason": reason})
            if target:
                promoted_patterns.append((s["id"], target))
        else:
            safe_miss.append({**s, "action": action, "reason": reason})

    for s in exact:
        action, reason, target = would_propose(s["command"], s.get("project_root"), args.threshold)
        gen = generalize(s["command"], s.get("project_root"))
        if action == "propose":
            exact_learned.append({**s, "target": target, "got_glob": gen is not None})
            if target:
                promoted_patterns.append((s["id"], target))
        else:
            exact_miss.append({**s, "action": action, "reason": reason})

    cross = []
    for sid, pattern in promoted_patterns:
        for d in dangerous:
            cmd = d["command"]
            if matches_learned(cmd, pattern, d.get("project_root")):
                cross.append({
                    "from_safe": sid, "pattern": pattern,
                    "dangerous_id": d["id"], "dangerous_cmd": cmd, "via": "matches_learned",
                })
            elif fnmatch.fnmatchcase(cmd, pattern) and not is_never_auto(None, cmd):
                cross.append({
                    "from_safe": sid, "pattern": pattern,
                    "dangerous_id": d["id"], "dangerous_cmd": cmd, "via": "raw_fnmatch",
                })

    print("=== Habit accuracy eval ===")
    print(f"samples: {len(samples)}  (dangerous={len(dangerous)} safe={len(safe)} exact={len(exact)})")
    print()
    print(f"dangerous proposed/auto-approved: {len(dang_auto)}  [target 0]")
    for row in dang_auto:
        print(f"  FAIL {row['id']}: {row['command']!r} -> {row['target']!r} ({row['reason']})")
    print(f"dangerous correctly refused: {len(dang_ok)}/{len(dangerous)}")
    print()
    print(f"safe proposed: {len(safe_learned)}/{len(safe)}")
    for row in safe_miss:
        print(f"  MISS {row['id']}: {row['command']!r} -> {row['action']} ({row['reason']})")
    print(f"exact-only proposed: {len(exact_learned)}/{len(exact)}")
    for row in exact_miss:
        print(f"  MISS {row['id']}: {row['command']!r} -> {row['action']} ({row['reason']})")
    print()
    print(f"cross-contamination (safe pattern matches dangerous): {len(cross)}  [target 0]")
    for c in cross[:20]:
        print(f"  CROSS {c}")

    report = {
        "n_samples": len(samples),
        "dangerous_total": len(dangerous),
        "dangerous_proposed": len(dang_auto),
        "dangerous_refused": len(dang_ok),
        "safe_total": len(safe),
        "safe_learned": len(safe_learned),
        "safe_miss": len(safe_miss),
        "exact_total": len(exact),
        "exact_learned": len(exact_learned),
        "cross_contamination": len(cross),
        "dangerous_auto_ids": [r["id"] for r in dang_auto],
        "safe_miss_ids": [r["id"] for r in safe_miss],
        "exact_miss_ids": [r["id"] for r in exact_miss],
        "cross": cross,
    }
    out = ROOT / "eval" / "last_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print()
    print(f"wrote {out}")

    ok = (
        len(dang_auto) == 0
        and len(cross) == 0
        and len(safe_miss) == 0
        and len(exact_miss) == 0
    )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
