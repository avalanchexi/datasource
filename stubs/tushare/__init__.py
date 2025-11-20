import pandas as pd

class _Pro:
    def stock_basic(self, *args, **kwargs):
        return pd.DataFrame(columns=['ts_code'])
    def daily(self, *args, **kwargs):
        return pd.DataFrame(columns=['ts_code', 'trade_date', 'close'])

def set_token(token):
    return None

def pro_api():
    return _Pro()
