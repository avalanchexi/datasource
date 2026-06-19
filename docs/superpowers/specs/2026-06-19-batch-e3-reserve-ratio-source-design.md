# 批次 E3:reserve_ratio 错口径源屏蔽 + BCOM 固定 quote 守卫 — 设计文档

> Spec for the 2026-06 refactor, batch E3(REFACTOR_PLAN §8,经源码深挖后修正为"减法+守卫")。
> Status: 2026-06-19 设计批准(brainstorming + 源码深挖产出)。建在 main `ddccebc`;独立 PR。

## 1. 目的与定位

屏蔽 `reserve_ratio` 的错口径来源(tradingeconomics `cash-reserve-ratio` = 7.50% 大行口径,曾使 2026-05-29 报告出假"偏紧"信号),让 PBoC 官方 provider 失败时**转 manual/搜索而非回退错值(宁缺勿错)**,且搜索链路不得重新接受该错口径 URL;并为已实现的 BCOM 固定 quote provider 加守卫测试防回归。

**深挖结论(修正 §8 的"改挂 PBoC provider / BCOM 评估 provider"措辞)**:
- reserve_ratio 的 PBoC provider(`official_china`)**早已存在**且 registry 先试它;7.50% 是它失败后**回退到 `trading_economics`** 才出现的。故修复 = **从 trading_economics 删 reserve_ratio**(减法),不需新建 provider。
- BCOM 的固定 quote provider(`market_quote_pages`,`bad_tokens` 拒 BCOMTR/total-return/sub-index)**早已存在且无竞争源**。故 E3 只加**守卫测试**锁住,不改 BCOM 代码。

## 2. 关键源码事实
- `registry.providers_for(key)` 按 `build_default_registry` 顺序收集所有 `key in supported_keys` 的 provider,`fetch` 逐个尝试到首个成功。reserve_ratio 顺序 = `official_china`(先)→ `trading_economics`(后,fallback)。
- `trading_economics.py`:`URLS["reserve_ratio"] = {"url": ".../china/cash-reserve-ratio", ...}`;`supported_keys = set(URLS)`。删 `URLS` 条目即自动从 `supported_keys` 移除 → registry 不再把 reserve_ratio 派发给它。
- `official_china.py`:`reserve_ratio` 已由 `RESERVE_RATIO_URL` + `_parse_monetary_result` 处理(不动)。
- `market_quote_pages.py`:`QUOTE_PAGES["BCOM"]`(investing bloomberg-commodity-historical-data,`required_tokens=[bloomberg,commodity,historical data]`,`bad_tokens=[total return,bcomtr,bcomx,sub-index,sub index]`);`BCOM` 仅此一处(stooq/yahoo/trading_economics 均不含 BCOM)。
- provider `name`:`official_china`/`market_quote_pages`/`trading_economics`。

## 3. 范围

**In scope**
1. `src/datasource/providers/stage2_structured/trading_economics.py`:删 `URLS` 中的 `reserve_ratio` 条目。
2. `rrr/reserve_ratio` 搜索链路:移除 Trading Economics trusted/issuer relax,将 `cash-reserve-ratio` 标为 bad URL/错口径来源。
3. 守卫/回归测试(见 §4)。
4. 文档:CLAUDE/AGENTS 把"reserve_ratio 结构化源"表述更新为"仅 official_china PBoC;tradingeconomics cash-reserve-ratio 已屏蔽(7.50% 大行口径错口径)";SCRIPTS/structured-provider 列表同步。

**Out of scope**
- 新建 provider(PBoC provider 已存在);改 official_china/market_quote_pages 逻辑;改 BCOM 代码。
- 扩 official override allowlist(mlf/USDCNY/BCOM 不变);reserve_ratio 仍走既有 pbc quality-replacement 通道(E2 已记录)。
- E1/E2 已覆盖部分。

## 4. 测试
- 新 `tests/test_e3_reserve_ratio_source.py`(或并入 structured provider 测试):
  - `"reserve_ratio" not in build_provider().supported_keys`(trading_economics)。
  - `[p.name for p in build_default_registry().providers_for("reserve_ratio")] == ["official_china"]`(无 trading_economics 回退)。
  - 行为:official_china 对 reserve_ratio fetch 抛 `StructuredProviderError` 时,`registry.fetch` **不**返回 trading_economics 的 7.50% 值(用注入式 fake provider 或 monkeypatch official_china.fetch 抛错 + 断言无结构化结果/抛错冒泡)。
  - 搜索负向: `rrr` profile 不信任 Trading Economics,`cash-reserve-ratio` 命中 bad URL 后 `search_result_scope_mismatch`;抽取结果若来自该 URL,校验置 `manual_required=True`。
  - **BCOM 守卫**:`[p.name for p in build_default_registry().providers_for("BCOM")] == ["market_quote_pages"]`(唯一源);`"total return" in QUOTE_PAGES["BCOM"]["bad_tokens"]` 且 `"bcomtr" in bad_tokens`(锁 BCOMTR 拒绝)。
- **byte-stable(E3 是行为修正,同 E1)**:Task 0 先查 `test_stage2_structured_golden`/`test_stage2_structured_integration`/replay 夹具是否经 reserve_ratio 的 trading_economics 回退产值:
  - 不经过 → golden byte-stable,照常断言;
  - 经过 → golden 合理变化,**逐条核对 diff = reserve_ratio 从 7.50% 错值变为缺失/转 manual**(预期修正)后才更新;**不盲更**。
- 全量 `pytest -q` 无回归(除上面预期修正)。文档契约 `test_manual_template`/`test_stage4_docs` 绿。

## 5. 验收
- `trading_economics` 不再支持 reserve_ratio;registry 对 reserve_ratio 只列 official_china;official_china 失败时无 7.50% 回退;搜索/抽取校验也不接受 `cash-reserve-ratio` 错口径 URL。
- BCOM 守卫测试绿(唯一源 + BCOMTR 拒绝)。
- 文档更新;全量无回归;replay golden 不经过则 byte-stable、经过则逐条核对为预期修正。
- (E 批累积前向观察:连续 5 交易日 macro compare 类 manual=0、日常手填 ≤ {etf}——合入后跟踪,非本 PR 内可算。)

## 6. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 删源后 reserve_ratio 更常缺失 | 这是**预期**(宁缺勿错优于 7.50% 错口径);PBoC official_china 仍先试,失败转搜索/manual(E2 policy 已备 pbc 兜底) |
| 行为变化破坏既有 golden 被误判 | §4:先查夹具,经过则逐条核对为预期修正,不盲更 |
| 误伤 trading_economics 其它 key | 只删 reserve_ratio 条目;断言其余 key(GC=F/CL=F/BZ=F/HG=F/reverse_repo 等)仍在 supported_keys |
| BCOM 未来被加竞争源/放松 bad_tokens | §4 守卫测试锁唯一源 + BCOMTR 拒绝 |
