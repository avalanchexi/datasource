# 批次 0:功能有效性审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产出 `src/datasource/` 全模块的四档有效性分级(`runtime_used / imported_only / reachable_not_run / unreachable`),为批次 A 删除提供运行时证据。

**Architecture:** 两条证据线合并——① `ast` 静态 import 可达性(入口=非 legacy 的 `scripts/*.py`);② 离线 coverage 回放 Stage2.5→Stage3→Stage4(夹具复制到一次性 scratch 目录 `data/runs/19990101/`,零网络、零真实数据污染)。审计工具是一次性的,放 `optimization/20260610_refactor_plan/audit/`,不进 `scripts/`。

**Tech Stack:** Python 标准库(`ast`/`json`/`argparse`)+ `coverage` 包(装入 `.venv`,不进 requirements.txt)+ pytest。

**Spec:** `docs/superpowers/specs/2026-06-11-batch0-validity-audit-design.md`

---

## 环境头(必读,适用于本计划所有命令)

- 本仓库在 Windows 磁盘上,但 `.venv` 是 **Linux venv**:所有命令必须在 WSL/Linux shell 中、于仓库根目录(`/mnt/d/cursor/datasource`)执行。若你在 Windows 侧,先 `wsl -e bash -lc '...'` 包装。
- 一切 Python 执行经 `bash run_clean.sh python ...`,**不直跑** `python`(包装器负责 venv、.env、代理清理、PYTHONPATH)。
- **硬约束:** 不得调用任何真实网络 API(Tavily 每日一次,严禁触发);不得读写 `data/runs/2026*`(真实 run 目录,只读复制例外);不得写真实 `data/trend_history/`(只读复制例外);不得手动删除任何 `data/runs/2026*/.run.lock`。
- 本计划只新增文件 + 临时 scratch 目录,**不修改任何现有源码**。若发现必须改现有代码才能推进,停下回报,不要自行修改。
- Commit 规范:Conventional(`test:/feat:/docs:`),按计划内 commit 步骤小步提交,消息末尾不加额外签名。

---

### Task 1: import_graph 的失败测试

**Files:**
- Create: `optimization/20260610_refactor_plan/audit/test_audit_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `optimization/20260610_refactor_plan/audit/test_audit_tools.py`,内容:

```python
"""Tests for the batch-0 one-off audit tools (import_graph / merge_audit)."""

import textwrap

import import_graph


def test_module_name_for_maps_src_paths():
    p = import_graph.SRC / "datasource" / "utils" / "coercion.py"
    assert import_graph.module_name_for(p) == "datasource.utils.coercion"
    init = import_graph.SRC / "datasource" / "utils" / "__init__.py"
    assert import_graph.module_name_for(init) == "datasource.utils"
    outside = import_graph.ROOT / "scripts" / "stage1_data_collector.py"
    assert import_graph.module_name_for(outside) is None


def test_extract_import_candidates_absolute_and_relative():
    src = textwrap.dedent(
        """
        import datasource.manager
        from datasource.utils import coercion
        from . import json_io
        from ..models import base
        """
    )
    cands = import_graph.extract_import_candidates(
        src, module_name="datasource.utils.coercion", is_package=False
    )
    assert "datasource.manager" in cands
    assert "datasource.utils" in cands
    assert "datasource.utils.coercion" in cands
    assert "datasource.utils.json_io" in cands
    assert "datasource.models.base" in cands


def test_reachability_includes_ancestor_packages():
    known = {
        "datasource": None,
        "datasource.utils": None,
        "datasource.utils.coercion": None,
        "datasource.orphan": None,
    }
    edges = {
        "datasource": [],
        "datasource.utils": [],
        "datasource.utils.coercion": [],
        "datasource.orphan": [],
    }
    entries = {"scripts/x.py": ["datasource.utils.coercion"]}
    seen = import_graph.reachable_from_entries(known, edges, entries)
    assert seen == {"datasource", "datasource.utils", "datasource.utils.coercion"}
```

- [ ] **Step 2: 运行确认失败**

```bash
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q
```

Expected: FAIL/ERROR,`ModuleNotFoundError: No module named 'import_graph'`

### Task 2: 实现 import_graph.py

**Files:**
- Create: `optimization/20260610_refactor_plan/audit/import_graph.py`

- [ ] **Step 1: 写实现**

创建 `optimization/20260610_refactor_plan/audit/import_graph.py`,内容:

```python
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
```

- [ ] **Step 2: 运行测试确认通过**

```bash
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q
```

Expected: PASS(3 passed)

- [ ] **Step 3: Commit**

```bash
git add optimization/20260610_refactor_plan/audit/import_graph.py optimization/20260610_refactor_plan/audit/test_audit_tools.py
git commit -m "test: add batch-0 audit import-graph tool with tests"
```

### Task 3: merge_audit 的失败测试

**Files:**
- Modify: `optimization/20260610_refactor_plan/audit/test_audit_tools.py`(文件末尾追加)

- [ ] **Step 1: 追加失败测试**

在 `test_audit_tools.py` 顶部 `import import_graph` 下一行加 `import merge_audit`,文件末尾追加:

```python
def test_classify_tiers():
    assert merge_audit.classify(True, 85.0) == "runtime_used"
    assert merge_audit.classify(True, 20.0) == "runtime_used"
    assert merge_audit.classify(True, 5.0) == "imported_only"
    # --source 模式下 coverage 会给未导入文件记 0%,必须归入静态档
    assert merge_audit.classify(True, 0.0) == "reachable_not_run"
    assert merge_audit.classify(True, None) == "reachable_not_run"
    assert merge_audit.classify(False, None) == "unreachable"
    assert merge_audit.classify(False, 0.0) == "unreachable"


def test_coverage_by_module_maps_file_keys():
    payload = {
        "files": {
            "src/datasource/utils/coercion.py": {
                "summary": {"percent_covered": 73.2}
            },
            "scripts/stage3_pring_analyzer.py": {
                "summary": {"percent_covered": 50.0}
            },
        }
    }
    out = merge_audit.coverage_by_module(payload)
    assert out == {"datasource.utils.coercion": 73.2}
```

- [ ] **Step 2: 运行确认失败**

```bash
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q
```

Expected: ERROR,`ModuleNotFoundError: No module named 'merge_audit'`

### Task 4: 实现 merge_audit.py

**Files:**
- Create: `optimization/20260610_refactor_plan/audit/merge_audit.py`

- [ ] **Step 1: 写实现**

创建 `optimization/20260610_refactor_plan/audit/merge_audit.py`,内容:

```python
"""Batch-0 audit tool: merge static reachability with offline replay coverage.

Inputs : import_reachability.json (import_graph.py) + coverage.json
         (``coverage json`` output of the offline Stage2.5/3/4 replay).
Outputs: used_unused.json (machine-readable, four tiers) and
         AUDIT_RESULTS.md (human-readable report).
"""

import argparse
import json
from pathlib import Path

import import_graph

RUNTIME_USED_THRESHOLD = 20.0

# REFACTOR_PLAN section 1.2 watchlist: modules whose validity was in doubt.
WATCHLIST = [
    "datasource.mcp_adapter",
    "datasource.utils.mcp_tools",
    "datasource.utils.yahoo_finance",
    "datasource.utils.dns_patch",
    "datasource.utils.tushare_patch",
    "datasource.engines.data_engine",
    "datasource.cache.memory_cache",
    "datasource.cache.sqlite_cache",
    "datasource.analyzers.long_term_analyzer",
    "datasource.comparators.international_comparator",
    "datasource.mappers.industry_rotation_mapper",
    "datasource.warnings.systemic_risk_monitor",
    "datasource.generators.report_generator",
    "datasource.generators.simple_report",
]

TIER_ORDER = ["runtime_used", "imported_only", "reachable_not_run", "unreachable"]


def classify(reachable, coverage_pct):
    """Four-tier classification; 0% coverage counts as never imported."""
    if not coverage_pct:
        return "reachable_not_run" if reachable else "unreachable"
    if coverage_pct >= RUNTIME_USED_THRESHOLD:
        return "runtime_used"
    return "imported_only"


def coverage_by_module(coverage_payload):
    out = {}
    for file_key, info in coverage_payload.get("files", {}).items():
        name = import_graph.module_name_for(import_graph.ROOT / file_key)
        if name:
            out[name] = info.get("summary", {}).get("percent_covered")
    return out


def build_rows(reachability_payload, cov_map):
    modules = reachability_payload["modules"]
    entries = reachability_payload["entries"]
    imported_by = {}
    for name, info in modules.items():
        for dep in info["imports"]:
            imported_by.setdefault(dep, []).append(name)
    for entry, targets in entries.items():
        for dep in targets:
            imported_by.setdefault(dep, []).append(entry)
    rows = {}
    for name, info in sorted(modules.items()):
        pct = cov_map.get(name)
        rows[name] = {
            "file": info["file"],
            "tier": classify(info["reachable"], pct),
            "coverage_percent": pct,
            "imported_by": sorted(imported_by.get(name, [])),
        }
    return rows


def render_markdown(rows):
    counts = {tier: 0 for tier in TIER_ORDER}
    for row in rows.values():
        counts[row["tier"]] += 1
    lines = [
        "# 批次 0 功能有效性审计结果",
        "",
        "- 口径:coverage >= %.0f%% 记为 runtime_used(启发式,边缘值人工复核)"
        % RUNTIME_USED_THRESHOLD,
        "- 运行时证据仅来自离线回放 Stage2.5 -> Stage3 -> Stage4 report;"
        "Stage1/Stage2 专属模块最高只能定为 reachable_not_run",
        "- 局限:importlib/动态导入静态不可见",
        "",
        "## 总览",
        "",
        "| 档位 | 模块数 |",
        "|---|---|",
    ]
    for tier in TIER_ORDER:
        lines.append("| %s | %d |" % (tier, counts[tier]))

    lines += ["", "## 1.2 疑似清单定档", "", "| 模块 | 档位 | coverage | 被谁引用 |", "|---|---|---|---|"]
    for name in WATCHLIST:
        row = rows.get(name)
        if row is None:
            lines.append("| %s | (模块不存在) | - | - |" % name)
            continue
        pct = "-" if row["coverage_percent"] is None else "%.1f%%" % row["coverage_percent"]
        importers = ", ".join(row["imported_by"][:4]) or "(无)"
        lines.append("| %s | %s | %s | %s |" % (name, row["tier"], pct, importers))

    for tier in ("unreachable", "imported_only", "reachable_not_run"):
        lines += ["", "## %s 全列表" % tier, ""]
        members = [n for n, r in rows.items() if r["tier"] == tier]
        if not members:
            lines.append("(空)")
        for name in members:
            importers = ", ".join(rows[name]["imported_by"][:3]) or "无引用"
            lines.append("- `%s`(%s)— 引用方: %s" % (name, rows[name]["file"], importers))
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reachability", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()
    reachability = json.loads(Path(args.reachability).read_text(encoding="utf-8"))
    coverage_payload = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
    rows = build_rows(reachability, coverage_by_module(coverage_payload))
    Path(args.output_json).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    Path(args.output_md).write_text(render_markdown(rows), encoding="utf-8")
    summary = {tier: 0 for tier in TIER_ORDER}
    for row in rows.values():
        summary[row["tier"]] += 1
    print(" ".join("%s=%d" % (t, summary[t]) for t in TIER_ORDER))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试确认通过**

```bash
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q
```

Expected: PASS(5 passed)

- [ ] **Step 3: Commit**

```bash
git add optimization/20260610_refactor_plan/audit/merge_audit.py optimization/20260610_refactor_plan/audit/test_audit_tools.py
git commit -m "feat: add batch-0 audit merge/classification tool"
```

### Task 5: 生成静态可达性数据

**Files:**
- Create(生成物): `optimization/20260610_refactor_plan/audit/import_reachability.json`

- [ ] **Step 1: 运行静态分析**

```bash
bash run_clean.sh python optimization/20260610_refactor_plan/audit/import_graph.py \
  --output optimization/20260610_refactor_plan/audit/import_reachability.json
```

Expected: 打印一行 `modules=<N> reachable=<M> unreachable=<K>`,N 约 80–90,K > 0;JSON 文件生成。

- [ ] **Step 2: 抽查合理性**

```bash
bash run_clean.sh python - <<'EOF'
import json
d = json.load(open("optimization/20260610_refactor_plan/audit/import_reachability.json"))
mods = d["modules"]
assert mods["datasource.manager"]["reachable"] is True, "manager must be reachable"
assert mods["datasource.utils.missing_items"]["reachable"] is True
print("spot checks OK; unreachable sample:",
      [m for m, i in mods.items() if not i["reachable"]][:10])
EOF
```

Expected: `spot checks OK; unreachable sample: [...]`(列表中预期出现 mcp 相关模块)

### Task 6: 离线 coverage 回放 Stage2.5 → Stage3 → Stage4

**Files:**
- Create(临时): `data/runs/19990101/`(scratch,Task 8 删除)
- Create(生成物): `optimization/20260610_refactor_plan/audit/coverage.json`

- [ ] **Step 1: 确保 coverage 包可用**

```bash
bash run_clean.sh python -c "import coverage; print(coverage.__version__)" \
  || bash run_clean.sh python -m pip install coverage
```

Expected: 打印版本号(已装)或安装成功后可再次 import。

- [ ] **Step 2: 打隔离时间戳标记 + 准备 scratch 夹具**

```bash
touch /tmp/batch0_audit_marker
mkdir -p data/runs/19990101/trend_history_min
cp data/runs/20260522/market_data_stage2.json data/runs/19990101/
cp data/runs/20260522/websearch_results_manual.json data/runs/19990101/
cp -r data/trend_history/min/. data/runs/19990101/trend_history_min/
ls data/runs/19990101
```

Expected: 列出 `market_data_stage2.json  trend_history_min  websearch_results_manual.json`

- [ ] **Step 3: coverage 回放 Stage2.5(trend_history 隔离)**

```bash
bash run_clean.sh python -m coverage run --source=src/datasource --parallel-mode \
  scripts/stage2_5_injector.py \
  data/runs/19990101/market_data_stage2.json \
  data/runs/19990101/websearch_results_manual.json \
  data/runs/19990101/market_data_complete.json \
  --date 1999-01-01 \
  --gap-monitor-path data/runs/19990101/gap_monitor.json \
  --trend-history-base-dir data/runs/19990101/trend_history_min
```

Expected: exit 0,`data/runs/19990101/market_data_complete.json` 生成。

- [ ] **Step 4: coverage 回放 Stage3**

```bash
bash run_clean.sh python -m coverage run --source=src/datasource --parallel-mode \
  scripts/stage3_pring_analyzer.py \
  --market-data data/runs/19990101/market_data_complete.json \
  --output data/runs/19990101/pring_result.json \
  --gap-monitor data/runs/19990101/gap_monitor.json \
  --allow-estimated --skip-fund-flow-check
```

Expected: exit 0,`pring_result.json` 生成。
**若被 gate 阻断(exit ≠ 0)**:改用原始产物作输入重跑本步——把 `--market-data` 换成 `data/runs/20260522/market_data_complete.json`、`--gap-monitor` 换成 `data/runs/20260522/gap_monitor.json`(只读),输出路径不变。审计要覆盖面,不要产物正确性。

- [ ] **Step 5: coverage 回放 Stage4 report generator**

```bash
bash run_clean.sh python -m coverage run --source=src/datasource --parallel-mode \
  scripts/stage4_report_generator.py \
  --market-data data/runs/19990101/market_data_complete.json \
  --pring-result data/runs/19990101/pring_result.json \
  --gap-monitor data/runs/19990101/gap_monitor.json \
  --output data/runs/19990101/report_audit.md \
  --allow-fund-flow-downgrade
```

Expected: exit 0,`data/runs/19990101/report_audit.md` 生成(Step 4 走了回退分支的话,输入同样替换为 20260522 原件)。

- [ ] **Step 6: 合并 coverage 并导出 JSON**

```bash
bash run_clean.sh python -m coverage combine
bash run_clean.sh python -m coverage json -o optimization/20260610_refactor_plan/audit/coverage.json
bash run_clean.sh python -m coverage report --include="src/datasource/*" | tail -3
```

Expected: `coverage.json` 生成;report 末尾显示总覆盖率(预期 20%–60% 区间,只回放了 2.5/3/4)。

### Task 7: 合并产出审计结论

**Files:**
- Create(生成物): `optimization/20260610_refactor_plan/audit/used_unused.json`、`AUDIT_RESULTS.md`

- [ ] **Step 1: 运行合并**

```bash
bash run_clean.sh python optimization/20260610_refactor_plan/audit/merge_audit.py \
  --reachability optimization/20260610_refactor_plan/audit/import_reachability.json \
  --coverage optimization/20260610_refactor_plan/audit/coverage.json \
  --output-json optimization/20260610_refactor_plan/audit/used_unused.json \
  --output-md optimization/20260610_refactor_plan/audit/AUDIT_RESULTS.md
```

Expected: 打印一行 `runtime_used=<a> imported_only=<b> reachable_not_run=<c> unreachable=<d>`,四数之和 = Task 5 的 modules 总数。

- [ ] **Step 2: 检查报告完整性**

```bash
bash run_clean.sh python - <<'EOF'
import json
rows = json.load(open("optimization/20260610_refactor_plan/audit/used_unused.json"))
watch = [
    "datasource.mcp_adapter", "datasource.utils.mcp_tools",
    "datasource.utils.yahoo_finance", "datasource.analyzers.long_term_analyzer",
    "datasource.comparators.international_comparator",
    "datasource.mappers.industry_rotation_mapper",
    "datasource.warnings.systemic_risk_monitor",
]
for name in watch:
    assert name in rows, "missing watchlist module: " + name
    print(name, "->", rows[name]["tier"])
EOF
```

Expected: 每个 watchlist 模块打印出档位,无 assert 失败。

### Task 8: 隔离断言 + 清理 scratch

- [ ] **Step 1: 断言真实数据未被触碰**

```bash
find data/trend_history data/runs/2026* -newer /tmp/batch0_audit_marker -type f | head -20
```

Expected: **空输出**。若有任何文件列出,这是隔离失败——停止,不要清理现场,原样回报文件列表。

- [ ] **Step 2: 清理 scratch 与 coverage 中间文件**

```bash
rm -rf data/runs/19990101
rm -f .coverage .coverage.*
ls data/runs/ | head
```

Expected: 列表中无 `19990101`。

### Task 9: 提交审计产物

- [ ] **Step 1: 最后跑一遍工具测试**

```bash
bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q
```

Expected: PASS(5 passed)

- [ ] **Step 2: Commit**

```bash
git add optimization/20260610_refactor_plan/audit/
git commit -m "docs: add batch-0 validity audit results (static reachability + offline coverage)"
```

- [ ] **Step 3: 完成回报**

向评审方(Claude Code)回报:四档计数、watchlist 各模块档位、以及 `unreachable` 全列表。批次 A 处置表的修订由评审方基于 `AUDIT_RESULTS.md` 执行,不在本计划范围。
