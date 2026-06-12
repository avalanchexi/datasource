"""DEPRECATED path shim (refactor batch B, 2026-06): moved to scripts/tools/run_snapshot.py.

Forwarder kept one release cycle; removal tracked in
optimization/20260610_refactor_plan/TODOS.md.
"""

import runpy
import sys
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "tools" / "run_snapshot.py"

if __name__ == "__main__":
    print("[DEPRECATED] scripts/run_snapshot.py -> scripts/tools/run_snapshot.py; forwarding.", file=sys.stderr)
    runpy.run_path(str(_NEW), run_name="__main__")
else:
    globals().update(
        {
            name: value
            for name, value in runpy.run_path(str(_NEW)).items()
            if not (name.startswith("__") and name.endswith("__"))
        }
    )
