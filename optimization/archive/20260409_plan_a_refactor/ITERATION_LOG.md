# 本期迭代记录 — 2026-04-09

## 迭代编号
`20260409_plan_a_refactor`

## 背景与目标

对市场背景扫描流水线进行精准修复，消除最高优先级的操作痛点。不改动架构，不动 Pring 分析逻辑，不换数据源。

本期迭代对应"方案A：精准修复"。

---

## 变更清单

### 已完成（2026-04-09）

| # | 变更 | 文件 | 状态 |
|---|------|------|------|
| 1 | 重命名 inject 脚本 | `inject_websearch_data_test.py` → `scripts/stage2_5_injector.py` | ✅ |
| 2 | 更新文档引用 | `CLAUDE.md`, `AGENTS.md` | ✅ |
| 3 | Stage4 添加 `--gap-monitor` 参数 | `scripts/stage4_report_generator.py` | ✅ |

### 待完成（Codex 执行）

| # | 变更 | 文件 | 状态 |
|---|------|------|------|
| 4 | 修复 Stage4 gap_monitor 路径推断逻辑 | `scripts/stage4_report_generator.py` | ⬜ |
| 5 | 修复 inject 脚本 is_estimated 跳过时不清理顶层 missing_items | `scripts/stage2_5_injector.py` | ⬜ |
| 6 | 移动非主流水线脚本到 `scripts/legacy/` | ~8个脚本 | ⬜ |
| 7 | 追踪未追踪的测试文件 | `tests/test_fix_estimated_verified.py`, `tests/test_stage4_docs.py` | ⬜ |

---

## 核心问题诊断摘要

### 问题1: 生产代码命名混乱
`inject_websearch_data_test.py` 是 3167 行的核心生产脚本，但名字带 `_test`，造成认知混乱。

### 问题2: Stage4 静默跳过 gap 校验
`stage4_report_generator.py:55` 检查 `reports/gap_monitor.json`（无日期），而流水线生成 `reports/gap_monitor_YYYYMMDD.json`。不存在无日期版本时，校验被静默跳过——报告可能在数据未完整时生成。

### 问题3: inject 脚本 is_estimated 边缘情况
当某指标已有值（`is_estimated=True`），inject 脚本跳过注入但**不调用** `_remove_top_missing`，导致顶层 `missing_items` list 残留该 key，Stage3 policy gate 被误阻断，用户需手动 `python3 -c` 修复。

### 问题4: scripts/ 目录脚本增殖
32 个脚本中约 10 个是旧版流程残留（MCP路径、旧版背景扫描、Yahoo数据源等），制造认知负担。

---

## 影响范围

| 组件 | 影响类型 |
|------|---------|
| `scripts/stage2_5_injector.py` | 重命名（功能不变） |
| `scripts/stage4_report_generator.py` | Bug修复（静默失败→显式警告） |
| `scripts/stage2_5_injector.py` | Bug修复（is_estimated边缘情况） |
| `scripts/legacy/` | 新目录，接收旧版脚本 |
| `CLAUDE.md`, `AGENTS.md` | 文档更新 |
| 测试文件 | git追踪 |

---

## 不在本期范围

- 方案B（流水线编排器）— 下期迭代
- 方案C（GPT API集成）— 暂不实现
- stage2_unified_enhancer.py 拆分 — 未来
- Pring 算法改动 — 明确排除
- 数据源替换 — 明确排除

---

## 测试验证

```bash
cd /mnt/d/cursor/datasource
source .venv/bin/activate && source .env

PYTHONPATH=./src python -m pytest tests/test_websearch_injector.py tests/test_stage3_guard.py tests/test_policy_rules.py -q
```

预期：全部通过，无回归。

---

## Codex 执行入口

详细的逐步执行指令见同目录下：
```
optimization/20260409_plan_a_refactor/CODEX_EXECUTE.md
```

---

## 提交计划

完成全部7步后，一次性提交：
```
fix: rename inject script, fix stage4 gap_monitor path, and cleanup scripts

- Rename inject_websearch_data_test.py → scripts/stage2_5_injector.py
- Fix stage4 gap_monitor to resolve dated gap_monitor_{YYYYMMDD}.json path
- Fix missing _remove_top_missing call on is_estimated skip in inject script
- Move 8 legacy scripts to scripts/legacy/
- Track previously untracked test files
```

---

## 下期迭代预告

**方案B: 流水线编排器**
- `scripts/run_daily_pipeline.py` — 统一入口，自动断点恢复，含 Tavily 配额保护
- `scripts/pipeline_status.py` — 状态总览
- `tests/test_pipeline_orchestrator.py` — 阶段检测逻辑测试
