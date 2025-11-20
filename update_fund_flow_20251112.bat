@echo off
REM ============================================================
REM 资金流向数据快速更新脚本 - 2025-11-12
REM ============================================================
REM
REM 使用说明：
REM 1. 访问下方数据源URLs获取实时数据
REM 2. 修改本脚本中的金额数值（替换"请替换"部分）
REM 3. 运行本脚本: update_fund_flow_20251112.bat
REM 4. 重新生成报告
REM
REM ============================================================

echo.
echo ============================================================
echo 资金流向数据更新工具 - 2025-11-12
echo ============================================================
echo.

set MARKET_DATA=data\20251112_market_data_final_enhanced.json

REM 检查market_data文件是否存在
if not exist "%MARKET_DATA%" (
    echo [ERROR] 文件不存在: %MARKET_DATA%
    echo 请确认文件路径是否正确
    pause
    exit /b 1
)

echo [步骤1/4] 更新北向资金...
echo.
echo 数据源: https://data.eastmoney.com/hsgt/
echo 已知: 11月12日成交额2260.65亿元
echo.

REM ⚠️ 请替换下面的金额为实际值
python scripts\utility\manual_fund_flow_updater.py ^
  --market-data "%MARKET_DATA%" ^
  --flow-type northbound ^
  --recent-5d "+请替换(如:+132.6亿)" ^
  --total-120d "+请替换(如:+845.2亿)" ^
  --trend "请替换(如:持续流入/震荡/流出)" ^
  --source "东方财富网实时数据" ^
  --note "数据日期: 2025-11-12, 成交额2260.65亿"

if errorlevel 1 (
    echo [ERROR] 北向资金更新失败
    pause
    exit /b 1
)

echo.
echo [步骤2/4] 更新南向资金...
echo.
echo 数据源: https://data.10jqka.com.cn/hgt/ 或 https://sc.hkex.com.hk/
echo.

REM ⚠️ 请替换下面的金额为实际值
python scripts\utility\manual_fund_flow_updater.py ^
  --market-data "%MARKET_DATA%" ^
  --flow-type southbound ^
  --recent-5d "+请替换" ^
  --total-120d "+请替换" ^
  --trend "请替换" ^
  --source "同花顺/港交所数据" ^
  --note "数据日期: 2025-11-12"

if errorlevel 1 (
    echo [ERROR] 南向资金更新失败
    pause
    exit /b 1
)

echo.
echo [步骤3/4] 更新ETF资金流...
echo.
echo 数据源: Wind/Choice终端 或 https://fund.eastmoney.com/data/fundranking.html
echo.

REM ⚠️ 请替换下面的金额为实际值
python scripts\utility\manual_fund_flow_updater.py ^
  --market-data "%MARKET_DATA%" ^
  --flow-type etf ^
  --recent-5d "+请替换" ^
  --total-120d "+请替换" ^
  --trend "请替换" ^
  --source "Wind终端/东方财富" ^
  --note "数据日期: 2025-11-12"

if errorlevel 1 (
    echo [ERROR] ETF资金流更新失败
    pause
    exit /b 1
)

echo.
echo [步骤4/4] 更新融资融券余额...
echo.
echo 数据源: http://www.sse.com.cn/market/stockdata/statistic/
echo         http://www.szse.cn/disclosure/margin/object/index.html
echo.

REM ⚠️ 请替换下面的金额为实际值
python scripts\utility\manual_fund_flow_updater.py ^
  --market-data "%MARKET_DATA%" ^
  --flow-type margin ^
  --recent-5d "+请替换" ^
  --total-120d "+请替换" ^
  --trend "请替换(如:持续增加)" ^
  --source "上交所+深交所" ^
  --note "数据日期: 2025-11-12, 两市余额约1.72-1.75万亿"

if errorlevel 1 (
    echo [ERROR] 融资融券更新失败
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [SUCCESS] 资金流向数据更新完成！
echo ============================================================
echo.
echo 下一步操作：
echo.
echo 1. 验证更新结果：
echo    python -c "import json; data=json.load(open('%MARKET_DATA%', encoding='utf-8')); print(json.dumps(data.get('fund_flow', {}), ensure_ascii=False, indent=2))"
echo.
echo 2. 重新生成报告：
echo    python scripts\stage3_report_generator.py ^
echo      --market-data %MARKET_DATA% ^
echo      --pring-result data\20251112_pring_result_final.json ^
echo      --output reports\20251112背景扫描120_已更新.md
echo.
echo ============================================================
pause
