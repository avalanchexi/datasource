# 2026-06-10 重构测试计划

总原则:沿用 2026-04-27 策略 — deterministic fixture replay 为主,live Stage1→Stage4 只作发布前 smoke(受 Tavily 每日一次约束,live 验证只能挂在当日正常流水线上,不为重构单独重跑 Stage2)。

## 0. 全批次基线(每个 PR 必跑)

```bash
pytest -q
python -m py_compile src/datasource/**/*.py scripts/*.py
flake8 src/
```

关键既有回归套件(改动相关域时必跑,见 CLAUDE.md "重构落地后的关键回归测试"):

- `tests/test_utils_coercion.py` / `tests/test_utils_json_io.py`
- `tests/test_pring_scoring_golden.py`(夹具 `tests/fixtures/pring_golden/`)
- `tests/test_monetary_key_registry.py`
- `tests/test_missing_items_compat.py`
- `tests/test_stage25_contract_replay.py`
- `tests/test_run_paths_consistency.py`

## 批次 0(功能有效性审计)

- 审计工具自带测试:`bash run_clean.sh python -m pytest optimization/20260610_refactor_plan/audit -q` 全绿(import 分类器 + 三档合并逻辑)。
- 回放隔离验证:审计运行后断言真实 `data/trend_history/` 与 `data/runs/2026*` 无 mtime 变化;scratch 目录 `data/runs/19990101/` 运行后删除。
- 产物完整性:`used_unused.json` 覆盖 `src/datasource/` 全部模块,无 `unknown` 档;`AUDIT_RESULTS.md` 对 REFACTOR_PLAN §1.2 每个疑似模块给出档位。

## 批次 A(清理)

- 删除/移动前:`grep -rn "<文件名>" src scripts tests docs *.md` 逐项确认无引用;有引用的不删,记录到 PR 描述。
- 合入后:`pytest -q` 全绿 + `python -c "from datasource import get_manager; print('OK')"`。
- mcp_adapter/mcp_tools 下线时同步下线 `tests/test_na_filling.py`、`tests/run_na_filling.py`(确认其仅覆盖 legacy 链路后)。

## 批次 B(命名收敛)

- 每个移动的脚本:`python scripts/tools/<新名>.py --help` 与旧入口输出一致。
- shim 验证:`python scripts/<旧名>.py --help` 打印 deprecation 后正常转发。
- 文档一致性:`grep -rn "scripts/<旧名>" *.md docs/` 清零(shim 期内允许 SCRIPTS.md 保留一处迁移对照表)。

## 批次 C(巨石拆分)— 重点

### C-0.5 replay harness(任何搬移前的硬前置)

- 对**未拆分的现状代码**先跑通:mock Tavily/DeepSeek/Exa(以 `websearch_results/` 缓存为录制源,零真实请求),replay 输出连续两次 byte-stable(时间戳字段豁免)。
- harness 自身进 `tests/`,从此 C1–C5 每个 PR 直接复用,不再各自搭桩。

### C0 forex 证据合一

1. 先写 characterization tests:对 Stage2 侧与 Stage2.5 侧的 `_is_forex_*`/`_has_forex_*` 各自现行为建参数化用例(输入覆盖:零值+无证据、no_change 明确证据、base_price/base_date 缺失、`no_deepseek_key` 文案、daily 前缀拒绝)。
2. 合一后两侧用例同时通过;如发现两侧行为真实存在差异,保留差异并在 utils 层暴露两个入口,差异写入 PR 描述。
3. 跑 `tests/test_*forex*` 全部既有用例(近期 commit 5935d84/32b6635/756250d 对应的回归)。

### C1–C5 机械搬移 PR

每个 PR 的统一验收:

1. **Fixture replay**:取 `data/runs/20260522/`(或最近完整 run)为夹具——
   - Stage2:以 `market_data.json` + `search_tasks_stage2.jsonl` + 缓存的 `websearch_results/` 为输入,mock Tavily/DeepSeek/Exa 网络层,断言 `market_data_stage2.json` 与 summary 关键字段(`stage2_effective_hit_rate`、`task_structured_success`、`manual_reason_breakdown`)逐字段一致。
   - Stage2.5:`bash run_clean.sh python scripts/stage2_5_injector.py <夹具三件套>`,断言 `market_data_complete.json`、`gap_monitor.json` 与基线 byte-stable(时间戳字段白名单豁免)。
2. **CLI 等价**:`--help` 输出 diff 为空;入口脚本行数 ≤300(终态 ≤30)。
3. **行为冻结区专项**(涉及 `manual_official.py`、fund_flow gate 的 PR):
   - `test_stage25_contract_replay.py` + `test_missing_items_compat.py`
   - official allowlist 三项(mlf/USDCNY/BCOM)正反用例:估算→正规化触发;非 allowlist key(etf)不触发;非 HTTPS/多 URL/带说明文字 URL 不触发。

### C3 `_execute_tasks` 切分

- 动刀前新增阶段级 characterization test:replay 一个混合 run(structured 命中 + Tavily 搜索 + manual_required 各至少 1 例),锁 per-task 的 `result_type`/`manual_reason`/diagnostics 行。
- 切分后该用例 + 上面 fixture replay 全部不变。

## 批次 D(run 目录契约)

- D1 原子写:单测模拟写盘中途抛异常,断言目标文件保持旧内容、无 tmp 残留;`tests/test_run_paths_consistency.py` 扩展白名单断言;`tools/run_dir_audit.py` 对历史 run 目录跑一遍,输出存量越界文件清单(只报告不删)。
- D2 schema 校验:对夹具 `market_data_complete.json` 注入坏数据(缺 category、错类型、`current_value` 为字符串)断言 hard fail 且报错指明字段路径;`--no-validate-output` 逃生门可绕过;正常夹具零误报。
- live smoke:合入后首个交易日流水线,人工核对 run 目录文件数 == 白名单数。

## 批次 E(兜底产品化)

- E1 自动回填:夹具构造"trend_history/event_history 有上期值、market_data 缺 `previous_value`"的 macro 条目,断言回填值、`change_rate` 口径 `(cur-prev)/abs(prev)*100`、`value_source=event_history_backfill`、`is_estimated` 不变;分母为 0 时保留缺口(沿用现规则)。
- E2 模板预填:gap_monitor 含 `mlf`/`etf` 时,生成的 manual 骨架包含 yaml 声明的预填字段与 note marker;不在册的 key 仍生成空骨架。
- E3 源屏蔽:断言 `reserve_ratio` 不再从 tradingeconomics `cash-reserve-ratio` 取值(provider 列表级断言);新 PBoC provider 的解析单测 + 失败 fallback 到搜索链路。
- 验收口径(连续 5 个交易日观察):macro compare 类 manual 条目 0;日常手填集合 ≤ {etf};`gap_monitor.json` 中 `reserve_ratio` 不再出现错口径值。

## Live 发布前 smoke(每批次合入后首个交易日)

按 CLAUDE.md Daily Report Pipeline 正常跑当日全链(Tavily 一次),核对:

1. `stage2_effective_hit_rate` 不低于前 5 日均值 - 5pp;
2. `gap_monitor.json` pending 集合不新增;
3. `reports/${DATE}-背景扫描120.md` 生成且无新增 N/A;
4. run 目录无白名单外文件(批次 D 后)。
