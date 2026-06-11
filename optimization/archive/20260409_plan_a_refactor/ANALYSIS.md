# 核心分析报告 — 市场背景扫描工具优化

**日期**: 2026-04-09  
**分析范围**: 全项目代码审查（Stage1-4 + 配套脚本）  
**分析方法**: 独立代码审查，无工具辅助，基于源码实证

---

## 一、项目全貌

### 真实价值链

```
本地 Python 流水线                     ChatGPT GPTs（背景信息）
────────────────────────              ────────────────────────────
Stage1: TuShare API 采集              用户上传持仓文件 (.xlsx/.csv)
Stage2: Tavily+DeepSeek 增强     ──→  手动上传知识文件（每日摩擦点）
Stage2.5: 手工注入补缺                   ↓
Stage3: Pring 六阶段分析              GPT "资产日报专家":
Stage4: 生成 背景扫描120.md  ────→    普林格阶段判定 + 行动矩阵输出
```

### 规模

| 指标 | 数值 |
|------|------|
| 核心代码行数 | ~15,000 行 |
| scripts/ 脚本总数 | 32 个 |
| 主流水线实际使用脚本 | 5 个 |
| 最大单文件 | stage2_unified_enhancer.py（3,713 行）|
| inject 脚本 | 3,167 行（含 207 行未提交修改）|

---

## 二、问题诊断

### 问题1：生产代码命名混乱（已修复）

**文件**: `inject_websearch_data_test.py`（3,167 行）

这是每日 Stage2.5 的核心入口脚本，但文件名带 `_test` 后缀。操作文档里的命令：

```bash
python inject_websearch_data_test.py data/xxx_stage2.json reports/xxx_manual.json data/xxx_complete.json
```

任何人第一眼看到这个命令都会困惑：这是在运行测试还是生产流程？

**影响**: 认知混乱、新人上手障碍、IDE 可能将其归类为测试文件。

**结论**: 重命名为 `scripts/stage2_5_injector.py`。

---

### 问题2：Stage4 gap_monitor 路径静默失败

**文件**: `scripts/stage4_report_generator.py:55`

```python
gap_path = Path("reports/gap_monitor.json")   # 硬编码无日期版本
if gap_path.exists():                          # 不存在就静默跳过
    ...
```

流水线实际生成的是 `reports/gap_monitor_20260408.json`（带日期），无日期版本通常不存在。结果：Stage4 每次都静默跳过 gap 校验，在数据不完整时照常生成报告。

**这是最危险的那类 bug**：不报错，也没工作。

**验证**: 查看 reports/ 目录实际文件：
```
gap_monitor_20260309.json
gap_monitor_20260316.json
gap_monitor_20260317.json
gap_monitor_20260324.json
```
无一是 `gap_monitor.json`（无日期版本）。Stage4 的校验从来没有真正运行过。

---

### 问题3：inject 脚本 is_estimated 跳过边缘情况

**文件**: `scripts/stage2_5_injector.py`（原 inject_websearch_data_test.py）

**背景**: inject 脚本有 `_remove_top_missing()` 函数，负责注入成功后清理顶层 `missing_items` list。该函数在多处被正确调用：

```
_remove_top_missing 调用点: 591, 1030, 1051, 1068, 1090, 1116, 1140, 1148, 1178, 1245, 1248
```

**但存在一个边缘情况**：当指标已有 `current_value`（即使 `is_estimated=True`），inject 脚本判断"已有值，跳过注入"——此时**不调用** `_remove_top_missing`。

结果：顶层 `missing_items` list 中该 key 残留，Stage3 的 policy gate 读取这个 list，判定数据缺失，阻断流水线。

用户必须手动执行：
```python
python3 -c "
import json; p='data/${DATE}_market_data_complete.json'
d=json.load(open(p))
d['missing_items']=[x for x in d.get('missing_items',[]) if x.get('key')!='bdi']
json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)
"
```

**关键判断**：这不是文档问题。CLAUDE.md 里有专门的"操作陷阱"章节解释如何手动修复——这说明代码本身需要修复。

**修复方向**：在各 `_apply_*` 函数的跳过分支里，当已有有效值时，仍调用 `_remove_top_missing`：

```python
if _should_skip(entry):
    if _has_valid_value(entry.get("current_value")):
        _remove_top_missing(market_data, key)  # ← 补上这一行
    continue
```

---

### 问题4：scripts/ 脚本增殖

**当前状态**: 32 个脚本，主流水线只用 5 个。

非主流水线脚本（旧版流程 / 废弃路径）：

| 脚本 | 废弃原因 |
|------|---------|
| `background_scan_120d.py` | 旧版流程，已被 Stage1-4 替代 |
| `background_scan_unified.py` | 同上 |
| `market_scanner_unified.py` | 功能重叠 |
| `enhanced_market_scan.py` | 功能重叠 |
| `stage2_mcp_enhancer.py` | MCP 路径已废弃 |
| `mcp_data_enhancer.py` | MCP 路径已废弃 |
| `fill_market_data_from_yahoo.py` | Yahoo 数据源已弃用 |
| `ai_execution_steps.py` | 无引用 |
| `run_background_scan_pipeline.py` | 旧版编排脚本 |

这些文件制造认知负担：打开 scripts/ 目录时需要判断哪些是"当前的"、哪些是"旧的"。

---

### 问题5（计划外发现）：20+ 个文件未提交

运行分析时发现 git 工作区有大量未提交修改：

```
M AGENTS.md
M CLAUDE.md
M inject_websearch_data_test.py  （207行修改）
M scripts/stage2_unified_enhancer.py
M scripts/stage3_pring_analyzer.py
M src/datasource/config/search_profiles.py
M src/datasource/engines/stage2_task_planner.py
... 共20+个文件
```

其中 `inject_websearch_data_test.py` 有 191 行新增，这些是有价值的进行中工作，重命名时已完整保留。

---

## 三、分析过程中的关键验证

### 验证1：missing_items 双层结构

**计划初稿判断**：inject 脚本不同步两个结构，需要添加同步逻辑。

**代码实证**：

```bash
grep -n "_remove_top_missing" inject_websearch_data_test.py
# 结果：11处调用，函数定义在第336行
```

**修正**：函数已存在且被调用，不是"完全没有同步"，而是特定边缘情况（is_estimated 跳过时）没有调用。计划因此从"重构双层结构"缩小为"10行边缘情况修复"。

### 验证2：gap_monitor 静默失败

**代码实证**：

```python
# stage4_report_generator.py:55
gap_path = Path("reports/gap_monitor.json")
```

```bash
ls reports/gap_monitor*.json
# gap_monitor_20260309.json, gap_monitor_20260316.json ...
# 没有无日期版本
```

结论：Stage4 的 gap 校验在所有历史运行中均未触发。

### 验证3：run_background_scan_pipeline.py 已存在

计划中提出新建流水线编排器，但 `scripts/run_background_scan_pipeline.py` 已存在。这意味着方案B（下期）应先读此文件，决定"扩展"还是"新建"，避免重复造轮子。

---

## 四、未纳入本期范围的发现

以下问题在分析中被识别，但超出方案A范围，记录供后续参考：

### 方案B 优先事项：Tavily 配额保护

流水线编排器（`run_daily_pipeline.py`）**必须** 包含以下保护逻辑：

```python
if stage == "NEED_STAGE2":
    if Path(f"data/{nh}_market_data_stage2.json").exists():
        raise RuntimeError(
            f"Stage2 今日已运行（{nh}_market_data_stage2.json 存在）。"
            "请检查 Stage2.5，或用 --force-stage2 强制重跑（消耗当日 Tavily 配额）"
        )
```

Tavily 每日限额是不可恢复资源，编排器误判"Stage2 未运行"会造成永久损失。

### 长期：stage2_unified_enhancer.py 拆分

3,713 行的单体脚本，混合了 CLI 解析、Tavily 调用、DeepSeek 抽取、缓存管理、gap 监控等全部逻辑。未来可拆分为独立模块，但不在当前范围。

### 测试覆盖缺口

| 缺口 | 优先级 |
|------|--------|
| is_estimated 跳过边缘情况测试 | 高（配合步骤5） |
| Stage4 gap_monitor 路径测试 | 高（配合步骤4） |
| 流水线编排器阶段检测测试 | 中（方案B时新建） |

---

## 五、决策摘要

| 决策 | 选择 | 理由 |
|------|------|------|
| missing_items：重构 vs 修复边缘情况 | 修复边缘情况（10行）| 同步函数已存在，不需要重构 |
| Stage4 gap_monitor：新参数 vs 直接修复 | 两者都做 | 参数支持手动覆盖，自动推断处理默认情况 |
| 方案C（GPT API）：实现 vs 延后 | 延后 | 用户确认为背景信息，不在本次范围 |
| 方案B：本期 vs 下期 | 下期 | 方案A先稳定，编排器需要额外的 Tavily 保护设计 |
