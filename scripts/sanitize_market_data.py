"""DEPRECATED path shim (refactor batch B, 2026-06): moved to scripts/tools/market_data_sanitize.py.

Forwarder kept one release cycle; removal tracked in
optimization/20260610_refactor_plan/TODOS.md.
"""

import runpy
import sys
from pathlib import Path

_NEW = Path(__file__).resolve().parent / "tools" / "market_data_sanitize.py"
print("[DEPRECATED] scripts/sanitize_market_data.py -> scripts/tools/market_data_sanitize.py; forwarding.", file=sys.stderr)
runpy.run_path(str(_NEW), run_name="__main__")
