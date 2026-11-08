#!/usr/bin/env python3
"""Local doctor: import + unit tests. No Hermes home writes beyond this check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    errors = []
    try:
        if "habit" not in sys.modules:      # load this folder as the package `habit`, whatever the clone folder is called
            import importlib.util
            spec = importlib.util.spec_from_file_location("habit", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
            mod = importlib.util.module_from_spec(spec)
            sys.modules["habit"] = mod
            spec.loader.exec_module(mod)
        import habit  # noqa: F401
        from habit.never_auto import is_never_auto
        from habit.normalize import fingerprint
        assert fingerprint("a  b") == "a b"
        assert is_never_auto(None, "rm -rf ~")
    except Exception as e:
        errors.append(f"import/self-check: {e}")

    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        errors.append("pytest failed")

    # schema presence
    import yaml
    schema = yaml.safe_load((ROOT / "plugin.yaml").read_text())
    modes = schema["config_schema"]["mode"]["choices"]
    if modes != ["off", "observe", "enforce"] and set(modes) != {"off", "observe", "enforce"}:
        # allow either list form
        if not all(m in modes for m in ("off", "observe", "enforce")):
            errors.append(f"bad mode choices: {modes}")

    if errors:
        print("DOCTOR FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("DOCTOR OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
