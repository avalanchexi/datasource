# 批次 C6(可选):Stage1 采集器瘦身 — MarketDataCollector → engines/stage1/ — 设计文档

> Spec for the 2026-06 refactor, batch C6(REFACTOR_PLAN §6 可选项 / TODOS C6)。
> Status: 2026-06-17 设计批准(brainstorming 产出)。前置 C1–C5 已合入 main `0c8f14b`(Stage2/Stage2.5 巨石拆分收官)。
> 行号采自 main `0c8f14b`,`scripts/stage1_data_collector.py` ≈2561 行(`cat -n` 口径)。

## 1. 目的与定位

`scripts/stage1_data_collector.py`(~2561 行)几乎整体是一个 ~2270 行的 god-class `MarketDataCollector`(~45 方法)。C6 把该类 + 模块级 helper 纯机械搬移到新包 `src/datasource/engines/stage1/`(与 `engines/stage2/`、`engines/stage2_5/` 统一),脚本瘦为 ≤300 行薄 entry(re-export + `main` + `if __name__`),达成全局验收"`scripts/` 入口 ≤300 行"。

**这是 relocate-only,不是 god-class 拆解**:类内 ~45 方法经 `self` 共享状态,内部拆分是行为重构,需真 characterization;而 Stage1 走 live TuShare、无 replay harness。relocate-only 行为天然保持(类同一对象),风险最低,匹配"瘦身"目标。god-class 内部拆解是独立 initiative,延后。

## 2. 范围

**In scope**
- 新建 `src/datasource/engines/stage1/`(`__init__.py` + `collector.py`)。
- **逐字搬入** `collector.py`:`MarketDataCollector` 类(~44–2307)、`Stage1DataCollector = MarketDataCollector` 别名(2308)、模块级 helper:`_calc_change_from_trend_history`、`_is_missing_change`、`_backfill_stage1_trend`、`_normalize_date_str`、`_resolve_last_trading_day`(行号以开工 HEAD 现取)。
- 脚本 `scripts/stage1_data_collector.py` 瘦为:re-export 上述名 + 保留 `main()` 与 `if __name__`(`main` ~115 行,作 entry)。
- **测试 repoint**:24 处 `monkeypatch.setattr("scripts.stage1_data_collector.get_manager", ...)` → `datasource.engines.stage1.collector.get_manager`。
- 轻量 is-identity 断言 + 既有 stage1 单测回归。

**Out of scope**
- 任何方法体逻辑改动:纯搬移,body 逐字(含注释、局部名、空行)。
- **不拆 god-class 内部**(per-category collectors / `_fetch_*_from_tushare` / calc / freshness / completeness 仍在一个类)。
- **不 dedup** stage1 的 `_calc_change_from_trend_history`(与 Stage2.5 已抽取的 trend_backfill 是独立副本;dedup 是行为风险 + 跨包,随类搬移保留副本,延后)。
- 不并入 utils/coercion;不改 `main` 业务逻辑;不动 manager/adapters/calculators。

## 3. 设计决策

| 决策 | 结论 | 依据 |
|---|---|---|
| **A. 范围** | relocate-only:整类 + helper 搬 src/,脚本瘦身 + re-export;不拆内部、不 dedup | 行为天然保持(类同一对象);Stage1 无 replay,内部拆解风险高;匹配"瘦身" |
| **B. 目标包** | `src/datasource/engines/stage1/collector.py` | 与 `engines/stage2/`、`engines/stage2_5/` 统一 stageN 心智模型 |
| **C. main 归属** | 留脚本作薄 entry(stage1 目标 ≤300 行,非 stage2/2.5 的 ≤30) | `main`~115 行 + re-export + imports < 300;无需单独 cli 模块 |
| **D. get_manager repoint** | 24 处 test patch `scripts.stage1_data_collector.get_manager` → `engines.stage1.collector.get_manager` | `MarketDataCollector.__init__` 在新模块查 `get_manager`;脚本命名空间 patch 不再触达(C5 同类问题) |
| **E. re-export** | 脚本 re-export `MarketDataCollector`/`Stage1DataCollector`/`FundFlowData` + helper | 现有测试 `from scripts.stage1_data_collector import MarketDataCollector/Stage1DataCollector/FundFlowData` 与外部引用零改 |

## 4. 目标结构
```
src/datasource/engines/stage1/
  __init__.py            # docstring
  collector.py           # MarketDataCollector + Stage1DataCollector 别名 + 5 模块级 helper(逐字)

scripts/stage1_data_collector.py  # 薄 entry:re-export + main + if __name__
```

依赖 DAG(全向下,无环):
```
manager / adapters / calculators.technical_indicators / models.market_data_contract / utils.{trend_history_store,run_paths} / pandas/numpy
   └─ engines/stage1/collector
        └─ scripts/stage1_data_collector(re-export + main)
```
collector 不 import 脚本、不 import engines/stage2(_5);import-time 冒烟确认无环。

## 5. monkeypatch 契约

- **re-export(零改)**:`from scripts.stage1_data_collector import MarketDataCollector / Stage1DataCollector / FundFlowData`。
- **位置无关 patch(零改)**:`monkeypatch.setitem(sys.modules,"tushare",...)`、实例方法 patch(`setattr(collector,"_get_recent_open_dates",...)`)、`MarketDataCollector.__new__(...)`。
- **必须 repoint(C6 唯一测试改动)**:24 处 `get_manager`(`test_stage1_data_collector.py` L59/70/81/91/101/152/182/213/246/284/332/387/414/443/468/497/526/556/586/615/640/669/703/712)→ `datasource.engines.stage1.collector.get_manager`。脚本 `from datasource import get_manager` 类搬走后于脚本内无用 → 脚本可删该 import(`get_manager` 由 collector.py import)。
- plan 收尾 grep `setattr("scripts.stage1_data_collector.<X>"` 兜底:确认除 `get_manager` 外无其它 script-global 被字符串 patch(当前实测仅 `get_manager`)。

## 6. 安全网(诚实:比 C1–C5 轻,但够)
- byte-for-byte 类搬移 → 行为天然保持;`is` 身份:`脚本.MarketDataCollector is collector.MarketDataCollector`(re-export 同一对象)。
- 既有 `tests/test_stage1_data_collector.py` + `tests/test_stage1_hsgt_window.py`(get_manager repoint 后)全绿——这是 Stage1 的行为锁。
- import-time 冒烟无环;`scripts/stage1_data_collector.py --help` diff 空;脚本行数 ≤300。
- **无 replay harness**:Stage1 走 live TuShare,不在测试内跑真实 API;由"纯搬移 + is 身份 + 既有单测"兜底——这正是选 relocate-only 的理由。

## 7. 执行序(moves 先,repoint 后)
Task 0 置备/baseline → Task 1 建 collector + 瘦脚本(此后 get_manager-patch 的 stage1 单测**中途 RED 预期**,因类移出脚本)→ Task 2 repoint 24 处 get_manager → 全绿 → Task 3 is-identity + 全量验收 → Task 4 文档/隔离/回报。
> ⚠️ Task 1 后、Task 2 前,`test_stage1_data_collector.py` 多数用例 RED 是预期(Codex 勿停);用 py_compile/import 冒烟/`is` 身份 + 不 patch get_manager 的用例校验,Task 2 后转绿。

## 8. 验证命令(plan 内联完整版)
```bash
bash run_clean.sh python -m pytest tests/test_stage1_data_collector.py tests/test_stage1_hsgt_window.py -q
bash run_clean.sh python -m py_compile src/datasource/engines/stage1/*.py scripts/stage1_data_collector.py
bash run_clean.sh python -m flake8 src/datasource/engines/stage1/
bash run_clean.sh python -c "import scripts.stage1_data_collector as s; from datasource.engines.stage1 import collector as c; print(s.MarketDataCollector is c.MarketDataCollector)"   # True;防环
bash run_clean.sh python scripts/stage1_data_collector.py --help   # diff vs baseline 空
bash run_clean.sh python -m pytest -q   # 全量无回归
```
baseline:C6 worktree 实现前全量绿(记数)。

## 9. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 类搬移引入 body 差异 | 逐字搬移;`is` 身份 + 既有 stage1 单测兜底;评审 diff 只允许位置 + import + re-export |
| get_manager repoint 漏改 → stage1 单测假绿/RED | §5 全 24 处映射 + grep 兜底;Task 2 后专项跑两测试文件确认绿 |
| collector → 脚本 反向 import / 成环 | collector 不 import 脚本;import 冒烟 |
| 脚本残留未用 import(get_manager 等) | 删类搬走后无用的 import,或 `# noqa: F401`(re-export 用的保留);flake8 脚本干净 |
| Stage1DataCollector 别名漏 re-export | §2/§5 明确;is-identity 断言含别名 |
| 行号漂移 | C6 worktree 从开工 HEAD;按类名/函数名 + 逐字 body |

## 10. 验收
- `engines/stage1/{__init__,collector}.py` 存在,含 `MarketDataCollector`(+别名)+ 5 helper;脚本 re-export 为同一对象(`is`)。
- 脚本 ≤300 行,仅 re-export + main + if __name__;`--help` diff 空;`MarketDataCollector` 等在脚本无本地定义(`rg "^class MarketDataCollector" scripts/stage1_data_collector.py` 为空)。
- collector 不 import 脚本;import 冒烟无环;flake8 `src/datasource/engines/stage1/` 干净。
- 24 处 get_manager repoint 完成;`test_stage1_data_collector.py` + `test_stage1_hsgt_window.py` 全绿;`pytest -q` 全量无回归。
- `data/runs`/`data/trend_history`/live 行为零变更。
