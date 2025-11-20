import pandas as pd

def _empty_df(columns=None):
    if columns is None:
        columns = []
    return pd.DataFrame(columns=columns)

def stock_info_a_code_name(*args, **kwargs):
    return _empty_df(["代码", "名称"])

def stock_zh_a_hist(*args, **kwargs):
    return _empty_df(["日期", "收盘"])

def stock_zh_a_spot_em(*args, **kwargs):
    return _empty_df(["代码", "最新价"])

def index_zh_a_hist(*args, **kwargs):
    dates = pd.date_range("2024-01-01", periods=500, freq="B")
    base_price = 3000
    values = base_price * (1 + 0.0005) ** range(len(dates))
    return pd.DataFrame({
        "日期": dates.strftime("%Y-%m-%d"),
        "收盘": values
    })

def stock_financial_abstract(*args, **kwargs):
    return _empty_df(["code", "指标"])
