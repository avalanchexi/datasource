"""Batch-0 audit tool: static import reachability for datasource modules.

One-off tool for optimization/20260610_refactor_plan (REFACTOR_PLAN section 3).
Parses src/datasource/** and scripts/*.py with ast, then computes which
datasource modules are reachable from non-legacy script entry points.
Known blind spot: importlib/__import__ dynamic imports are not detected.
"""

import argparse
import ast
import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
PKG_ROOT = SRC / "datasource"
SCRIPTS_DIR = ROOT / "scripts"


def module_name_for(path: Path) -> Optional[str]:
    """Dotted module name for a .py file under src/, else None."""
    try:
        rel = Path(path).resolve().relative_to(SRC.resolve())
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _package_of(module_name: str, is_package: bool):
    parts = module_name.split(".")
    return parts if is_package else parts[:-1]


def extract_import_candidates(source, module_name=None, is_package=False):
    """Set of candidate dotted names imported by ``source``.

    For ``from X import y`` both ``X`` and ``X.y`` are emitted; callers
    filter candidates against the known module set.
    """
    tree = ast.parse(source)
    candidates = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                candidates.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module.split(".") if node.module else []
            else:
                if not module_name:
                    continue
                pkg = _package_of(module_name, is_package)
                cut = len(pkg) - (node.level - 1)
                if cut < 0:
                    continue
                base = pkg[:cut] + (node.module.split(".") if node.module else [])
            if base:
                candidates.add(".".join(base))
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidates.add(".".join(base + [alias.name]))
    return candidates


def _filter_known(candidates, known):
    """Map each candidate to its longest known module prefix."""
    out = set()
    for cand in candidates:
        parts = cand.split(".")
        for end in range(len(parts), 0, -1):
            prefix = ".".join(parts[:end])
            if prefix in known:
                out.add(prefix)
                break
    return sorted(out)


def build_graph():
    known = {}
    for path in sorted(PKG_ROOT.rglob("*.py")):
        name = module_name_for(path)
        if name:
            known[name] = path
    edges = {}
    for name, path in known.items():
        is_pkg = path.name == "__init__.py"
        cands = extract_import_candidates(
            path.read_text(encoding="utf-8"), name, is_pkg
        )
        edges[name] = _filter_known(cands, known)
    entries = {}
    for path in sorted(SCRIPTS_DIR.glob("*.py")):  # top-level only: excludes scripts/legacy/
        if path.name == "__init__.py":
            continue
        cands = extract_import_candidates(path.read_text(encoding="utf-8"))
        entries["scripts/" + path.name] = _filter_known(cands, known)
    return known, edges, entries


def _with_ancestors(name):
    parts = name.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)}


def reachable_from_entries(known, edges, entries):
    """BFS from entry imports; importing a.b.c also executes a and a.b."""
    seen = set()
    stack = []
    for targets in entries.values():
        stack.extend(targets)
    while stack:
        mod = stack.pop()
        for m in _with_ancestors(mod):
            if m in known and m not in seen:
                seen.add(m)
                stack.extend(edges.get(m, []))
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="output JSON path")
    args = parser.parse_args()
    known, edges, entries = build_graph()
    reachable = reachable_from_entries(known, edges, entries)
    payload = {
        "entries": {k: v for k, v in sorted(entries.items())},
        "modules": {
            name: {
                "file": str(known[name].relative_to(ROOT)).replace("\\", "/"),
                "reachable": name in reachable,
                "imports": edges.get(name, []),
            }
            for name in sorted(known)
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    total = len(known)
    print(
        "modules=%d reachable=%d unreachable=%d"
        % (total, len(reachable), total - len(reachable))
    )


if __name__ == "__main__":
    main()
