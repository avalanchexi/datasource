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

    lines += [
        "",
        "## 1.2 疑似清单定档",
        "",
        "| 模块 | 档位 | coverage | 被谁引用 |",
        "|---|---|---|---|",
    ]
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
