# TuShare WebClient 调用模板（Stage1 专用）

> 目的：在无 GUI/浏览器的 Codex 环境下，提前在有浏览器的机器使用 https://tushare.pro/webclient/ 生成参数正确的调用脚本，粘贴到本仓库或私有脚本中，提升 Stage1 采集成功率。

## 1. CPI（`cn_cpi`）
```python
import tushare as ts
import os
pro = ts.pro_api(os.getenv('TUSHARE_TOKEN'))
df = pro.cn_cpi(start_m='202401', end_m='202510', fields='month,nt_yoy,nt_mom,nt_val')
print(df.tail())
```
- `start_m/end_m`：保持 YYYYMM 格式；Stage1 默认回溯 18 个月。
- `fields`：至少包含 `nt_yoy`（全国当月同比），否则 Stage1 会再次降级到 WebSearch。

## 2. PMI（`cn_pmi`）
```python
import tushare as ts
import os
pro = ts.pro_api(os.getenv('TUSHARE_TOKEN'))
df = pro.cn_pmi(start_m='202401', end_m='202510')
df.columns = [c.lower() for c in df.columns]
print(df[['month','pmi010100','pmi010400','pmi010500']].tail())
```
- `pmi010100`：制造业 PMI 总值。
- `pmi010400`：生产指数。
- `pmi010500`：新订单指数。
- 拷贝上述列名到 `scripts/stage1_data_collector.py:self.pmi_column_map`，确保 Stage1 能精准匹配。

## 3. 融资融券（`margin`）
```python
import tushare as ts
import os
pro = ts.pro_api(os.getenv('TUSHARE_TOKEN'))
frames = []
for exch in ['SSE','SZSE']:
    part = pro.margin(exchange_id=exch, start_date='20240501', end_date='20251119', fields='trade_date,exchange_id,rzye,rzrqye')
    frames.append(part)
df = ts.concat(frames)
df['trade_date'] = pd.to_datetime(df['trade_date'])
print(df.head())
```
- Stage1 需要 `trade_date` + `rzrqye`，用于计算近 5 / 120 个交易日的余额变化。
- 若发现字段名有变更，请在 `TuShareAdapter.get_margin_total` 中同步修改。

> 使用建议：
> 1. 在 WebClient 中生成并测试代码片段后，将其保存到本文件或个人笔记，确保 token/参数填写正确。
> 2. 若某接口返回空值，优先检查账号积分/权限，其次核对 `start/end` 参数是否超出官方数据范围。
> 3. 需要新增接口时，先在 WebClient 验证，再在 Stage1 的配置/映射中补充字段，避免生产流程出现大量 `N/A`。
