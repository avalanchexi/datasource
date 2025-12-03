import sys
from pathlib import Path

# Ensure repo root and src are on sys.path for imports
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (ROOT, SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
