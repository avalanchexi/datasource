# 批次 D1:run 目录契约 — atomic_write_json + 文件白名单 + run_dir_audit — 设计文档

> Spec for the 2026-06 refactor, batch D1(REFACTOR_PLAN §7)。
> Status: 2026-06-17 设计批准(brainstorming 产出)。可与 C 批次并行(worktree 支线);从开工 main HEAD 起。
> D1 = 原子写 + 白名单 + 诊断工具;**D2(另 PR)= 写盘前 contract hard-fail**,本 PR 不做强制阻断。

## 1. 目的与定位

消灭 run 目录(`data/runs/YYYYMMDD/`)的杂散文件累积:`.bak`、时间戳副本、`_new`。手段:① `utils/json_io.atomic_write_json`(tmp + `os.replace`)统一所有写盘;② 删 `dump_json(backup=True)` 的 `.bak`+时间戳逻辑;③ 以 `RunPaths` 为单一白名单来源;④ `scripts/tools/run_dir_audit.py` 列白名单外文件(诊断)。纯写入机制 + 工具,**输出内容逐字不变、零业务逻辑改动**。

证据(真实 `data/runs/20260610`):`market_data.json.bak`/`market_data_stage2.json.bak`/`pring_result.json.bak` + 时间戳副本 `market_data_stage2_20260610085557827559.json` —— 来自 `dump_json(backup=True)` 与各 stage 自带 `.bak`,正是要删的。

## 2. 范围

**In scope**
- `utils/json_io.py`:新增 `atomic_write_json(payload, path)`(tmp+`os.replace`,无 backup)+ `atomic_write_text(text, path)`(供 csv);`dump_json` 委托 `atomic_write_json` 并**删除 `backup` 的 `.bak`/时间戳副本逻辑**(`backup` 参数移除或 no-op)。
- 全流水线 run 目录写盘点切到 `atomic_write_json`/`atomic_write_text`,删各处自带 `.bak`(见 §4 迁移表)。
- `RunPaths` 扩为白名单单一来源:补 `source_conflicts`/`stage4_risk_review`/`quality_trend`/`run_lock` 属性;加 `data_dir_whitelist() -> set[str]`(从 data_dir 各属性派生文件名 + `.run.lock`)。`stage2_log` 按**实际落盘**(data_dir)纳入白名单,**不迁移其位置**。
- `scripts/tools/run_dir_audit.py`:给定日期,列 `data/runs/YYYYMMDD/` 白名单外文件,打印 PASS/violations(诊断;`--strict` 可退非零供 smoke)。
- 测试:`test_run_paths_consistency.py` 断言白名单;`test_utils_json_io.py` 改为断言 atomic_write + **不产 `.bak`**;新增 `run_dir_audit` 单测(造含 `.bak`/时间戳的临时目录,断言被标记)。
- 文档:`SCRIPTS.md` 加 `run_dir_audit` 条目;CLAUDE/AGENTS 轻量提及白名单契约。

**Out of scope**
- D2:写盘前 contract schema 校验 + hard-fail(`pring_result_contract`/`market_data_contract` 接线)。
- 迁移 `stage2_log`/observability 等到 log_dir(口径不一致只记录,不动)。
- `data/trend_history` 序列写(非 run 目录;可选原子化,非本 PR 目标)。
- `.run.lock` 写入机制(锁语义,保持原状;仅纳入白名单)。
- 任何业务逻辑/输出内容改动。

## 3. 安全确认
- **`.bak`/时间戳副本无消费者**:全仓 grep 仅见写入方,无 `open(*.bak)`/恢复逻辑 → 删 backup 不破任何读取路径。
- `tests/test_utils_json_io.py:45-75` **断言** `dump_json(backup=True)` 产 `.bak` → 删 backup 必须同步改该测试(改为断言 atomic_write_json 原子写 + 无 `.bak`)。
- 原子写产出内容与现状逐字一致(只换写入机制),replay/contract golden 不受影响。

## 4. 写盘点迁移表(run 目录;行号 = 开工 HEAD 附近,以 grep 实测为准)
| 文件 | 写 | 动作 |
|---|---|---|
| `scripts/stage1_data_collector.py`(main,~84-89) | market_data.json(.tmp+replace + `.bak`) | `atomic_write_json`;删 `.bak` |
| `scripts/stage3_pring_analyzer.py`(~726-730) | pring_result.json(`.bak`) | `atomic_write_json`;删 `.bak` |
| `scripts/stage3_pring_analyzer.py`(~769) | stage3 log | `atomic_write_json` |
| `scripts/stage4_report_generator.py`(~211) | 报告 `.bak`(`shutil.copy2`) | 删 `.bak`(报告在 `reports/`,但仍删副本污染) |
| `scripts/stage4_risk_review.py`(~639) | stage4_risk_review.json | `atomic_write_json` |
| `src/datasource/utils/quality_metrics.py`(~232) | quality_metrics.json | `atomic_write_json` |
| `src/datasource/utils/quality_metrics.py`(~236) | quality_trend.csv | `atomic_write_text`(tmp+replace) |
| `src/datasource/utils/policy_rules.py`(~297) | policy_evaluation.json | `atomic_write_json` |
| `src/datasource/utils/source_conflicts.py`(~82) | source_conflicts.json | `atomic_write_json` |
| `src/datasource/utils/run_snapshot.py`(~42) | run_snapshot.json | `atomic_write_json` |
| `src/datasource/utils/observability.py`(~118) | observability.json(log_dir) | `atomic_write_json`(一致性;白名单仍 data_dir) |
| `src/datasource/utils/trend_history_store.py`(~82) | run 目录 gap snapshot | run 目录写 → `atomic_write_json`;series(data/trend_history)可选 |
| `src/datasource/engines/stage2_5/core.py`(~951,1026) | market_data_complete.json 等 | `atomic_write_json` |
| `src/datasource/engines/stage2_5/trend_backfill.py`(~1254) | backfill issues log | `atomic_write_json` |
| `src/datasource/engines/stage2/cli.py`(~438-439 `_dump_json`) | market_data_stage2/websearch/split | `_dump_json` 切 `atomic_write_json`,删 backup 形参传递 |
| `scripts/tools/{run_snapshot,market_data_sanitize,trend_history_scan}.py` | run 目录写 | 切 `atomic_write_json` |
| `src/datasource/utils/run_lock.py`(~136) | `.run.lock` | **不动**(锁语义) |
> plan 执行时 `grep -rn "json.dump(\|dump_json(\|\.bak\|with_suffix.*tmp" scripts/ src/` 兜底,确保无遗漏 run 目录写盘点。

## 5. 白名单(data/runs/YYYYMMDD/ 实测全集,RunPaths 派生)
`market_data.json`、`market_data_stage2.json`、`market_data_complete.json`、`pring_result.json`、`search_tasks_stage2.jsonl`、`websearch_results_auto.json`、`websearch_results_manual.json`、`gap_monitor.json`、`quality_metrics.json`、`quality_trend.csv`、`policy_evaluation.json`、`run_snapshot.json`、`source_conflicts.json`、`stage4_risk_review.json`、`trend_history_gap.json`、`recap_facts.json`、`stage2_log.json`、`.run.lock`。**剔除**:`*.bak`、时间戳副本(`*_NNNNNN.json`)、`*_new`。
> `stage2_log.json` 实际落 data_dir(RunPaths 现定义在 log_dir,口径不一致)——白名单按实际包含;D1 不迁移。`split_dir`(websearch 拆分子目录)若存在,按目录白名单或排除规则处理(plan 实测定)。

## 6. run_dir_audit 工具
`scripts/tools/run_dir_audit.py --date YYYY-MM-DD`(默认今日):
- 读 `data/runs/<compact>/` 实际文件名集 vs `RunPaths.data_dir_whitelist()`;
- 打印:`OK: N files, all whitelisted` 或逐行 `STRAY: <name>`(`.bak`/时间戳/未知);
- 默认 exit 0(诊断);`--strict` 时有 stray 退非零(供 live smoke "文件数==白名单数")。
- 走 `run_clean.sh`;只读,不删文件(清理留人工/D2)。

## 7. 安全网
- `test_run_paths_consistency.py`:断言 `data_dir_whitelist()` == 期望集合,且每个 RunPaths data_dir 属性的 basename ∈ 白名单。
- `test_utils_json_io.py`:改断言 `atomic_write_json` 原子写正确 + 写后**目录无 `.bak`**;移除旧 backup 断言。
- 新 `tests/test_run_dir_audit.py`:tmp 目录造 `market_data.json` + `x.bak` + 时间戳副本,断言 audit 标记后两者、PASS 仅白名单集。
- 全量 `pytest -q` 无回归;replay/contract byte-stable(原子写不改内容)。

## 8. 验收
- `atomic_write_json`/`atomic_write_text` 存在;`dump_json` 无 backup `.bak`/时间戳逻辑;全 run 目录写盘点走原子写(grep 无残留 run 目录 `json.dump(`/自带 `.bak`,除 `.run.lock`)。
- `RunPaths.data_dir_whitelist()` 覆盖 §5 全集;`run_dir_audit` 工具可用,对脏目录正确报 stray。
- `test_run_paths_consistency`/`test_utils_json_io`/`test_run_dir_audit` 绿;全量无回归;replay/contract byte-stable。
- 文档同步(SCRIPTS run_dir_audit + 白名单契约提及)。
- (合入后首个交易日 live smoke,属验收观察)run 目录文件数 == 白名单数,无 `.bak`/时间戳副本产生。

## 9. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 删 backup 破读取 | §3:全仓无 `.bak` 消费者(grep 证);仅 test_utils_json_io 断言需同步改 |
| 漏迁某写盘点 → 仍产污染 | §4 迁移表 + plan grep 兜底;run_dir_audit 兜底暴露 |
| 白名单与实际不符 → audit/test 误报 | §5 以实测 20260610/20260609 全集为准;RunPaths 派生 |
| 原子写改了输出内容 | atomic_write_json 内容与 dump_json 一致(同 json.dumps 参数);replay/contract byte-stable 兜底 |
| 误碰 .run.lock 语义 | §2 明确不动 run_lock 写入 |
