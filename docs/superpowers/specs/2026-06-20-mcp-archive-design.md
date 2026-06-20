# MCP 链路归档(批次 A 遗留延期项)— 设计文档

> Spec for the 2026-06 refactor 收官:批次 A 延期的 MCP 链路归档(`mcp_adapter` / `mcp_tools`)。
> Status: 2026-06-20 设计批准(深挖 + brainstorming)。建在 main `591f5dc`(E2/F1 合入后亦可,无交叠);独立小 PR。

## 1. 目的与定位

把批次 0 审计判定 `unreachable`、批次 A 因测试依赖延期的 MCP 链路归档到 `archive/py_unused/`。`mcp_adapter.py` + `utils/mcp_tools.py` 早已脱离 Stage1–4 主链,仅 `test_fund_flow_pipeline.py` 两段 legacy 测试还 import 它。**纯归档 + 删死测试,零流水线行为改动。**

## 2. 关键源码事实(深挖)
- **主链零 import**:`grep "mcp_adapter|mcp_tools|import mcp" src/datasource`(排除 archive)只命中 `mcp_adapter.py`(import `mcp_tools`)与 `mcp_tools.py` 自身——无任何 stage/engines/utils 消费它们。
- **唯一拖住归档的依赖** = `tests/test_fund_flow_pipeline.py` 两段:
  - `test_stage4_generates_fund_flow_prompts`(~253–274):纯测 `MCPToolAdapter.generate_fund_flow_prompts`(legacy 提示词生成,死路径)。
  - `test_integration_stage1_to_stage4`(~276+):混合——Stage1 `collect_fund_flow`+placeholder(活,但已被 `test_stage1_data_collector.py` 覆盖)+ MCP 提示词步骤(死)。
- **"MCP" 其余 ~25 处命中是 source label / 文档字符串**(如 `"source": "MCP WebSearch实时获取"`、docs、`market_data_contract` 示例),**非代码依赖**,本 PR **不动**。
- `pytest.ini` `testpaths` 已排除 `archive/`(批次 A),归档后文件不被收集。

## 3. 范围

**In scope**
1. `git mv` 归档:`src/datasource/mcp_adapter.py` → `archive/py_unused/datasource/mcp_adapter.py`;`src/datasource/utils/mcp_tools.py` → `archive/py_unused/datasource/utils/mcp_tools.py`(沿用批次 0/A 的 `archive/py_unused/datasource/` 布局)。
2. `tests/test_fund_flow_pipeline.py`:**整删**两段 MCP 测试方法(`test_stage4_generates_fund_flow_prompts` + `test_integration_stage1_to_stage4`),保留文件其余 fund_flow 测试。
3. TODOS.md / 批次 A 处置:把"MCP 链路归档延期"勾为完成。

**Out of scope**
- 改任何流水线/stage/engines 代码(MCP 早已 unreachable)。
- 动 "MCP" source-label 历史字符串(`"MCP WebSearch实时获取"` 等是数据来源标记,保留)。
- 删除而非归档(沿用 archive/ 留痕惯例)。

## 4. 测试 / 安全网
- 删两段 MCP 测试后,`test_fund_flow_pipeline.py` 其余测试仍绿;Stage1 `collect_fund_flow`+placeholder 由 `test_stage1_data_collector.py` 覆盖(无覆盖损失)。
- 归档后 `grep -rn "mcp_adapter|mcp_tools|MCPToolAdapter" src/ scripts/ tests/`(排除 archive)= 零(确认无残留 import)。
- 全量 `pytest -q` 无回归(`archive/` 不被收集;两段死测试已删)。
- 文档契约 `test_manual_template`/`test_stage4_docs` 绿(未动命令文档)。

## 5. 验收
- `mcp_adapter.py`/`mcp_tools.py` 在 `archive/py_unused/datasource/`(+utils/),`src/` 内不存在。
- 两段 MCP 测试已删;`grep` 确认 src/scripts/tests 无 MCPToolAdapter/mcp_adapter/mcp_tools import。
- 全量无回归;TODOS 标记 MCP 归档完成(批次 A 收口)。

## 6. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 误以为 MCP 还被主链用 | §2 grep 证主链零 import;批次 0 已判 unreachable |
| 删 integration test 丢 Stage1 覆盖 | Stage1 collect_fund_flow+placeholder 由 test_stage1_data_collector 覆盖(已 grep 确认) |
| 误删 "MCP" source-label | §3 明确只动 mcp_adapter/mcp_tools 文件 + 两段测试,不碰字符串 |
| archive 文件被 pytest 收集 | pytest.ini testpaths 已排除 archive/(批次 A)|
