# CLAUDE.md / AGENTS.md accuracy 修正 + intra-doc 去冗 执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 修 CLAUDE.md/AGENTS.md 的 accuracy stale(死 `datasource-test`、AGENTS MCP 归档表述、CLAUDE 结构化源漏 reserve_ratio)+ 去 AGENTS 文档内重复的「Codex + gstack」块。纯文档,**不跨文档裁剪**(两文档服务不同模型,各自自足)。

**Architecture:** 6 处定点编辑(CLAUDE 2、AGENTS 4)+ 1 处文档内去重;不改任何代码逻辑/命令契约。`tests/test_manual_template.py`/`tests/test_stage4_docs.py` 断言 runbook 命令——改后必跑确认绿(本计划不动被断言的 `bash run_clean.sh ...` 命令)。

**Tech Stack:** Markdown;pytest(doc 契约);git;Windows + WSL。

> 现状 main `879a9e4`。背景:`src/datasource/cli.py`(及 cli/ 包)不存在、`test_command` 全 src 无定义 → `datasource-test` CLI 已死;MCP 已于 `879a9e4` 归档(test_fund_flow_pipeline 两段 MCP 测试已删)。建小分支 `codex/doc-accuracy-fixes`(doc 级,可不开 worktree)。

---

## 偏离声明
- 纯文档 accuracy + 文档内去重;**不做 CLAUDE↔AGENTS 跨文档去重**(两文档服务不同模型,各自必须自足)。
- 不改被 `test_manual_template`/`test_stage4_docs` 断言的命令示例。
- `setup.py` 的死 entry 作**可选 Task 3**(代码改动)单列,不混入 doc commit。

## Task 0 — baseline
- [ ] `bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3` 全绿(doc 契约基线)。

## Task 1 — CLAUDE.md 两处
**Files:** Modify `CLAUDE.md`
- [ ] **Step 1(删死 datasource-test)** 把:
```
# 验证安装
python -c "from datasource import get_manager; print('OK')"
datasource-test  # CLI 入口（等价于 python -m datasource.cli test_command）
```
改为:
```
# 验证安装
python -c "from datasource import get_manager; print('OK')"
```
- [ ] **Step 2(结构化源列表补 reserve_ratio)** 在 `### Stage2/Stage2.5 搜索优化要点` 的结构化源句中,把
`` `reverse_repo/mlf/USDCNY/industrial/industrial_sales` `` 改为 `` `reverse_repo/reserve_ratio/mlf/USDCNY/industrial/industrial_sales` ``(reserve_ratio 结构化源 = official_china PBoC,与下文"仅 official_china;TE 已屏蔽"一致)。
- [ ] **Step 3** commit `docs: fix CLAUDE dead datasource-test + add reserve_ratio to structured list`

## Task 2 — AGENTS.md 四处
**Files:** Modify `AGENTS.md`
- [ ] **Step 1(Sanity 删死 datasource-test,§3 第 3 步)** 把:
```
3. Sanity:
   ```bash
   python -c "from datasource import get_manager; print('OK')"
   datasource-test
   ```
```
改为:
```
3. Sanity:
   ```bash
   python -c "from datasource import get_manager; print('OK')"
   ```
```
- [ ] **Step 2(§4 Smoke 行)** 把 `` - Smoke: `pytest -q` 或 `datasource-test`。 `` 改为 `` - Smoke: `pytest -q`。 ``
- [ ] **Step 3(§13 MCP 归档表述)** 把:
```
- MCP 链路（`src/datasource/mcp_adapter.py`、`src/datasource/utils/mcp_tools.py`）经审计 unreachable 但**刻意保留**：`tests/test_fund_flow_pipeline.py` 混合测试依赖，归档延期，不要顺手删。
```
改为:
```
- MCP 链路（`mcp_adapter`、`mcp_tools`）已归档至 `archive/py_unused/datasource/`（批次 A 遗留收口，2026-06）；`tests/test_fund_flow_pipeline.py` 两段 legacy MCP 测试已随归档删除，主链对其零 import。
```
- [ ] **Step 4(去重「Codex + gstack」块)** 文件末尾有**两个** `# Codex + gstack` 标题(约 L434 与 L445)。删除**第一个**块(从第一个 `# Codex + gstack` 起,到第二个 `# Codex + gstack` 之前的全部行),**保留第二个**块(含编号搜索顺序 + 工具映射,更完整)。删后全文只剩一个 `# Codex + gstack`。
- [ ] **Step 5** commit `docs: fix AGENTS dead datasource-test + MCP archived note + dedupe gstack block`

## Task 3 —(可选,代码)setup.py 死 entry
**Files:** Modify `setup.py`
- [ ] `setup.py` console_scripts `"datasource-test=datasource.cli:test_command"` 引用了不存在的 `datasource.cli` → 删除该 entry(`datasource.cli` 模块已不存在,CLI 死)。若希望保留 CLI 须另行恢复模块,本计划默认删 entry。commit `chore: drop dead datasource-test console_scripts entry`
> 若你只想动文档、不碰 setup.py,跳过本 Task。

## Task 4 — 校验 + 回报
- [ ] `bash run_clean.sh python -m pytest tests/test_manual_template.py tests/test_stage4_docs.py -q 2>&1 | tail -3` 全绿(doc 契约未破)。
- [ ] grep 确认两文档已无 `datasource-test`、AGENTS 只剩一个 `# Codex + gstack`、AGENTS MCP 行已改、CLAUDE 结构化源含 reserve_ratio。
- [ ] 回报:逐处改动确认、doc 契约 passed、是否执行了可选 Task 3。

---

## 评审 checklist
1. CLAUDE/AGENTS 均无 `datasource-test`;AGENTS MCP 行=已归档;CLAUDE 结构化源含 reserve_ratio。
2. AGENTS 只剩一个 `# Codex + gstack` 块(保留更完整的第二份)。
3. **未跨文档裁剪**(两文档各自自足);未动被 doc 契约断言的命令示例。
4. doc 契约测试绿;无代码逻辑改动(除可选 Task 3 删死 entry)。
5. squash 合入 main。

## Self-Review
- 覆盖:accuracy(datasource-test×2 / MCP / reserve_ratio)→ Task1/2;intra-doc 去重(gstack)→ Task2 Step4;可选代码 entry → Task3。✅
- Placeholder:每处给 old→new 原文;命令带 Expected。✅
- 边界:不跨文档去重、不动断言命令、setup.py 可选单列,均显式。✅
