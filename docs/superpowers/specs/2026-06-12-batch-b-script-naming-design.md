# 批次 B:脚本命名收敛 — 设计文档

> Spec for the 2026-06 refactor, batch B. Parent strategy: `optimization/20260610_refactor_plan/REFACTOR_PLAN.md` §5。
> Status: 2026-06-12 brainstorming 定稿(用户已拍板 scripts/utility 与 scripts/archive 走"拆分定档");可执行计划待批次 A 合入 main 后从新 HEAD 生成。

## 目标终态

`scripts/` 只剩**两层**:

1. **主链**(不动):`stage1_data_collector.py`、`stage2_unified_enhancer.py`、`stage2_5_injector.py`、`stage3_pring_analyzer.py`、`stage4_risk_review.py`、`stage4_report_generator.py`、`check_monthly_freshness.py`(每日必跑)、`runtime_env.sh`/`bootstrap_venv.sh`/`env_probe.sh` 等 shell 基建。
2. **`scripts/tools/`**(新增,带 `__init__.py`):全部非主链运维工具,`<domain>_<verb>` 命名。

`scripts/utility/`、`scripts/archive/`、`scripts/legacy/`(A 批已清)三个历史层级全部消失。

## 硬约束(规划期实测,计划必须吃进)

1. **`scripts/` 是 Python 包,测试以模块导入脚本**。主链被 20+ 测试文件密集导入 → 绝不改名。非主链唯一被模块导入的是 `scripts.fix_estimated_verified`(`tests/test_fix_estimated_verified.py`,2 个活用例)→ 它**不是废弃代码**,改名移入 tools/ 时必须同 commit 改该测试的 import。
2. **`tests/test_fund_flow_pipeline.py` 按文件路径硬编码加载** `scripts/utility/manual_fund_flow_updater.py`(L159/L164 importlib spec + L199 sys.path.insert)→ 移动时同 commit 改这两处路径常量。
3. **文档是本批最大爆炸半径**:SCRIPTS.md/CLAUDE.md(诊断工具条目)/AGENTS.md/runbooks 含大量命令路径;批次 A 新增的 doc contract tests(`test_manual_template.py`/`test_stage4_docs.py`)盯着 runbook。执行批次 A 教训:**py 引用闸 + md 活文档闸双闸**,每个改名与其文档同步必须原子提交。
4. utility 9 个脚本全部只导入活模块(无批次 A 归档雷);代码层消费者仅 manual_fund_flow_updater(测试)一个。

## 处置清单

### B-1:§5 表 17 个脚本 → `scripts/tools/`(改名表沿用 §5,两处定死)

- `fix_estimated_verified.py` → `tools/estimated_fix_verified.py`(§5 原表"或确认废弃"分支删除——有活测试断言 bdi 信任域规则,是活工具)
- `gap_monitor_to_manual_template.py` → `tools/manual_template_from_gap_monitor.py`(批次 E2 已按此名引用,锁定)
- 其余按 §5 表执行;`check_monthly_freshness.py` 留原位。

### B-2:`scripts/utility/` 拆分定档(用户已拍板)

| 文件 | 处置 | 依据 |
|---|---|---|
| `manual_fund_flow_updater.py` | → `tools/fund_flow_manual_updater.py` + 同 commit 改 `test_fund_flow_pipeline.py` 两处路径 | 活测试依赖;SCRIPTS.md/资金流指南有操作记载 |
| `fund_flow_daily_sync.py` | → `tools/fund_flow_daily_sync.py`(已是 domain-first,保名) | 导入活模块(fund_flow_series/trend_history_store),资金流运维工具 |
| `background_scan_120d_generator.py`、`background_scan_validator.py`、`calculate_na_data.py`、`generate_background_scan.py`、`generate_network_report.py`、`tushare_pro_report_patch.py`、`validate_data_quality.py`(7 个) | → `archive/py_unused/scripts_utility/` | background_scan 体系已于批次 A 归档;代码层零消费者,活文档明确"已归档不能作为入口" |

### B-3:`scripts/archive/`(6 个文件 + README)→ `archive/py_unused/scripts_archive/`

自带 README 一起走;代码层零消费者(规划期已验)。

### B-4:旧路径 shim 策略

- **只给活文档中出现过命令路径的脚本留 shim**(清单在计划生成期对 SCRIPTS.md/CLAUDE.md/AGENTS.md/runbooks grep 定死;CLAUDE.md 诊断工具节的 `stage2_health_check.py`、`stage2_low_score_audit.py` 预计在列)。
- shim 形态(每个 ≤10 行):stderr 打 deprecation(指明新路径 + 移除批次)→ `runpy.run_path(<新路径>, run_name="__main__")` 转发,argv 原样透传。
- 死脚本(B-2 归档 7 个、B-3)不留 shim。
- shim 保留一个版本周期,到期删除记入 TODOS(挂在批次 C 完成后)。
- 双环境验证:shim 在 WSL bash 与 Windows 侧 `wsl -e bash -lc` 通道各冒烟一次。

### B-5:文档同步与双闸

- 同步范围(活文档):SCRIPTS.md、CLAUDE.md、AGENTS.md、README.md、`docs/AI报告生成标准流程_V3.3.md`、`docs/AI背景扫描报告执行完整手册.md`、`templates/AI_EXECUTION_CHECKLIST.md`、`docs/手动更新资金流向数据指南.md`(若含路径)。
- **不动**:`docs/archive/**`、dated specs/plans、`optimization/archive/**`、README changelog 段。
- 合入闸:① py 闸——`grep` 旧模块名/旧路径在 `{src,scripts,tests}` `*.py` 清零(shim 文件自身豁免);② md 闸——旧路径在活文档清零;③ doc contract tests 全绿。

## 验收标准

1. `pytest -q` 全绿(含两个测试文件的精确修改);`pytest optimization/20260610_refactor_plan/audit -q` 全绿。
2. 每个移入 tools/ 的脚本 `--help` 冒烟通过;每个 shim 转发冒烟通过(stderr 含 deprecation + 退出码与直跑一致)。
3. 双闸清零;`scripts/` 顶层只剩主链 + shim + shell 基建 + `tools/`。
4. `compileall` 通过;文档契约测试通过。

## 非目标

- 不动主链脚本内容(巨石拆分是批次 C);不动 `scripts/__init__.py` 的包结构。
- 不重写历史文档;不在本批删除 shim。

## 风险

| 风险 | 缓解 |
|---|---|
| 漏改某个活文档命令路径 | md 闸 grep 旧路径清零作为合入条件;doc contract tests 兜底 |
| shim 的 runpy 语义差异(`__file__`/argv) | shim 冒烟显式断言退出码与输出;`run_name="__main__"` 保证入口语义 |
| 隐藏的按路径调用方(cron/外部笔记) | 规划期已查:无 CI workflow、无 .sh/.bat 调用;shim 保一个周期兜底 |
| Codex 计划外扩散(批次 A 教训) | 计划写明"文档修复只允许出现在对应任务的原子 commit 内;预期外引用 → 停止回报" |
