# MCP 链路归档 执行计划(批次 A 遗留收口)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。Steps use checkbox (`- [ ]`)。

**Goal:** 把 unreachable 的 `mcp_adapter.py` + `utils/mcp_tools.py` 归档到 `archive/py_unused/`,删除 `test_fund_flow_pipeline.py` 两段唯一依赖它们的 legacy MCP 测试。纯归档,零流水线行为改动。

**Architecture:** `git mv` 两文件到 `archive/py_unused/datasource/`(+utils/)+ 删两段死测试;`pytest.ini` 已排除 archive/ 收集。Stage1 fund_flow 覆盖由 `test_stage1_data_collector.py` 保留。

**Tech Stack:** Python;pytest;git worktree;Windows + WSL。

> Spec:`docs/superpowers/specs/2026-06-20-mcp-archive-design.md`(§2 源码事实 / §3 范围)。建在 main `591f5dc`;独立 worktree。

---

## 偏离声明
- 纯归档 + 删死测试;不改流水线/stage/engines 代码;不动 "MCP" source-label 历史字符串。
- 用 `git mv`(留痕,非删除)。

## 环境头(零上下文)
- **Bash 工具坏**;命令经 `wsl -e bash -lc '...'`;pytest 走 `run_clean.sh`;只读 git 用 PowerShell。worktree 根执行。
- worktree:`git worktree add .worktrees/codex-mcp-archive -b codex/mcp-archive main` + 置备 `.env`/`.venv`/`logs`/`reports` + `DATASOURCE_AUTO_VENV=1 DATASOURCE_INSTALL_DEV=1`。
- 硬约束:不重跑真实流水线/Tavily;不碰 `data/runs`/`data/trend_history`;离线。
- Commit:Conventional(`refactor:`/`test:`)。

## Task 0 — worktree + baseline
- [ ] 建 worktree + `bash run_clean.sh python -m pytest -q 2>&1 | tail -4`(记 baseline N)。失败→停-回报。

## Task 1 — 归档 + 删死测试
**Files:** `git mv` `src/datasource/mcp_adapter.py`、`src/datasource/utils/mcp_tools.py`;Modify `tests/test_fund_flow_pipeline.py`
- [ ] **Step 1** 归档:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-mcp-archive && mkdir -p archive/py_unused/datasource/utils && git mv src/datasource/mcp_adapter.py archive/py_unused/datasource/mcp_adapter.py && git mv src/datasource/utils/mcp_tools.py archive/py_unused/datasource/utils/mcp_tools.py && echo moved'
```
- [ ] **Step 2** 删 `tests/test_fund_flow_pipeline.py` 两段 MCP 测试方法整体:`test_stage4_generates_fund_flow_prompts`(~253–274)与 `test_integration_stage1_to_stage4`(~276 到其方法结束);保留文件其余 fund_flow 测试与 import(若文件顶部有 `from src.datasource.mcp_adapter import ...` 顶层 import 也一并删)。
- [ ] **Step 3** py_compile + 确认无残留:
```bash
wsl -e bash -lc 'cd /mnt/d/cursor/datasource/.worktrees/codex-mcp-archive && (rg -n "mcp_adapter|mcp_tools|MCPToolAdapter" src/ scripts/ tests/ -g"!archive/**" || echo "NO-MCP-IMPORT-OK")'
```
Expected:`NO-MCP-IMPORT-OK`(src/scripts/tests 无 MCP 代码引用)。有残留 → 停-回报。
- [ ] **Step 4** commit `refactor: archive unreachable mcp_adapter/mcp_tools; drop legacy MCP tests (batch-A tail)`

## Task 2 — 全量 + 文档
- [ ] **Step 1** 全量 `bash run_clean.sh python -m pytest -q 2>&1 | tail -5`(= baseline N − 2 段 MCP 测试,无其它回归;Stage1 fund_flow 覆盖由 test_stage1_data_collector 保留)。失败 → 停-回报。
- [ ] **Step 2** TODOS.md 把批次 A「MCP 链路归档延期」与全局收尾相关项勾为完成(`- [x] MCP 链路归档:mcp_adapter/mcp_tools → archive/py_unused/datasource;删 test_fund_flow_pipeline 两段 legacy MCP 测试;主链零 import`)。commit `docs: mark MCP link archival complete (batch-A tail)`

## Task 3 — 隔离 + 回报
- [ ] 隔离:`git status --short` 仅本 PR 文件(2 个 git mv + test_fund_flow_pipeline + TODOS);无 data/reports 业务产物。
- [ ] 回报:commit 列表、全量 passed(对比 baseline 少 2 段 MCP)、NO-MCP-IMPORT-OK 确认、归档路径。

---

## 评审 checklist
1. `mcp_adapter.py`/`mcp_tools.py` 在 `archive/py_unused/datasource/`(+utils/);src/ 内不存在;`git mv` 留痕。
2. 两段 MCP 测试整删 + 顶层 MCP import(若有)删;`grep` 确认 src/scripts/tests 零 MCPToolAdapter/mcp_adapter/mcp_tools。
3. 不动流水线代码、不动 "MCP" source-label 字符串、不动 pring_result_contract。
4. 全量无回归(除已删 2 段);Stage1 fund_flow 覆盖仍在(test_stage1_data_collector)。
5. 合入 main 之上 squash;清 worktree/分支。

## Self-Review
- Spec 覆盖:§3 in-scope → Task 1/2;§4 安全网 → Task 1 Step3 + Task 2。✅
- Placeholder:git mv 命令 + 删测试定位 + grep 兜底 + Expected 全给。✅
- 一致性:归档路径、grep 断言、分支名一致。✅
- 风险:主链零 import(grep 证)、Stage1 覆盖保留、只动两文件+两测试,均显式。✅
