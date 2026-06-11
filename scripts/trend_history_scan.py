"""DEPRECATED path shim (refactor batch B, 2026-06): moved to scripts/tools/trend_history_scan.py.

Forwarder kept one release cycle; removal tracked in
optimization/20260610_refactor_plan/TODOS.md.
"""

import runpy
import sys
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "tools" / "trend_history_scan.py"
print("[DEPRECATED] scripts/trend_history_scan.py -> scripts/tools/trend_history_scan.py; forwarding.", file=sys.stderr)
runpy.run_path(str(_NEW), run_name="__main__")
