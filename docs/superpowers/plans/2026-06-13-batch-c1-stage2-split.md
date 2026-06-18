# PR-C1 执行计划:Stage2 拆分 — errors / snippet_filters / evidence / regex_extraction

> 可执行 plan(writing-plans 规格)。Spec:`docs/superpowers/specs/2026-06-13-batch-c1-stage2-split-design.md`。
> 从 main `0187b00` 现生成(`docs: mark PR-C0 complete in refactor TODOS`)。行号采自该 HEAD;**搬移按函数名 + 逐字 body,不靠绝对行号 retype**。
> 执行者:Codex(executing-plans 技能),零上下文。逐 checkbox 勾选;卡住即停并回报,不擅自改计划。

### 规划方对 §11.2 的有意偏离(评审请勿误判为占位/疏漏)

1. **搬移函数体未内联**(偏离 §11.2 #7"搬移代码块直接给完整代码"):本 PR 是**纯逐字搬移**,要求 body 一字不改。指令为"按函数名整体搬入、body 逐字不变",而非把 ~1000 行抄进本 plan——抄写反而引入转写风险。正确性由 characterization(§Task1/6)+ replay harness byte-stable + `py_compile`/`flake8` 三重保证。
2. **import header / `# noqa: F401` 未逐字定死**:新模块 import header 与未用告警压制依各簇实际引用,由 `flake8`(F401/F811/F821)反馈收敛——这是机械、可判定的过程,非主观占位。
3. **characterization expected 已预计算**(§11.2 无占位符要求**已满足**):Task 1 核心断言的 expected 由规划方在 main `0187b00` 离线实跑取真并写死,Codex 不得改;仅可选追加项需自行实跑取真。

---

## 统一环境头(Codex 必读,零上下文)

- **执行通道**:本机 Windows 上必须经 `wsl -e bash -lc '...'` 进入 Linux 侧;`.venv` 是 Linux venv。所有命令默认从 **worktree 根**执行(`$WT`),例外单独注明。
- **流水线脚本**一律 `bash run_clean.sh python scripts/...`,不直跑;测试 `bash run_clean.sh python -m pytest -q`。
- **硬约束**:Tavily 每日一次,**任何验证不得重跑 Stage2 真实搜索**;不触碰真实 `data/runs/YYYYMMDD`(当日)与 `data/trend_history`;不手删 `.run.lock`。本 PR **全部验证离线**(pytest / py_compile / flake8 / replay harness),零真实 API。
- **行为冻结区**(diff 只允许 import/路径变化):official manual override allowlist(mlf/USDCNY/BCOM)、fund_flow 估算 gate、forex 零值防占位、Stage3 三路 gate。**本 PR 不触碰这些区域的任何函数**(它们留主脚本)。
- **本 PR 额外冻结**:4 个搬移簇的**函数体逐字不变**(含注释、空行、局部变量名)。允许的 diff 仅:新模块新增、主脚本删除原定义 + 新增 re-import 段。**禁止**顺手改 body、禁止改 call-site、禁止迁移横切件 `_safe_number`/`_RANGE_RULES`。
- **Commit 规范**:Conventional(`test:`/`refactor:`),小步频提(建议每模块一个 refactor commit + characterization 一个 test commit)。

### 搬移簇清单(权威;按名搬移,body 逐字)

**errors.py**(自洽,无 intra-import):
- 常量(L316–323):`_TAVILY_LIMIT_STATUSES`、`_TAVILY_ERROR_TEXT_LIMIT`、`_TAVILY_REQUEST_ID_HEADERS`
- 函数:`_coerce_http_status`、`_safe_header_value`、`_sanitize_tavily_error_text`、`_tavily_error_metadata`、`_is_tavily_quota_error`、`_text_indicates_quota_or_rate_limit`、`_is_tavily_quota_response`、`_is_environment_proxy_error`、`_build_environment_proxy_error_records`(L326–610,止于 `_exa_search_type` 前)

**snippet_filters.py**(自洽):
- 常量(L256):`_REPORT_MONTH_KEYS`
- 新鲜度(L182–325):`_parse_date_str`、`_extract_dates`、`_is_stale`、`_prefer_fresh_snippets`、`_extract_report_month`、`_prefer_latest_report_snippets`
- 评分统计(L646–686):`_percentile`、`_score_stats`
- 域名/关键词(L840–1020,止于 `_pattern_hits` 前):`_filter_by_domain`、`_official_extract_domains`、`_host_matches_official_domain`、`_filter_by_official_extract_domain`、`_snippet_blob`、`_filter_by_keyword_rules`、`_snippets_have_issuer`、`_snippets_have_expected_period`、`_strict_indicator_tokens`

**evidence.py**(`from datasource.engines.stage2.snippet_filters import _score_stats, _snippet_blob, _snippets_have_issuer, _snippets_have_expected_period`):
- 证据评分/诊断(L1021–1126,止于 `_candidate_query_quality` 前):`_pattern_hits`、`_usage_evidence_score`、`_value_evidence_score`、`_final_snippet_diagnostics`、`_selected_reason_from_diagnostics`
- source_url/field-retry(L1694–1877,止于 `_scrub_unevidenced_forex_zeroes` 前):`_first_snippet_url`、`_normalize_url_for_evidence`、`_snippets_for_source_url`、`_snippet_text`、`_snippet_contains_number`、`_resolve_field_retry_evidence_source`、`_field_retry_window_evidence`、`_source_label_for_task`

**regex_extraction.py**(自洽):
- 函数(L1322–1548,止于 `_infer_report_period` 前):`_regex_fallback`、`_collect_snippet_text`、`_find_number_by_patterns`、`_extract_structured_value`、`_extract_flow_value`、`_refine_extraction_value`、`_infer_rrr_type`

> ⚠️ **不搬**(留主脚本):`_safe_number`(785)、`_RANGE_RULES`(793)、`_exa_search_type`(611)、`_start_date_from_max_age`(639)、`_pattern_hits` 之后的 `_candidate_query_quality`(1127)、`_infer_report_period`(1549)、`_infer_as_of_date`(1557)、`_augment_extraction_metadata`(1577)、`_scrub_unevidenced_forex_zeroes`(1879) 及之后。

---

## Task 0 — worktree 置备 + baseline(首任务)

- [ ] 置备 worktree(从 main `0187b00`):
  ```bash
  MAIN=/mnt/d/cursor/datasource
  BR=codex/batch-c1-stage2-split
  WT="$MAIN/.worktrees/codex-batch-c1-stage2-split"
  cd "$MAIN" && git fetch && git worktree add "$WT" -b "$BR" 0187b00
  cp "$MAIN/.env" "$WT/.env"
  mkdir -p "$WT/logs" "$WT/reports" "$WT/.venv"
  cd "$WT" && DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1 bash run_clean.sh python -V
  ```
  **Expected**:打印 Python 版本(≥3.7);`.venv` bootstrap 成功。
  **若失败**:停-回报(不要 `ALLOW_SYSTEM_PYTHON=1` 绕过)。
- [ ] baseline 测试(必须与主 checkout 一致):
  ```bash
  cd "$WT" && bash run_clean.sh python -m pytest -q 2>&1 | tail -5
  ```
  **Expected**:全绿(与 main `0187b00` 一致,含 `tests/test_stage2_replay_harness.py`、`tests/test_stage25_contract_replay.py`)。记录 passed 数。
  **若失败**:停-回报(置备问题,不是本 PR 改动)。
- [ ] 记录基线指标(供收尾对比):
  ```bash
  cd "$WT" && wc -l scripts/stage2_unified_enhancer.py
  bash run_clean.sh python scripts/stage2_unified_enhancer.py --help > /tmp/c1_help_baseline.txt 2>&1; echo "help exit=$?"
  ```
  **Expected**:行数 7174;`--help` exit=0,输出存 `/tmp/c1_help_baseline.txt`。

---

## Task 1 — characterization tests(先写,锁现行为)

- [ ] 新建 `tests/test_stage2_split_characterization.py`,从**主脚本现函数** import,跑固定输入表锁现行为。下列 expected 值已由规划方在 main `0187b00` 上**离线实跑现函数取真**(非臆造;`/tmp/c1_probe*.py`),Codex 直接采用,**不得改 expected**:
  ```python
  """C1 跨模块 characterization:搬移前后逐项不变。先对主脚本现函数锁行为,
  搬移后(Task 6)断言新模块行为一致。全离线、秒级。
  expected 真值采自 main 0187b00 实跑(规划方预计算)。"""
  import importlib
  import pytest

  ENH = importlib.import_module("stage2_unified_enhancer")  # scripts/ 在 sys.path(conftest)

  # ---- errors:quota status(_is_tavily_quota_response 读 status_code/status 键)----
  @pytest.mark.parametrize("payload,expected", [
      ({"status_code": 402}, True), ({"status_code": 403}, True),
      ({"status_code": 429}, True), ({"status_code": 432}, True),
      ({"status_code": 433}, True), ({"status_code": 200}, False),
      ({"status_code": 404}, False), ({}, False),
      ({"status": 429}, True),
  ])
  def test_tavily_quota_response(payload, expected):
      assert ENH._is_tavily_quota_response(payload) is expected

  # ---- errors:quota/rate 文本 ----
  @pytest.mark.parametrize("text,expected", [
      ("rate limit exceeded", True), ("payment required", True),
      ("quota exhausted", True), ("429 Too Many Requests", True),
      ("ok", False), ("", False), ("insufficient balance", False),
  ])
  def test_quota_or_rate_text(text, expected):
      assert ENH._text_indicates_quota_or_rate_limit(text) is expected

  # ---- snippet_filters:官方域严格 hostname 匹配 ----
  @pytest.mark.parametrize("host,domain,expected", [
      ("www.pbc.gov.cn", "pbc.gov.cn", True),
      ("pbc.gov.cn", "pbc.gov.cn", True),
      ("sub.pbc.gov.cn", "pbc.gov.cn", True),
      ("evil-pbc.gov.cn.bad.com", "pbc.gov.cn", False),
  ])
  def test_host_matches_official_domain(host, domain, expected):
      assert ENH._host_matches_official_domain(host, domain) is expected

  # ---- evidence:数值证据仅匹配带单位数字(亿/billion 等)----
  @pytest.mark.parametrize("snippet,value,expected", [
      ({"content": "北向资金净流入 12.5 亿元"}, 12.5, True),
      ({"title": "成交 3.2 billion"}, 3.2, True),
      ({"content": "净流入 12.5 亿元"}, 99.0, False),
      ({"content": "USDCNY 7.1234 today"}, 7.1234, False),  # 无单位 → False
      ({"content": "x"}, None, False),
  ])
  def test_snippet_contains_number(snippet, value, expected):
      assert ENH._snippet_contains_number(snippet, value) is expected

  # ---- regex_extraction:rrr 类型推断(加权/weighted→weighted;法定/statutory→statutory)----
  @pytest.mark.parametrize("text,expected", [
      ("加权平均存款准备金率", "weighted"),
      ("weighted average RRR", "weighted"),
      ("法定存款准备金率", "statutory"),
      ("大型存款类金融机构", None),
      ("", None),
  ])
  def test_infer_rrr_type(text, expected):
      assert ENH._infer_rrr_type(text) == expected

  # ---- import-surface:主脚本 re-export 生效 ----
  def test_import_surface_monolith_reexports():
      for name in ["_is_tavily_quota_response", "_text_indicates_quota_or_rate_limit",
                   "_host_matches_official_domain", "_snippet_contains_number",
                   "_value_evidence_score", "_regex_fallback", "_infer_rrr_type"]:
          assert hasattr(ENH, name), f"主脚本应仍可调 {name}(re-export)"
  ```
  > 以上为**锁定基线**,Codex 直接落地、不改 expected。可**追加**(非必需)spec §5 其余覆盖面(`_is_environment_proxy_error` proxy/SOCKS/DNS 文案、`_is_stale`/`_prefer_fresh_snippets`、`_value_evidence_score(snippet,task)→int`、`_extract_structured_value`/`_extract_flow_value`);**追加项的 expected 必须先 `python -c "import sys;sys.path.insert(0,'scripts');import stage2_unified_enhancer as m;print(m.<fn>(...))"` 实跑取真,不臆造**。
  >
  > ⚠️ 规划方实测纠偏(防 Codex 踩同样的坑):`_snippet_contains_number` **只匹配带单位**(亿港元/亿元/亿/billion/bn)的数字,纯数字如 `7.1234` 返回 **False**;`_infer_rrr_type` 仅认 `加权/weighted`→`weighted`、`法定/statutory`→`statutory`,其余 **None**。
- [ ] 跑绿(锁现行为):
  ```bash
  cd "$WT" && bash run_clean.sh python -m pytest tests/test_stage2_split_characterization.py -q 2>&1 | tail -5
  ```
  **Expected**:全绿。**若某用例 expected 拿不准**:先 `python -c "import sys; sys.path.insert(0,'scripts'); import stage2_unified_enhancer as m; print(m.<fn>(<input>))"` 取真值再写死。
- [ ] commit:`test: add C1 stage2 split characterization (lock pre-move behavior)`

---

## Task 2 — 建包 + errors.py

- [ ] 建包:`src/datasource/engines/stage2/__init__.py`(仅 docstring):
  ```python
  """Stage2 enhancer 内聚子模块(批次 C 巨石拆分)。"""
  ```
- [ ] 新建 `src/datasource/engines/stage2/errors.py`:import header(按实际引用裁剪,errors 簇用到 `Any/Dict/Optional/Tuple` + 可能 `re`)+ **逐字搬入** errors 簇 3 常量 + 9 函数(见清单,body 一字不改)。
- [ ] 主脚本 `scripts/stage2_unified_enhancer.py`:**删除** errors 簇 3 常量 + 9 函数原定义;在 `from loguru import logger`(L34)之后插入:
  ```python
  from datasource.engines.stage2.errors import (  # noqa: F401 (C1 re-export)
      _TAVILY_LIMIT_STATUSES,
      _TAVILY_ERROR_TEXT_LIMIT,
      _TAVILY_REQUEST_ID_HEADERS,
      _coerce_http_status,
      _safe_header_value,
      _sanitize_tavily_error_text,
      _tavily_error_metadata,
      _is_tavily_quota_error,
      _text_indicates_quota_or_rate_limit,
      _is_tavily_quota_response,
      _is_environment_proxy_error,
      _build_environment_proxy_error_records,
  )
  ```
- [ ] 校验:
  ```bash
  cd "$WT" && bash run_clean.sh python -m py_compile src/datasource/engines/stage2/errors.py scripts/stage2_unified_enhancer.py
  bash run_clean.sh python -m flake8 src/datasource/engines/stage2/errors.py
  bash run_clean.sh python -m pytest tests/test_stage2_split_characterization.py -q 2>&1 | tail -3
  ```
  **Expected**:py_compile 无输出;flake8 无 F811/F821/F401(已迁函数若主脚本无残留引用,re-import 的 `# noqa: F401` 压制未用告警;**若某名实际仍被主脚本调用则无需 noqa**——Codex 据 flake8 结果调整);characterization 全绿。
  **若 F821 undefined**:某常量/函数漏 re-import → 补入 import 名单。
- [ ] commit:`refactor: extract stage2 errors module (PR-C1)`

---

## Task 3 — snippet_filters.py

- [ ] 新建 `src/datasource/engines/stage2/snippet_filters.py`:import header(用到 `datetime/timedelta/timezone`、`re`、`Any/Dict/List/Optional/Tuple/Iterable`)+ **逐字搬入** `_REPORT_MONTH_KEYS` + 新鲜度 6 函数 + 评分统计 2 函数 + 域名/关键词 9 函数(见清单)。
- [ ] 主脚本删除这些原定义;追加 re-import 段(同 Task 2 风格,完整名单:`_REPORT_MONTH_KEYS`、`_parse_date_str`、`_extract_dates`、`_is_stale`、`_prefer_fresh_snippets`、`_extract_report_month`、`_prefer_latest_report_snippets`、`_percentile`、`_score_stats`、`_filter_by_domain`、`_official_extract_domains`、`_host_matches_official_domain`、`_filter_by_official_extract_domain`、`_snippet_blob`、`_filter_by_keyword_rules`、`_snippets_have_issuer`、`_snippets_have_expected_period`、`_strict_indicator_tokens`)。
- [ ] 校验(同 Task 2 三连)+ characterization 全绿。
  **Expected**:全绿。注意 `_safe_number`/`_RANGE_RULES`(L785/793)**不搬**,仍在主脚本原位。
- [ ] commit:`refactor: extract stage2 snippet_filters module (PR-C1)`

---

## Task 4 — regex_extraction.py

- [ ] 新建 `src/datasource/engines/stage2/regex_extraction.py`:import header(`re`、`Any/Dict/List/Optional/Tuple`)+ **逐字搬入** 7 函数(`_regex_fallback`、`_collect_snippet_text`、`_find_number_by_patterns`、`_extract_structured_value`、`_extract_flow_value`、`_refine_extraction_value`、`_infer_rrr_type`)。
  > `_refine_extraction_value` 调 `_infer_rrr_type`(同模块内),自洽。
- [ ] 主脚本删原定义 + re-import 段(7 个名)。
- [ ] 校验 + characterization 全绿。
  **Expected**:全绿。`_infer_report_period`(1549)/`_infer_as_of_date`(1557)**留主脚本**。
- [ ] commit:`refactor: extract stage2 regex_extraction module (PR-C1)`

---

## Task 5 — evidence.py(最后,依赖 snippet_filters)

- [ ] 新建 `src/datasource/engines/stage2/evidence.py`:import header + **簇间依赖 import**:
  ```python
  from datasource.engines.stage2.snippet_filters import (
      _score_stats,
      _snippet_blob,
      _snippets_have_issuer,
      _snippets_have_expected_period,
  )
  ```
  + **逐字搬入** 证据评分/诊断 5 函数(`_pattern_hits`、`_usage_evidence_score`、`_value_evidence_score`、`_final_snippet_diagnostics`、`_selected_reason_from_diagnostics`)+ source_url/field-retry 8 函数(`_first_snippet_url`、`_normalize_url_for_evidence`、`_snippets_for_source_url`、`_snippet_text`、`_snippet_contains_number`、`_resolve_field_retry_evidence_source`、`_field_retry_window_evidence`、`_source_label_for_task`)。
  > Codex:搬入后用 `flake8 F821` 确认 evidence 簇对 snippet_filters 的实际依赖名单 = 上述 4 个;若 F821 报其它未定义名(如还调了某 snippet_filters 函数),补进簇间 import。
- [ ] 主脚本删原定义 + re-import 段(13 个名)。
- [ ] 校验 + characterization 全绿。
- [ ] commit:`refactor: extract stage2 evidence module (PR-C1)`

---

## Task 6 — characterization 切到新模块 + 全量验收

- [ ] 在 `tests/test_stage2_split_characterization.py` 末尾追加**新模块直连断言**(证明 4 模块独立 export 且行为一致):
  ```python
  import importlib
  ERRORS = importlib.import_module("datasource.engines.stage2.errors")
  SNIP = importlib.import_module("datasource.engines.stage2.snippet_filters")
  EVID = importlib.import_module("datasource.engines.stage2.evidence")
  REGEX = importlib.import_module("datasource.engines.stage2.regex_extraction")

  def test_new_modules_export_moved_names():
      assert hasattr(ERRORS, "_is_tavily_quota_response")
      assert hasattr(SNIP, "_host_matches_official_domain")
      assert hasattr(SNIP, "_score_stats")
      assert hasattr(EVID, "_value_evidence_score")
      assert hasattr(REGEX, "_regex_fallback")

  def test_moved_fn_identity_via_monolith():
      # 主脚本 re-export 的对象与新模块为同一函数(zero call-site churn 证明)
      assert ENH._is_tavily_quota_response is ERRORS._is_tavily_quota_response
      assert ENH._value_evidence_score is EVID._value_evidence_score
      assert ENH._regex_fallback is REGEX._regex_fallback
  ```
- [ ] 全量验收:
  ```bash
  cd "$WT"
  bash run_clean.sh python -m pytest -q 2>&1 | tail -8
  bash run_clean.sh python -m py_compile src/datasource/engines/stage2/*.py scripts/stage2_unified_enhancer.py
  bash run_clean.sh python -m flake8 src/datasource/engines/stage2/
  bash run_clean.sh python -m pytest tests/test_stage2_replay_harness.py tests/test_stage25_contract_replay.py -q 2>&1 | tail -5
  bash run_clean.sh python scripts/stage2_unified_enhancer.py --help > /tmp/c1_help_after.txt 2>&1
  diff /tmp/c1_help_baseline.txt /tmp/c1_help_after.txt && echo "HELP-DIFF-EMPTY"
  wc -l scripts/stage2_unified_enhancer.py
  ```
  **Expected**:pytest 全绿(passed 数 = baseline + 新 characterization 用例);py_compile 无输出;flake8 无违规;replay harness byte-stable;`HELP-DIFF-EMPTY`;主脚本行数较 7174 下降约 1000+。
  **若 replay harness 非 byte-stable**:停-回报(说明搬移引入了行为差异,逐簇 revert 定位)。
- [ ] 残留校验(4 簇主脚本无本地定义):
  ```bash
  cd "$WT" && rg -n "^def _coerce_http_status|^def _filter_by_domain|^def _value_evidence_score|^def _regex_fallback|^def _infer_rrr_type" scripts/stage2_unified_enhancer.py || echo "NO-LOCAL-DEF (OK)"
  rg -n "^def _safe_number|^def _exa_search_type|^def _infer_report_period|^def _scrub_unevidenced_forex_zeroes" scripts/stage2_unified_enhancer.py && echo "RETAINED-IN-MONOLITH (OK)"
  ```
  **Expected**:第一条 `NO-LOCAL-DEF`;第二条命中 4 个(横切件/C2 函数仍在主脚本)。
- [ ] commit:`test: assert C1 split modules behave identically post-move`

---

## Task 7 — 文档同步 + 隔离断言 + 回报(尾任务)

- [ ] TODOS.md(`optimization/20260610_refactor_plan/TODOS.md`)更新 C1 行 `[ ]` → `[x]`,"当前焦点"改为 PR-C2;commit `docs: mark PR-C1 complete in refactor TODOS`。
- [ ] 命令漂移检查(本 PR 仅搬内部私有函数,预计零命令改动):
  ```bash
  cd "$WT" && bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3
  ```
  **Expected**:全绿(本 PR 不改文档命令示例)。
- [ ] 隔离断言(主 checkout 零污染;worktree 数据隔离):
  ```bash
  cd "$WT" && git status --short
  ls "$MAIN/data/runs/" 2>/dev/null | tail -3   # 仅确认未新增当日产物;不写入
  ```
  **Expected**:`git status` 只含本 PR 的新增/修改文件(4 新模块 + `__init__.py` + 主脚本 + 新测试 + TODOS.md);无 `data/`/`reports/`/`logs/` 业务产物。
- [ ] 临时产物清理:`rm -f /tmp/c1_help_baseline.txt /tmp/c1_help_after.txt`。
- [ ] **完成回报**(给评审方 Claude):
  - 实际 commit 列表(逐条);
  - 全量 pytest passed 数(baseline → after);
  - 主脚本行数(7174 → ?);
  - 4 模块依赖图确认(errors/snippet_filters/regex 无 intra-import;evidence 仅 import snippet_filters);
  - replay harness byte-stable 确认 + `--help` diff 空确认;
  - **任何计划外改动逐条列出**(理想为零;若 flake8 逼出额外 import 调整,明示)。

---

## 评审方(Claude)checklist

1. **计划符合度**:7 个 Task 逐项完成;commit 列表与回报一致;独立验证"计划外改动=0"(不只信摘要)。
2. **冻结区 diff**:4 簇函数体逐字未变(`git diff` 只见位置移动 + import);call-site 零改;横切件 `_safe_number`/`_RANGE_RULES` 仍在主脚本;forex/fund_flow/official allowlist 函数未触碰。
3. **依赖图**:`evidence → snippet_filters` 单向;无 module→主脚本反向 import;无循环。
4. **测试**:characterization before/after 逐项一致 + import-surface + identity 断言;replay harness byte-stable;`--help` diff 空。
5. **合入**:默认 squash;合入前验证分支与合入内容零 diff;合入后 `git worktree remove "$WT"` + 删分支;下一步生成 C2 plan。
