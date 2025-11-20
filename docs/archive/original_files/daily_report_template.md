# 每日市场数据报告

**报告日期**: {{report_date}}
**生成时间**: {{generate_time}}
**数据来源**: {{data_sources}}

## 主要指数表现

| 指数名称 | 代码   | 最新价       | 涨跌额        | 涨跌幅(%)         | 成交量(亿)    | 成交额(亿)    |
| -------- | ------ | ------------ | ------------- | ----------------- | ------------- | ------------- |
| 上证指数 | 000001 | {{sh_price}} | {{sh_change}} | {{sh_pct_change}} | {{sh_volume}} | {{sh_amount}} |
| 深证成指 | 399001 | {{sz_price}} | {{sz_change}} | {{sz_pct_change}} | {{sz_volume}} | {{sz_amount}} |
| 创业板指 | 399006 | {{cy_price}} | {{cy_change}} | {{cy_pct_change}} | {{cy_volume}} | {{cy_amount}} |
| 科创50   | 000688 | {{kc_price}} | {{kc_change}} | {{kc_pct_change}} | {{kc_volume}} | {{kc_amount}} |

## 市场概况

### 涨跌分布

| 市场   | 上涨家数  | 下跌家数    | 平盘家数    | 涨停家数        | 跌停家数          | 涨跌比               |
| ------ | --------- | ----------- | ----------- | --------------- | ----------------- | -------------------- |
| 沪市   | {{sh_up}} | {{sh_down}} | {{sh_flat}} | {{sh_limit_up}} | {{sh_limit_down}} | {{sh_up_down_ratio}} |
| 深市   | {{sz_up}} | {{sz_down}} | {{sz_flat}} | {{sz_limit_up}} | {{sz_limit_down}} | {{sz_up_down_ratio}} |
| 创业板 | {{cy_up}} | {{cy_down}} | {{cy_flat}} | {{cy_limit_up}} | {{cy_limit_down}} | {{cy_up_down_ratio}} |

### 行业表现 TOP 10

| 排名                | 行业名称          | 涨跌幅(%)           | 领涨股票       | 股票代码      | 股票涨幅(%)     |
| ------------------- | ----------------- | ------------------- | -------------- | ------------- | --------------- |
| {{#industry_top10}} |                   |                     |                |               |                 |
| {{rank}}            | {{industry_name}} | {{industry_change}} | {{lead_stock}} | {{lead_code}} | {{lead_change}} |
| {{/industry_top10}} |                   |                     |                |               |                 |

## 个股热点

### 涨幅榜 TOP 20

| 排名             | 股票名称 | 代码     | 最新价    | 涨跌幅(%)      | 成交量(万手) | 成交额(亿) | 换手率(%)    |
| ---------------- | -------- | -------- | --------- | -------------- | ------------ | ---------- | ------------ |
| {{#top_gainers}} |          |          |           |                |              |            |              |
| {{rank}}         | {{name}} | {{code}} | {{price}} | {{pct_change}} | {{volume}}   | {{amount}} | {{turnover}} |
| {{/top_gainers}} |          |          |           |                |              |            |              |

### 跌幅榜 TOP 20

| 排名            | 股票名称 | 代码     | 最新价    | 涨跌幅(%)      | 成交量(万手) | 成交额(亿) | 换手率(%)    |
| --------------- | -------- | -------- | --------- | -------------- | ------------ | ---------- | ------------ |
| {{#top_losers}} |          |          |           |                |              |            |              |
| {{rank}}        | {{name}} | {{code}} | {{price}} | {{pct_change}} | {{volume}}   | {{amount}} | {{turnover}} |
| {{/top_losers}} |          |          |           |                |              |            |              |

### 成交额榜 TOP 20

| 排名            | 股票名称 | 代码     | 最新价    | 涨跌幅(%)      | 成交量(万手) | 成交额(亿) | 换手率(%)    |
| --------------- | -------- | -------- | --------- | -------------- | ------------ | ---------- | ------------ |
| {{#top_volume}} |          |          |           |                |              |            |              |
| {{rank}}        | {{name}} | {{code}} | {{price}} | {{pct_change}} | {{volume}}   | {{amount}} | {{turnover}} |
| {{/top_volume}} |          |          |           |                |              |            |              |

## 资金流向

### 主力资金流向 TOP 10

| 排名                  | 股票名称 | 代码     | 最新价    | 涨跌幅(%)      | 主力净流入(万) | 主力净流入占比(%) |
| --------------------- | -------- | -------- | --------- | -------------- | -------------- | ----------------- |
| {{#money_flow_top10}} |          |          |           |                |                |                   |
| {{rank}}              | {{name}} | {{code}} | {{price}} | {{pct_change}} | {{net_inflow}} | {{inflow_ratio}}  |
| {{/money_flow_top10}} |          |          |           |                |                |                   |

### 北向资金

| 类型   | 今日净买入(亿)          | 今日成交额(亿)         | 本周净买入(亿)         | 本月净买入(亿)          |
| ------ | ----------------------- | ---------------------- | ---------------------- | ----------------------- |
| 沪股通 | {{hgt_net_buy_today}}   | {{hgt_amount_today}}   | {{hgt_net_buy_week}}   | {{hgt_net_buy_month}}   |
| 深股通 | {{sgt_net_buy_today}}   | {{sgt_amount_today}}   | {{sgt_net_buy_week}}   | {{sgt_net_buy_month}}   |
| 合计   | {{total_net_buy_today}} | {{total_amount_today}} | {{total_net_buy_week}} | {{total_net_buy_month}} |

## 两市融资融券

| 项目         | 今日(亿)                 | 昨日(亿)                     | 环比变化(亿)              | 环比变化(%)                   |
| ------------ | ------------------------ | ---------------------------- | ------------------------- | ----------------------------- |
| 融资余额     | {{margin_balance_today}} | {{margin_balance_yesterday}} | {{margin_balance_change}} | {{margin_balance_change_pct}} |
| 融券余额     | {{short_balance_today}}  | {{short_balance_yesterday}}  | {{short_balance_change}}  | {{short_balance_change_pct}}  |
| 融资融券余额 | {{total_balance_today}}  | {{total_balance_yesterday}}  | {{total_balance_change}}  | {{total_balance_change_pct}}  |

|  |  |  |  |  |  |
| - | - | - | - | - | - |

## 数据说明

- 数据来源：{{primary_source}}（主要）、{{secondary_source}}（备用）
- 更新时间：{{last_update_time}}
- 计算方式：
  - 涨跌比 = 上涨家数 / 下跌家数
  - 主力净流入占比 = 主力净流入金额 / 成交额 × 100%
  - N/A 表示数据暂未获取或计算中

---

*本报告由数据源集成系统自动生成*
