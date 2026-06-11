"""DEPRECATED path shim (refactor batch B, 2026-06): moved to scripts/tools/stage2_health_check.py.

Forwarder kept one release cycle; removal tracked in
optimization/20260610_refactor_plan/TODOS.md.
"""

import runpy
import sys
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "tools" / "stage2_health_check.py"
print("[DEPRECATED] scripts/stage2_health_check.py -> scripts/tools/stage2_health_check.py; forwarding.", file=sys.stderr)
runpy.run_path(str(_NEW), run_name="__main__")
