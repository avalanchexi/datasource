# 数据源集成框架

统一的金融数据源集成框架，支持 AKShare 和 TuShare 数据源的无缝切换和故障转移。

## 特性

- 🔄 **统一接口**: 为不同数据源提供一致的API接口
- 🚀 **异步支持**: 基于 asyncio 的高性能异步操作
- 🔁 **故障转移**: 自动在数据源之间切换，确保服务可用性
- ⚡ **速率限制**: 智能的请求频率控制，避免被限流
- 💾 **缓存支持**: 内存缓存减少重复请求，提高响应速度
- 🔄 **重试机制**: 自动重试失败的请求
- 📊 **批量操作**: 支持批量数据获取
- 🛡️ **错误处理**: 完善的错误处理和日志记录
- 🔍 **库存周期验证**: 基于PPI、CPI、PMI数据的宏观基本面验证
- 📈 **V2.1 Pring分析增强**: 集成库存周期矫正的智能商品信号判定
- 🎯 **投资决策支持**: 技术面35% + 库存周期65%双重验证，避免误判风险
- 🧠 **智能阈值设计**: ≥70分Bullish，≤30分Bearish，30-70分Neutral
- 📅 **最新数据获取**: 动态获取国家统计局最新发布的统计数据
- 🤖 **智能提示系统**: 自动生成最新统计数据获取提示词

## 支持的数据源

### AKShare
- 免费开源的金融数据源
- 丰富的数据接口
- 无需注册即可使用

### TuShare
- 专业的金融数据服务
- 需要注册获取 Token
- 提供更稳定的数据服务

## 贡献指南

有关目录结构、开发流程和提交规范，请阅读 [AGENTS.md](AGENTS.md)。

## 安装

1. 创建并激活本地虚拟环境（推荐）：
```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装项目依赖：
```bash
pip install -r requirements.txt
pip install -e .
pip install -e ".[dev]"  # 包含测试、格式化、类型检查工具
```

3. 配置环境变量（可选）：
```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 TuShare Token、TAVILY_API_KEY 与 DEEPSEEK_API_KEY
# 可运行 `bash run_clean.sh python scripts/tools/stage2_setup_search_env.py` 验证密钥与网络连通性
```

## 快速运行 Stage2（structured-provider-first + Tavily + DeepSeek/Regex）
- 运行前：`bash run_preflight.sh`；可选健康检查 `bash run_clean.sh python scripts/tools/stage2_health_check.py`（检查 Tavily/DeepSeek key、代理、缓存路径可写、基础连通性）。
- 下列示例默认已设置 `DATE=$(date +%Y-%m-%d)` 与 `DATE_NH=${DATE//-/}`。
- Stage2 uses structured-provider-first for known official or structured indicators, with provider-level fallback for the same key, then falls back to Tavily-first search, Exa quota/rate/payment failover, and DeepSeek/regex extraction. Current structured sources include Trading Economics, Stooq GSG CSV, ChinaMoney USDCNY JSON, and NBS/PBC detail pages. 排障可加 `--disable-structured-providers` 回到原搜索链路。
- 速度优先（regex，无 LLM）：
```bash
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --execute-search --phase all --fund-flow-backend tavily \
  --extraction-backend regex --disable-extract \
  --deepseek-timeout 8 --llm-hard-timeout 10 --deepseek-max-concurrency 0 \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json" \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json"
```
- 精度模式：保留 structured-provider-first，改用 `--extraction-backend deepseek --deepseek-model deepseek-v4-pro`；LangChain 默认禁用，如需实验需加 `--allow-langchain`。
- Tavily extract 422/配额：可保留 `--disable-extract` 或调低 `--extract-topk 1`，先 search-only 再 regex 兜底。

## 测试

```bash
pytest -q
python tests/test_datasource.py
```

历史专项脚本已归档至 `archive/py_unused/legacy/`，仅作历史参考，不在当前 Stage1-4 流程执行；当前主路径优先使用 Stage1-4 脚本。

快速测试脚本示例

```bash
# Pring 分析快速验证（tests/scripts）
bash run_clean.sh python scripts/stage3_pring_analyzer.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --output "data/runs/${DATE_NH}/pring_result.json" \
  --allow-estimated \
  --skip-fund-flow-check

# 正式报告生成
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade
```



## 快速开始

### 基本使用

```python
import asyncio
from datasource import get_manager

async def main():
    # 获取管理器实例
    manager = get_manager()
    
    # 检查数据源状态
    status = manager.get_status()
    print(f"管理器状态: {status}")
    
    # 获取股票基本信息
    response = await manager.get_stock_basic()
    if response.error:
        print(f"错误: {response.error}")
    else:
        print(f"成功获取数据，来源: {response.source}")
        print(f"数据行数: {len(response.data)}")

asyncio.run(main())
```

### 获取股票日线数据

```python
import asyncio
from datetime import datetime, timedelta
from datasource import get_manager

async def get_daily_data():
    manager = get_manager()
    
    # 设置日期范围
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # 获取平安银行(000001)的日线数据
    response = await manager.get_stock_daily("000001", start_date, end_date)
    
    if response.error:
        print(f"错误: {response.error}")
    else:
        print(f"成功获取数据，来源: {response.source}")
        print(response.data.head())

asyncio.run(get_daily_data())
```

### 统一报告生成（V2.0重构）

```bash
# 当前报告生成入口（Stage4）
bash run_clean.sh python scripts/stage4_report_generator.py \
  --market-data "data/runs/${DATE_NH}/market_data_complete.json" \
  --pring-result "data/runs/${DATE_NH}/pring_result.json" \
  --output "reports/${DATE}-背景扫描120.md" \
  --allow-fund-flow-downgrade

# 历史简单报告脚本已归档：archive/py_unused/root/generate_report_simple.py（诊断/回溯用，不在当前流程执行）

# 历史扫描器已归档，仅历史参考，不在当前 Stage1-4 流程执行
# 原路径: scripts/legacy/market_scanner_unified.py
# 归档路径: archive/py_unused/legacy/market_scanner_unified.py

# Stage2 一体化增强（structured-provider-first + Tavily + DeepSeek 骨架）
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"

# 重跑指定缺口（示例）
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --resume-from-task-file "data/runs/${DATE_NH}/search_tasks_stage2.jsonl" \
  --tasks industrial,bdi \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"

# 仅补资金流向（选择 Tavily 后端）
bash run_clean.sh python scripts/stage2_unified_enhancer.py \
  --market-data "data/runs/${DATE_NH}/market_data.json" \
  --output "data/runs/${DATE_NH}/market_data_stage2.json" \
  --tasks northbound,southbound,etf \
  --phase all --execute-search \
  --fund-flow-backend tavily \
  --cache-backend sqlite --cache-path data/cache/tavily_cache.sqlite \
  --websearch-results "data/runs/${DATE_NH}/websearch_results_auto.json" \
  --log-output "logs/runs/${DATE_NH}/stage2_unified_log.json" \
  --gap-monitor "data/runs/${DATE_NH}/gap_monitor.json"

# 资金流向为零值时：写入 Stage2.5 manual/WebSearch JSON 后注入
bash run_clean.sh python scripts/stage2_5_injector.py \
  "data/runs/${DATE_NH}/market_data_stage2.json" \
  "data/runs/${DATE_NH}/websearch_results_manual.json" \
  "data/runs/${DATE_NH}/market_data_complete.json"

# 工具脚本 (保留入口见 scripts/tools/；历史 utility 已归档)
# get_real_economic_data.py 已移除，不再作为可执行工具命令
# calculate_na_data.py 已归档至 archive/py_unused/scripts_utility/，不作为当前命令
# generate_background_scan.py 已归档至 archive/py_unused/scripts_utility/，不在当前流程执行
# background_scan_120d_generator.py 已归档至 archive/py_unused/scripts_utility/，不作为补数入口
```

**V2.0 重构特色功能**：
- 🏗️ **统一配置管理**: 配置化驱动，消除硬编码，便于维护和扩展
- 🔧 **统一市场扫描**: 基于配置的技术指标计算，支持多市场扩展
- 📊 **多数据源集成**: UnifiedReportGenerator整合经济、市场、技术多维数据
- ⚡ **代码质量提升**: 删除871行重复代码，提高可维护性
- 🔄 **自动获取最新数据**: 国家统计局PPI、CPI、PMI数据实时更新
- 📈 **库存周期验证**: 技术面+宏观面双重验证机制
- 📝 **智能报告生成**: 自动化多格式报告输出（Markdown/JSON）

### 批量获取数据

```python
import asyncio
from datasource import get_manager

async def batch_get_data():
    manager = get_manager()
    
    # 批量获取多只股票的数据
    symbols = ["000001", "000002", "000858"]
    start_date = "2023-12-01"
    end_date = "2023-12-31"
    
    results = await manager.batch_get_stock_daily(symbols, start_date, end_date)
    
    for symbol, response in results.items():
        if response.error:
            print(f"股票 {symbol}: 获取失败 - {response.error}")
        else:
            print(f"股票 {symbol}: 获取成功，{len(response.data)} 条数据")

asyncio.run(batch_get_data())
```

### 自定义配置

```python
from datasource import DataSourceManager, DataSourceType

# 创建自定义管理器
manager = DataSourceManager()

manager.add_data_source(DataSourceType.TUSHARE)

# 设置主数据源和备用数据源
manager.set_primary_source("tushare")
```

## API 接口

### DataSourceManager

主要的数据源管理类，提供统一的数据接口。

#### 方法

- `add_data_source(source_type, config=None)`: 添加数据源
- `set_primary_source(source_name)`: 设置主数据源
- `add_fallback_source(source_name)`: 添加备用数据源
- `get_stock_basic(**kwargs)`: 获取股票基本信息
- `get_stock_daily(symbol, start_date, end_date, **kwargs)`: 获取股票日线数据
- `get_stock_realtime(symbols, **kwargs)`: 获取股票实时数据
- `get_index_daily(symbol, start_date, end_date, **kwargs)`: 获取指数日线数据
- `get_financial_data(symbol, **kwargs)`: 获取财务数据
- `batch_get_stock_daily(symbols, start_date, end_date, **kwargs)`: 批量获取股票日线数据
- `check_availability()`: 检查数据源可用性
- `get_status()`: 获取管理器状态

### DataResponse

数据响应对象，包含以下字段：

- `data`: pandas.DataFrame - 数据内容
- `source`: str - 数据来源
- `timestamp`: datetime - 响应时间
- `error`: str - 错误信息（如果有）
- `metadata`: dict - 元数据信息

## 配置说明

### 环境变量

在 `.env` 文件中配置以下变量：

```bash
# TuShare API Token（必填，如果使用TuShare）
TUSHARE_TOKEN=your_tushare_token_here  # 请仅在本地 .env 设置，代码中不要硬编码

# 速率限制设置
TUSHARE_RATE_LIMIT=5       # TuShare 每秒请求数

# 缓存设置
CACHE_ENABLED=true         # 是否启用缓存
CACHE_TTL=300             # 缓存过期时间（秒）
```

### TuShare Token 获取

1. 访问 [TuShare官网](https://tushare.pro/)
2. 注册账户
3. 在个人中心获取 Token
4. 将 Token 配置到 `.env` 文件中

## 项目结构

项目已经重新组织为清晰的目录结构，并完成了文档整合优化（减少57%的MD文件数量）：

```
datasource/
├── src/datasource/                 # 核心代码库
│   ├── __init__.py                # 主模块导出
│   ├── manager.py                 # 数据源管理器
│   ├── models/base.py             # 基础模型定义
│   ├── config/                    # 🆕 统一配置管理（V2.0新增）
│   │   ├── __init__.py            # 配置模块导出
│   │   └── indices_config.py      # 金融工具、技术参数配置
│   ├── adapters/                  # 数据源适配器（AKShare/TuShare）
│   ├── utils/                     # 速率限制/重试工具
│   ├── cache/                     # 内存缓存
│   ├── calculators/               # 技术指标/债券/资金流/普林格分析
│   ├── engines/                   # 数据引擎
│   └── generators/                # 报告生成器
├── docs/                          # 📚 文档中心
│   ├── README.md                  # 文档导航索引
│   ├── 系统技术文档.md             # 完整技术参考
│   ├── history/                   # 历史报告/分析文档
│   └── archive/                   # 历史文档归档
├── reports/                       # 📊 生成报告输出目录
├── tests/                         # 🧪 默认 pytest 测试集
│   ├── simple_test.py             # 简单测试
│   ├── test_datasource.py         # 集成测试入口
│   ├── test_fund_flow_pipeline.py # 当前资金流/MCP 混合测试
│   └── integration/               # 保留的集成测试
├── scripts/                       # 🔧 Stage1-4 与诊断脚本
│   ├── stage1_data_collector.py
│   ├── stage2_unified_enhancer.py
│   ├── stage2_5_injector.py
│   ├── stage3_pring_analyzer.py
│   ├── stage4_report_generator.py
│   ├── utility/                   # 当前保留的手工/辅助工具
│   └── archive/                   # 归档/手工分析脚本，不跑正常 Stage1-4
├── templates/                     # 📝 报告模板
├── assets/                        # 🖼️ 图片和静态资源
├── data/                          # 💾 数据文件和样本
└── README.md                      # 项目主要说明（本文档）
```

## 错误处理

框架提供了完善的错误处理机制：

1. **自动重试**: 请求失败时自动重试，支持指数退避
2. **故障转移**: 主数据源失败时自动切换到备用数据源
3. **详细错误信息**: 提供详细的错误描述和调试信息
4. **超时处理**: 防止请求长时间阻塞

## 性能优化

1. **异步操作**: 基于 asyncio 的异步I/O，提高并发性能
2. **速率限制**: 智能控制请求频率，避免被限流
3. **缓存机制**: 内存缓存减少重复请求
4. **批量操作**: 支持批量数据获取，提高效率
5. **连接池**: 复用HTTP连接，减少连接开销

## 注意事项

1. **数据源限制**: 不同数据源有不同的访问限制，请遵守相应的使用条款
2. **Token管理**: TuShare Token 应妥善保管，不要泄露
3. **网络环境**: 确保网络连接稳定，某些数据源可能需要特殊的网络环境
4. **数据格式**: 不同数据源返回的数据格式可能略有差异，使用时请注意
5. **更新频率**: 实时数据的更新频率取决于数据源的更新策略

## 故障排除

### 常见问题

1. **TuShare Token 错误**
   - 检查 Token 是否正确配置
   - 确认 Token 是否有效且未过期

2. **网络连接问题**
   - 检查网络连接
   - 尝试更换网络环境

3. **数据获取失败**
   - 检查股票代码格式是否正确
   - 确认日期范围是否合理
   - 查看错误日志了解具体原因

4. **速率限制**
   - 降低请求频率
   - 增加重试间隔

## 📖 文档导航

文档中心保留当前流程说明、技术参考和历史归档入口。

### 🎯 核心文档
- **[文档索引](docs/README.md)** - 完整的文档导航中心
- **[系统技术文档](docs/系统技术文档.md)** - 完整技术参考
- **[AI报告生成标准流程](docs/AI报告生成标准流程_V3.3.md)** - 报告生成流程
- **[AI背景扫描报告执行完整手册](docs/AI背景扫描报告执行完整手册.md)** - 背景扫描执行手册

### 📚 技术参考
系统技术文档包含：
- 技术指标计算详解（含库存周期验证框架）
- 商品趋势双重验证机制（技术面35% + 库存周期65%）
- 每日市场扫描系统架构
- 数据源接口说明
- 报告生成流程和文件关系

### 🔧 开发支持
开发支持内容覆盖：
- Claude Code开发规范
- 项目架构说明
- 文件分类和组织结构
- 环境配置和依赖管理

### 📊 实用资源
- **[测试脚本](tests/)** - 功能测试和使用示例
- **[独立脚本](scripts/)** - 增强功能和工具脚本
- **[历史报告/分析文档](docs/history/)** - 项目发展记录和历史分析
- **[归档文档](docs/archive/)** - 历史文档归档

### 🚀 快速入门路径
1. 📚 **项目概况**: 阅读本README了解整体功能
2. 🔧 **开发环境**: 查看[文档索引](docs/README.md)设置环境
3. 📖 **技术深度**: 参考[系统技术文档](docs/系统技术文档.md)理解架构
4. 📋 **工作流程**: 使用[AI报告生成标准流程](docs/AI报告生成标准流程_V3.3.md)执行任务
5. 💡 **样例参考**: 查看[历史报告/分析文档](docs/history/)了解输出形态

## 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进项目。

## 更新日志

### v2.1.0 (2025-09-11) - Pring分析智能化升级
- **🧠 Pring分析增强**: 集成库存周期矫正，商品信号智能化判定，避免纯技术面误判
- **🔧 双重验证机制**: 技术面35% + 库存周期65%，科学化决策框架
- **🎯 智能阈值设计**: ≥70分Bullish，≤30分Bearish，30-70分Neutral，避免假突破
- **📊 透明评分体系**: 完整的评分过程和数据来源可追溯
- **⚠️ 风险控制机制**: 基本面评分<35分强制判定Neutral，防范投资风险
- **🔄 算法优化**: PringAnalyzer类增强，支持库存周期矫正权重配置
- **📈 实战验证**: 2025年9月11日验证案例，成功避免技术面误导的重配风险
- **🔧 配置集成**: V2.1功能完全兼容V2.0统一配置管理系统
- **📝 文档全面更新**: 系统技术文档、开发文档、工作流模板、报告样例全面更新

### v2.0.0 (2025-09-11) - 重大重构版本
- **架构重构**: 创建统一配置管理系统，消除硬编码问题
- **代码优化**: 删除871行重复代码，合并重复功能脚本
- **新增**: `src/datasource/config/indices_config.py` - 统一金融工具配置管理
- **重构**: `scripts/market_scanner_unified.py` - 统一市场扫描器，替代多个重复脚本
- **增强**: `generate_report_simple.py` - 转换为UnifiedReportGenerator，支持多数据源集成
- **清理**: 移除低质量和重复脚本，提高代码质量和可维护性
- **配置化**: 所有技术参数和指数映射改为配置驱动，便于维护和扩展
- **统一接口**: 所有扫描和计算功能使用统一的配置和接口
- **文档更新**: 同步更新CLAUDE.md和项目文档，保持一致性

### v1.2.0 (2025-09-10)
- **新增**: 最新统计数据获取功能，基于当前日期动态更新
- **新增**: `update_latest_data.py` 完整数据更新流程和摘要生成
- **优化**: `get_real_economic_data.py` 增强数据获取提示和时效性验证
- **优化**: `calculate_na_data.py` 集成最新库存周期验证数据
- **优化**: `generate_report_simple.py` 自动集成最新宏观数据到技术分析报告
- **新增**: 智能提示系统，自动生成最新统计数据获取提示词
- **文档**: 全面更新工作流模板、开发文档、系统技术文档

### v1.1.0 (2025-09-10)
- **新增**: 库存周期验证框架，基于PPI、CPI、PMI数据的宏观基本面验证
- **新增**: 商品趋势双重验证机制（技术面35% + 库存周期65%）
- **优化**: 背景扫描V3.1和日报生成模板，集成库存周期分析和双重验证机制
- **新增**: 普林格六阶段经济周期判断与投资决策标准
- **文档**: 完善技术指标计算说明和库存周期验证标准文档

### v1.0.0
- 初始版本
- 支持 AKShare 和 TuShare 数据源
- 实现统一的数据接口
- 提供故障转移和缓存功能
