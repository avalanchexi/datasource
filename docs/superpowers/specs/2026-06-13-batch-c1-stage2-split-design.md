# 批次 C1:Stage2 拆分 — errors / snippet_filters / evidence / regex_extraction — 设计文档

> Spec for the 2026-06 refactor, batch C1(REFACTOR_PLAN §6.2 首个 Stage2 巨石拆分 PR)。
> Status: 2026-06-13 设计定稿(brainstorming 产出)。前置 PR-C-0.5(replay harness `7aad7df`)、PR-C0(forex 证据合一 `2427814`)均已合入 main。
> 决策基线:**纯机械搬移**(函数体逐字不改,只搬位置 + import 转发);**4 个内聚簇**进新包 `src/datasource/engines/stage2/`;主脚本保留 `_私有名` 显式 import,call-site 零改动;**跨模块 characterization tests 先行**(before/after 逐项断言)。
> 行号采自 main `0187b00`(C0 之后,未触碰 4 簇,行号有效);**执行以 PR 开工时从当时 HEAD 现生成的 per-PR 计划为准**(见 §6 / plan)。

## 1. 目的与定位

`scripts/stage2_unified_enhancer.py`(7174 行)是 REFACTOR_PLAN §1.1 点名的头号巨石。C1 是批次 C 中**第一个真正动 Stage2 代码**的 PR,把 4 个**无状态、内聚、低耦合**的函数簇下沉到新包 `src/datasource/engines/stage2/`,为后续 C2(extraction_apply / structured_runner / query_planner / diagnostics / validation / cli)、C3(`_execute_tasks` 切分)腾出干净的依赖面。

C1 的全部价值在于**零行为风险地缩小主脚本**:选这 4 个簇正是因为它们是纯函数谓词/过滤/抽取/错误分类,**不持有可变状态、不调用编排层、不触碰冻结区**(forex 零值防占位、fund_flow gate、official override allowlist 全部不在本 PR)。

## 2. 范围

**In scope** — 4 个新模块(`engines/stage2/` 新包):

| 新模块 | 职责 | 簇内函数(main `0187b00` 行号) | 自带模块常量 | 簇间依赖 |
|---|---|---|---|---|
| `errors.py` | Tavily 错误分类 / quota 判定 / 环境代理错误识别与记录 | `_coerce_http_status`(326)、`_safe_header_value`(333)、`_sanitize_tavily_error_text`(361)、`_tavily_error_metadata`(375)、`_is_tavily_quota_error`(408)、`_text_indicates_quota_or_rate_limit`(415)、`_is_tavily_quota_response`(445)、`_is_environment_proxy_error`(459)、`_build_environment_proxy_error_records`(523) | `_TAVILY_LIMIT_STATUSES`、`_TAVILY_ERROR_TEXT_LIMIT`、`_TAVILY_REQUEST_ID_HEADERS`(316–323) | 无(自洽) |
| `snippet_filters.py` | 新鲜度过滤 + 域名/官方域/关键词过滤 + 评分统计 | 新鲜度:`_parse_date_str`(182)、`_extract_dates`(206)、`_is_stale`(224)、`_prefer_fresh_snippets`(238)、`_extract_report_month`(259)、`_prefer_latest_report_snippets`(289);评分统计:`_percentile`(646)、`_score_stats`(664);域名/关键词:`_filter_by_domain`(840)、`_official_extract_domains`(899)、`_host_matches_official_domain`(906)、`_filter_by_official_extract_domain`(912)、`_snippet_blob`(933)、`_filter_by_keyword_rules`(944)、`_snippets_have_issuer`(967)、`_snippets_have_expected_period`(987)、`_strict_indicator_tokens`(1001) | `_REPORT_MONTH_KEYS`(256) | 无(自洽) |
| `evidence.py` | value/usage 证据评分 + snippet 诊断 + source_url 证据 + field-retry 证据 | 证据评分/诊断:`_pattern_hits`(1021)、`_usage_evidence_score`(1031)、`_value_evidence_score`(1036)、`_final_snippet_diagnostics`(1077)、`_selected_reason_from_diagnostics`(1110);source_url/field-retry:`_first_snippet_url`(1694)、`_normalize_url_for_evidence`(1702)、`_snippets_for_source_url`(1706)、`_snippet_text`(1721)、`_snippet_contains_number`(1728)、`_resolve_field_retry_evidence_source`(1746)、`_field_retry_window_evidence`(1781)、`_source_label_for_task`(1818) | — | **→ snippet_filters**(调 `_score_stats`/`_snippet_blob`/`_snippets_have_issuer`/`_snippets_have_expected_period`;单向,无环) |
| `regex_extraction.py` | regex fallback / structured value / flow value 抽取 + rrr 类型推断 | `_regex_fallback`(1322)、`_collect_snippet_text`(1387)、`_find_number_by_patterns`(1393)、`_extract_structured_value`(1424)、`_extract_flow_value`(1471)、`_refine_extraction_value`(1510)、`_infer_rrr_type`(1539) | — | 无(自洽) |

- 新包 `src/datasource/engines/stage2/__init__.py`(空或仅 docstring)。
- 主脚本 `scripts/stage2_unified_enhancer.py`:删除上述 4 簇的本地定义,改为从 4 个新模块**显式 import `_私有名`**(见 §4)。
- 跨模块 characterization tests 新增(先行,见 §5)。
- 配套 housekeeping:TODOS.md C1 状态、文档同步检查(见 §7)。

**Out of scope(本 PR 不做)**

- 任何函数体逻辑改动:纯搬移,函数体逐字不变(含注释、局部变量名、空行)。
- 横切件 `_safe_number`(L785,全脚本 32 处调用)、`_RANGE_RULES`(L793):**不属任何 C1 簇**(4 簇内部均不调用),留主脚本,待 C2 结合 coercion 收敛。
- C2 边界函数:`_exa_search_type`(611)、`_start_date_from_max_age`(639)、`_infer_report_period`(1549)、`_infer_as_of_date`(1557)、`_augment_extraction_metadata`(1577)、`_scrub_unevidenced_forex_zeroes`(1879)、`_copy_forex_compare_fields`(1909)、`_apply_extraction`(1937) 及之后所有 → 留 C2/C3。
- `_execute_tasks`(3403–6049)切分 → C3。
- 主脚本入口瘦身到 ≤30 行 → C 批次终态(C1 只缩小,不达终态行数)。
- 冻结区(forex 零值防占位、fund_flow gate、official override allowlist):本 PR diff 不触碰。

## 3. 边界决策(brainstorming 核心结论)

REFACTOR_PLAN §6.2 的行号区间是 2026-06-10 旧 HEAD 的评审定位坐标,且 snippet_filters(815–1101)与 evidence(996–1051)**区间有重叠**。本 spec 按**职责 + 实测调用图**定死归属,消除该重叠:

| 决策点 | 结论 | 依据 |
|---|---|---|
| snippet_filters ↔ evidence 重叠区(996–1051)归属 | 纯筛选/打分(`_score_stats`/`_snippet_blob`/`_snippets_have_*`/`_strict_indicator_tokens`)→ snippet_filters;证据评分/诊断(`_pattern_hits`/`_usage_evidence_score`/`_value_evidence_score`/`_final_snippet_diagnostics`/`_selected_reason_from_diagnostics`)→ evidence | 实测:evidence 簇调 snippet_filters 簇,反之不成立 → 依赖单向 evidence→snippet_filters |
| `_safe_number` / `_RANGE_RULES` 归属 | **留主脚本**,不进 C1 任何模块 | 实测 4 簇内部零调用;`_safe_number` 全脚本 32 处调用(多在 C2/C3 代码),搬移会扩 diff 面并产生 module→script 反向 import |
| `_infer_rrr_type`(1539)归属 | 进 `regex_extraction.py` | `_refine_extraction_value`(regex 簇)调用它;为保簇自洽随迁。`_infer_report_period`/`_infer_as_of_date` 不被 regex 簇调用 → 留 C2 |
| `_exa_search_type`/`_start_date_from_max_age`(611/639) | 留主脚本(C2) | 非错误分类,errors 簇语义不含 Exa search-type;紧贴 errors 区间外 |
| 搬移后主脚本如何调这些函数 | 显式 `from datasource.engines.stage2.<mod> import _foo, _bar, ...` **保留 `_私有名`** | call-site(含 `_execute_tasks` 等 C2/C3 代码)零改动;diff 只在文件头 import 段 + 删除原定义。零行为风险 |
| 新模块 import header | 仅 stdlib + typing(`re`/`datetime`/`timedelta`/`timezone`/`urlparse`/`Any/Dict/List/Optional/Tuple/Iterable`),按各簇实际引用裁剪 | 实测 4 簇均**零 logger 调用**、零第三方依赖 |
| 簇间依赖落地 | `evidence.py` 顶部 `from datasource.engines.stage2.snippet_filters import _score_stats, _snippet_blob, _snippets_have_issuer, _snippets_have_expected_period` | 单向依赖,无环;由 plan 精确列出实际被调名单 |

## 4. 目标结构与搬移机制

### 4.1 新包布局

```
src/datasource/engines/stage2/
  __init__.py            # 空(或仅 docstring)
  errors.py              # 9 函数 + 3 常量,自洽
  snippet_filters.py     # 17 函数 + 1 常量,自洽
  evidence.py            # 13 函数,import snippet_filters 4 个名
  regex_extraction.py    # 7 函数,自洽
```

### 4.2 搬移机制(每个簇统一三步,逐字搬移)

1. **新模块** = import header(§3 裁剪)+ 该簇常量(逐字)+ 该簇函数(逐字,body 一字不改)+ (evidence)对 snippet_filters 的 import。
2. **主脚本删除**该簇原定义(函数 + 常量),在主脚本 import 段之后(loguru import 后)插入:
   ```python
   from datasource.engines.stage2.errors import (
       _coerce_http_status, _safe_header_value, _sanitize_tavily_error_text,
       _tavily_error_metadata, _is_tavily_quota_error, _text_indicates_quota_or_rate_limit,
       _is_tavily_quota_response, _is_environment_proxy_error, _build_environment_proxy_error_records,
       _TAVILY_LIMIT_STATUSES, _TAVILY_ERROR_TEXT_LIMIT, _TAVILY_REQUEST_ID_HEADERS,
   )
   # ...snippet_filters / evidence / regex_extraction 同理,完整名单见 plan
   ```
   常量若仍被主脚本残留代码引用,一并 re-import(`_TAVILY_*`/`_REPORT_MONTH_KEYS` 等)。
3. **不保留薄 alias、不改 call-site**:主脚本所有原调用点(`_is_tavily_quota_error(...)` 等)因 import 进同名,逐字不动。

### 4.3 入口行数

C1 后主脚本预计减少约 1000+ 行(4 簇合计),但**不达 ≤30 行终态**(那是 C2/C3 完成后)。C1 验收只要求"减少且 CLI 行为不变",不卡终态行数。

## 5. Characterization tests(先写,TDD;本 PR 与 replay harness 并行的第二重网)

新增 `tests/test_stage2_split_characterization.py`(跨模块 before/after 断言):

1. **搬移前先落地并跑绿**:从 `scripts.stage2_unified_enhancer` import 4 簇代表函数,跑固定输入表,断言**当前**输出 = 锁现行为。覆盖每个模块的核心谓词:
   - errors:`_is_tavily_quota_error`/`_is_tavily_quota_response`/`_text_indicates_quota_or_rate_limit`(quota status 402/403/429/432/433、文本 quota/rate-limit/payment、`_is_environment_proxy_error` 的 proxy/SOCKS/DNS 文案)、`_build_environment_proxy_error_records` 形状。
   - snippet_filters:`_is_stale`/`_prefer_fresh_snippets`(max_age 边界)、`_filter_by_domain`/`_host_matches_official_domain`(hostname 严格匹配)、`_filter_by_keyword_rules`、`_score_stats`(percentile 形状)。
   - evidence:`_value_evidence_score`/`_usage_evidence_score`(pattern 命中)、`_snippets_for_source_url`/`_snippet_contains_number`(数值证据)、`_field_retry_window_evidence`。
   - regex_extraction:`_regex_fallback`/`_extract_structured_value`/`_extract_flow_value`/`_refine_extraction_value`(各指标抽取)、`_infer_rrr_type`。
2. **搬移后**:把 import 改指向 `datasource.engines.stage2.<mod>`(或仍经主脚本 re-export,二者皆可,断言两路一致),同一输入表、同一 expected,**逐项不变**。
3. **import-surface 断言**:断言 4 个新模块 export 全部应迁函数名 + 主脚本仍可调同名(re-export 生效),防漏迁/拼写漂移。
4. 不改任何现有测试;新测试进默认 `pytest -q`(全离线、秒级)。

> 已有回归网(不替代 characterization):C-0.5 replay harness(`tests/test_stage2_replay_harness.py`,Stage2 端到端 byte-stable)兜底整体行为;C1 的 characterization 锁住簇级函数粒度。

## 6. 执行流程框架(给 Codex;exact code 由 plan 从 HEAD 现生成)

> 环境头与 worktree 协议见 REFACTOR_PLAN §11 / §11.1;plan 须内联完整环境头(Codex 零上下文)。可执行 plan:`docs/superpowers/plans/2026-06-13-batch-c1-stage2-split.md`。

1. **Task 0 置备**:worktree `.worktrees/codex-batch-c1-stage2-split`(分支 `codex/batch-c1-stage2-split`)← from main `0187b00`;按 §11.1 配方置备 `.env`/`.venv`/`logs`/`reports`;baseline `bash run_clean.sh python -m pytest -q` 全绿(含 C-0.5 replay harness)。
2. 写 characterization tests(主脚本现函数),跑绿 = 锁现行为。
3. 建包 `engines/stage2/` + `__init__.py`;按 errors → snippet_filters → regex_extraction → evidence 顺序建模块(evidence 最后,依赖 snippet_filters)。
4. 每建一个模块:迁常量 + 迁函数(逐字)→ 主脚本删原定义 + 加 re-import → `py_compile` + `flake8`(查 F401 未用 / F811 重定义 / F821 未定义)→ 局部跑 characterization + replay harness。
5. 全部迁完:characterization tests 改指向新模块断言逐项不变;全量 `pytest -q` + `py_compile` + `flake8 src/` + C-0.5 replay harness **全绿且 byte-stable**;主脚本 `--help` diff 为空。
6. 收尾:隔离断言(主 checkout 数据零变更)、临时产物清理、完成回报;更新 TODOS.md C1 行。

## 7. 行为冻结约束(diff 只允许"搬移 + import"变化)

- **函数体逐字不变**:4 簇所有函数 body 一字不改(含注释、空行、局部名)。评审 diff 只允许:新模块新增、主脚本删除原定义 + 新增 import 段。
- **零 call-site 改动**:主脚本对这些函数的调用点全部保持原样(靠同名 re-import)。
- **冻结区不触碰**:本 PR 不涉及 forex 零值防占位、fund_flow gate、official override allowlist;这些函数(`_scrub_unevidenced_forex_zeroes` 等)留主脚本,且其依赖的谓词(若属本 PR 迁移簇)输出必须逐项一致。
- **依赖单向**:`evidence → snippet_filters`,不得出现 module→主脚本 反向 import,不得引入循环。
- **横切件不搬**:`_safe_number`/`_RANGE_RULES` 留主脚本。
- 验证**全离线**:不重跑 Stage2 真实搜索(Tavily 每日一次);不触碰当日 `data/runs/YYYYMMDD` 与 `data/trend_history`;不手删 `.run.lock`。

## 8. 验收

1. characterization tests 搬移前锁绿、搬移后逐项不变;import-surface 断言通过。
2. `pytest -q` 全绿;`python -m py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py` 通过;`flake8 src/` 无新增违规(尤其 F401/F811/F821)。
3. C-0.5 replay harness(`tests/test_stage2_replay_harness.py`)仍 byte-stable;`scripts/stage2_unified_enhancer.py --help` 与基线 diff 为空。
4. 主脚本中 4 簇无本地定义(`rg "^def _coerce_http_status|^def _filter_by_domain|^def _value_evidence_score|^def _regex_fallback" scripts/stage2_unified_enhancer.py` 为空),仅剩 re-import。
5. 新包 4 模块依赖图:`errors`/`snippet_filters`/`regex_extraction` 无 intra-import;`evidence` 仅 import `snippet_filters`;无环、无 module→主脚本反向 import。
6. 主脚本行数较 C0 后基线显著下降(预计 −1000+);CLI 行为不变(本 PR 不卡 ≤30 行终态)。

## 9. 前置 / housekeeping 状态

- ✅ **PR-C-0.5 已合入** main(replay harness,canonical 回归网)。
- ✅ **PR-C0 已合入** main `2427814`(forex 证据合一 + `note_utils.py`;4 簇不含 forex 判定族,与 C0 零交叠)。
- ⬜ **TODOS.md C1 行**:`[ ] PR-C1` → 执行中/完成(随 PR 合入更新);"当前焦点" → PR-C2。
- ⬜ **文档同步检查**:本 PR 仅搬内部私有函数,不改 CLI/命令引用 → `SCRIPTS.md`/`CLAUDE.md`/`AGENTS.md` 命令示例预计零改动;plan 收尾 grep 确认无命令漂移(若 `tests/test_manual_template.py`/`test_stage4_docs.py` 无关则不触发)。

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 搬移漏迁某函数 / 拼写漂移导致 NameError | import-surface 断言 + `flake8` F821 + `py_compile`;characterization 覆盖每模块核心谓词 |
| 簇间依赖看漏,产生循环或反向 import | §3 实测调用图定死单向 evidence→snippet_filters;plan 精确列 import 名单;评审查依赖图 |
| 函数体被"顺手"微调 | §7 冻结:body 逐字;评审 diff 只允许新增模块 + 主脚本删除/import |
| 横切件 `_safe_number` 被误迁,扩大 diff/反向 import | §3 定死留主脚本;plan 不含其搬移步骤 |
| 主脚本残留代码引用已迁常量(`_TAVILY_*`/`_REPORT_MONTH_KEYS`)未 re-import → NameError | 常量随函数 re-import;`flake8` F821 + 全量 pytest 兜底 |
| 行号漂移 | plan 从 HEAD `0187b00` 现生成;搬移按**函数名 + 逐字 body**,不靠绝对行号 retype |
| replay harness 因 import 路径变化误报 | harness 走 CLI/公共入口,不 import 私有名;搬移后仍 byte-stable 即证明 |
