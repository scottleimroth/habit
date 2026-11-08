#!/usr/bin/env python3
"""Validate plugin.yaml against a minimal manifest checklist."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REQUIRED = ("name", "version", "description", "manifest_version", "config_schema", "provides_hooks")


def main() -> int:
    data = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        print("VALIDATE FAIL missing", missing)
        return 1
    if data["name"] != "habit":
        print("VALIDATE FAIL name", data["name"])
        return 1
    hooks = set(data.get("provides_hooks") or [])
    need = {"pre_approval_request", "post_approval_response"}
    if not need <= hooks:
        print("VALIDATE FAIL hooks", hooks)
        return 1
    print("VALIDATE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
