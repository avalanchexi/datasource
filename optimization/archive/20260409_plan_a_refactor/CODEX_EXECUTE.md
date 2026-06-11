# Plan A 精准修复 — Codex 执行指令

**项目根目录**: `/mnt/d/cursor/datasource`  
**日期**: 2026-04-09  
**目标**: 执行方案A的剩余步骤（步骤4-7），前3步已完成。

---

## 已完成（不要重复执行）

- ✅ `inject_websearch_data_test.py` 已重命名为 `scripts/stage2_5_injector.py`
- ✅ `CLAUDE.md` / `AGENTS.md` 中的引用已更新
- ✅ `scripts/stage4_report_generator.py` 已添加 `--gap-monitor` 参数

---

## 步骤4: 修复 Stage4 gap_monitor 路径逻辑

**文件**: `scripts/stage4_report_generator.py`

**问题**: 第55行硬编码 `reports/gap_monitor.json`（无日期版本），而流水线实际生成 `reports/gap_monitor_YYYYMMDD.json`，导致静默跳过 gap 校验。

**当前代码** (`main()` 函数内，约第54-61行):
```python
    # gap_monitor 校验
    gap_path = Path("reports/gap_monitor.json")
    if gap_path.exists():
        gap = json.load(gap_path.open("r", encoding="utf-8"))
        pending = gap.get("pending_tasks", [])
        manual = gap.get("manual_required", [])
        if pending or manual:
            raise RuntimeError(f"gap_monitor 未清空，pending={pending}, manual_required={manual}，请先补齐再生成报告。")
```

**替换为**:
```python
    # gap_monitor 校验（支持带日期版本，自动从 market_data 路径推断）
    if args.gap_monitor:
        gap_path: Optional[Path] = Path(args.gap_monitor)
    else:
        # 从 market_data 路径推断日期前缀
        # e.g. data/20260408_market_data_complete.json → reports/gap_monitor_20260408.json
        stem = market_path.stem  # e.g. "20260408_market_data_complete"
        date_prefix = stem.split("_")[0] if "_" in stem else ""
        if date_prefix and date_prefix.isdigit() and len(date_prefix) == 8:
            gap_path = Path(f"reports/gap_monitor_{date_prefix}.json")
            if not gap_path.exists():
                gap_path = Path("reports/gap_monitor.json")  # 兼容旧路径
        else:
            gap_path = Path("reports/gap_monitor.json")

    if gap_path.exists():
        gap = json.load(gap_path.open("r", encoding="utf-8"))
        pending = gap.get("pending_tasks", [])
        manual = gap.get("manual_required", [])
        if pending or manual:
            raise RuntimeError(
                f"gap_monitor 未清空（{gap_path}），"
                f"pending={pending}, manual_required={manual}，请先补齐再生成报告。"
            )
    else:
        print(f"[WARN] gap_monitor 文件未找到（查找: {gap_path}），跳过 gap 校验")
```

注意：需要在文件顶部的 import 里确认 `Optional` 已导入（从 `typing` 导入），或使用 `Optional[Path]` 的 Python 3.9+ 写法 `Path | None`。检查文件头部已有的 import，按已有风格补充。

---

## 步骤5: 修复 inject 脚本 is_estimated 跳过边缘情况

**文件**: `scripts/stage2_5_injector.py`（原 inject_websearch_data_test.py）

**问题**: 当某个指标已有值（`is_estimated=True`），inject 脚本会跳过注入，但**不调用 `_remove_top_missing`**，导致顶层 `missing_items` list 残留该 key，Stage3 policy gate 被误阻断。

用户必须手动用 `python3 -c` 来修复。

**定位方法**: 搜索文件中各 `_apply_*` 函数，找到类似以下模式的"跳过"分支：

```python
# 在 _apply_macro_entry, _apply_monetary_entry 等函数中
if not _has_valid_value(existing.get("current_value")) or existing.get("is_stale"):
    pass  # 继续注入
else:
    logger.info(f"跳过 {key}（已有值）")
    continue  # ← 这里是问题所在
```

**修复方案**: 在每个跳过分支里，如果已有有效值（哪怕 is_estimated=True），仍然清理顶层 missing_items：

```python
    else:
        logger.info(f"跳过 {key}（已有值，is_estimated={existing.get('is_estimated')}）")
        # 即使跳过注入，如果已有有效值则清理顶层 missing_items
        if _has_valid_value(existing.get("current_value")):
            _remove_top_missing(market_data, key)
        continue
```

**需要修复的函数**（重点检查，可能有其他）:
1. `_apply_macro_entry` — 搜索 `is_estimated` 相关的跳过逻辑
2. `_apply_monetary_entry` — 同上
3. `_cleanup_monetary_aliases` — 检查别名映射时的跳过

**验证**: 修复后，运行以下测试确认没有回归：
```bash
cd /mnt/d/cursor/datasource
source .venv/bin/activate
PYTHONPATH=./src python -m pytest tests/test_websearch_injector.py -q
```

---

## 步骤6: 移动非主流水线脚本到 scripts/legacy/

**操作**:
```bash
cd /mnt/d/cursor/datasource
mkdir -p scripts/legacy

# 以下脚本明确为旧版/废弃，移到 legacy
git mv scripts/ai_execution_steps.py scripts/legacy/
git mv scripts/background_scan_120d.py scripts/legacy/
git mv scripts/background_scan_unified.py scripts/legacy/
git mv scripts/enhanced_market_scan.py scripts/legacy/
git mv scripts/fill_market_data_from_yahoo.py scripts/legacy/
git mv scripts/market_scanner_unified.py scripts/legacy/
git mv scripts/mcp_data_enhancer.py scripts/legacy/
git mv scripts/run_background_scan_pipeline.py scripts/legacy/
```

**如果存在也移走**:
```bash
[ -f scripts/stage2_mcp_enhancer.py ] && git mv scripts/stage2_mcp_enhancer.py scripts/legacy/
```

**保留在 scripts/**（工具类，可能仍有用）:
- `backfill_fund_flow_series.py`
- `backfill_trend_history_event_dates.py`
- `trend_history_backfill.py`
- `trend_history_scan.py`
- `run_snapshot.py`
- `gap_monitor_to_manual_template.py`
- `fund_flow_analysis.py`
- `recap_consistency_check.py`
- `sanitize_market_data.py`
- `index_trend_analysis.py`

---

## 步骤7: 追踪未追踪的测试文件

```bash
cd /mnt/d/cursor/datasource
git add tests/test_fix_estimated_verified.py tests/test_stage4_docs.py
```

---

## 最终验证

```bash
cd /mnt/d/cursor/datasource
source .venv/bin/activate && source .env

# 1. 确认重命名
ls scripts/stage2_5_injector.py

# 2. 语法检查
PYTHONPATH=./src python -m py_compile scripts/stage4_report_generator.py
PYTHONPATH=./src python -m py_compile scripts/stage2_5_injector.py

# 3. 运行相关测试
PYTHONPATH=./src python -m pytest tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_policy_rules.py -q

# 4. 确认 scripts/ 清洁度
ls scripts/*.py | wc -l  # 目标: ≤ 22（原32，移走约10个）
ls scripts/legacy/ | wc -l  # 目标: ≥ 8

# 5. 确认 Stage4 帮助文本更新
PYTHONPATH=./src python scripts/stage4_report_generator.py --help | grep gap-monitor
```

---

## 不要做的事

- ❌ 不要重命名 inject_websearch_data_test.py（已完成）
- ❌ 不要修改 Stage2 逻辑（每日限额）
- ❌ 不要修改 Pring 分析算法
- ❌ 不要创建 run_daily_pipeline.py（这是方案B，本次范围外）
- ❌ 不要移动 `trend_history_*.py` 和 `run_snapshot.py`（它们是工具类脚本）

---

## 提交信息模板

```
fix: rename inject script, fix stage4 gap_monitor path, and sync missing_items on skip

- Rename inject_websearch_data_test.py → scripts/stage2_5_injector.py
- Fix stage4_report_generator.py to resolve dated gap_monitor_{YYYYMMDD}.json path
- Fix _apply_macro_entry/_apply_monetary_entry to call _remove_top_missing on skip
- Move legacy/unused scripts to scripts/legacy/
- Track previously untracked test files
```
