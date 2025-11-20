# Stage 2a 浼樺寲鎬荤粨 - WebSearch闄嶇骇鏈哄埗

**浼樺寲鏃ユ湡**: 2025-11-12
**鏂囦欢**: `scripts/stage2a_mcp_enhancer.py`
**浼樺寲鐗堟湰**: V3.3澧炲己鐗?

---

## 涓€銆佷紭鍖栬儗鏅?

### 闂鎻忚堪

鍘熷`stage2a_mcp_enhancer.py`鍦∕CP宸ュ叿璋冪敤寮傚父鏃讹紝鍙細璁板綍閿欒骞惰烦杩囨暟鎹～鍏咃紝瀵艰嚧锛?

1. **鏁版嵁瀹屾暣鎬т綆**: MCP寮傚父鏃舵棤澶囩敤鏂规锛屾暟鎹己澶?
2. **Pring鍒嗘瀽澶辫触**: 缂哄皯鍏抽敭鍊哄埜鍜屽晢鍝佹暟鎹紝鏃犳硶瀹屾垚涓夊眰妗嗘灦鍒嗘瀽
3. **鐢ㄦ埛浣撻獙宸?*: 娌℃湁鏄庣‘鐨勬晠闅滃鐞嗘彁绀猴紝鐢ㄦ埛涓嶇煡閬撳浣曡ˉ鏁?

### 鐢ㄦ埛闇€姹?

> "浼樺寲stage2a_mcp_enhancer.py锛屽mcp寮傚父锛屽彲浠ョ洿鎺ラ€氳繃websearch锛岄€氳繃鍙俊鏁版嵁婧愯幏鍙栨暟鎹€?

---

## 浜屻€佸疄鏂芥柟妗?

### 2.1 鏍稿績鎬濊矾

**MCP浼樺厛 + WebSearch闄嶇骇**

```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
鈹?  鏁版嵁璇锋眰    鈹?
鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹?
       鈹?
       鈻?
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?    鎴愬姛
鈹? 灏濊瘯MCP鑾峰彇  鈹傗攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈻? 搴旂敤鏁版嵁
鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹?
       鈹?澶辫触
       鈻?
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
鈹? WebSearch闄嶇骇        鈹?
鈹? - 鏌ユ壘鍙俊鏁版嵁婧?    鈹?
鈹? - 鐢熸垚鎼滅储鎻愮ず璇?    鈹?
鈹? - 璁板綍闄嶇骇鏃ュ織       鈹?
鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?
```

### 2.2 鎶€鏈疄鐜?

#### A. 鍙俊鏁版嵁婧愰厤缃?

鍦╜__init__`鏂规硶涓坊鍔犵粨鏋勫寲閰嶇疆锛?

```python
self.trusted_sources = {
    'bonds': {
        'CN10Y': {
            'name': '涓浗10骞存湡鍥藉€?,
            'sources': [
                '涓浗鍊哄埜淇℃伅缃?yield.chinabond.com.cn',
                'cn.investing.com 涓浗10骞存湡鍥藉€?,
                'eastmoney.com 涓浗10骞村浗鍊烘敹鐩婄巼'
            ],
            'keywords': '涓浗10骞存湡鍥藉€烘敹鐩婄巼 鏈€鏂?鍊哄埜'
        },
        'CN10Y_CDB': { ... }
    },
    'commodities': {
        'GC=F': {
            'name': 'COMEX榛勯噾',
            'sources': [
                'cn.investing.com COMEX榛勯噾鏈熻揣',
                'finance.sina.com.cn 榛勯噾鏈熻揣',
                'eastmoney.com COMEX榛勯噾'
            ],
            'keywords': 'COMEX榛勯噾鏈熻揣 鏈€鏂颁环鏍?瀹炴椂琛屾儏'
        },
        'CL=F': { ... },
        'BZ=F': { ... },
        'HG=F': { ... },
        'BCOM': { ... }
    }
}
```

**浼樺娍**:
- 鏁版嵁婧愰泦涓鐞嗭紝鏄撲簬缁存姢
- 鏀寔澶氫釜澶囩敤鏁版嵁婧?
- 鍖呭惈缁撴瀯鍖栫殑鎼滅储鍏抽敭璇?

#### B. WebSearch闄嶇骇鏂规硶

鏂板涓や釜寮傛鏂规硶锛?

1. **`_websearch_fallback_bond()`**: 鍊哄埜鏁版嵁闄嶇骇
2. **`_websearch_fallback_commodity()`**: 鍟嗗搧鏁版嵁闄嶇骇

**鏍稿績鍔熻兘**:
```python
async def _websearch_fallback_bond(self, symbol: str) -> Optional[Dict[str, Any]]:
    """WebSearch闄嶇骇锛氳幏鍙栧€哄埜鏁版嵁"""
    config = self.trusted_sources['bonds'][symbol]

    # 鐢熸垚缁撴瀯鍖栨彁绀鸿瘝
    prompt = f"""
璇烽€氳繃WebSearch鑾峰彇{config['name']}鐨勬渶鏂版暟鎹細

**鏁版嵁婧愪紭鍏堢骇**:
  1. {config['sources'][0]}
  2. {config['sources'][1]}
  3. {config['sources'][2]}

**鎼滅储鍏抽敭璇?*: {config['keywords']}

**闇€瑕佺殑鏁版嵁**:
- 褰撳墠鏀剁泭鐜?(%)
- 杩?鏃ュ彉鍖?(bp)
- 杩?20鏃ュ彉鍖?(bp)
...
"""

    return {
        'symbol': symbol,
        'name': config['name'],
        'prompt': prompt,
        'sources': config['sources'],
        'method': 'WebSearch闄嶇骇'
    }
```

#### C. 涓诲～鍏呮柟娉曞寮?

淇敼`_fill_bonds()`鍜宍_fill_commodities()`锛?

```python
async def _fill_bonds(self, bond_symbols: List[str]):
    for symbol in bond_symbols:
        # 1. 灏濊瘯MCP鑾峰彇
        mcp_success = False
        try:
            result = await self.mcp_fetcher.get_bond_yield_data_mcp(...)
            if result:
                # 搴旂敤鏁版嵁
                mcp_success = True
        except Exception as exc:
            print(f"[MCP澶辫触] {symbol}: {exc}")

        # 2. MCP澶辫触锛屽惎鐢╓ebSearch闄嶇骇
        if not mcp_success:
            print(f"[闄嶇骇] 灏濊瘯WebSearch鑾峰彇 {symbol}")
            fallback_result = await self._websearch_fallback_bond(symbol)

            if fallback_result:
                # 淇濆瓨鎻愮ず璇嶅埌鏃ュ織
                self.enhancement_log['websearch_prompts'].append({
                    'category': 'bond',
                    'symbol': symbol,
                    'prompt': fallback_result['prompt'],
                    'sources': fallback_result['sources']
                })
```

**鏀硅繘鐐?*:
- 鉁?MCP寮傚父涓嶅啀鐩存帴璺宠繃
- 鉁?鑷姩瑙﹀彂闄嶇骇娴佺▼
- 鉁?鐢熸垚璇︾粏鐨刉ebSearch鎻愮ず璇?
- 鉁?璁板綍瀹屾暣鐨勯檷绾ф棩蹇?

#### D. 鏃ュ織澧炲己

鏂板鏃ュ織瀛楁锛?

```python
self.enhancement_log = {
    'start_time': ...,
    'mcp_enabled': ...,
    'enhancements': [],
    'errors': [],
    'websearch_fallbacks': [],      # 鏂板锛氶檷绾ц褰?
    'websearch_prompts': [],         # 鏂板锛氭彁绀鸿瘝闆嗗悎
    'mcp_prompts_file': ...
}
```

#### E. 鎽樿杈撳嚭浼樺寲

澧炲己`_print_summary()`锛?

```python
def _print_summary(self):
    websearch_fallbacks = len(self.enhancement_log.get('websearch_fallbacks', []))
    websearch_prompts = len(self.enhancement_log.get('websearch_prompts', []))

    print(f"  - WebSearch闄嶇骇: {websearch_fallbacks} 椤?)
    print(f"  - 鐢熸垚鎻愮ず璇? {websearch_prompts} 涓?)

    if websearch_prompts > 0:
        print(f"\n  [鎻愮ず] WebSearch鎻愮ず璇嶅凡淇濆瓨鍒版棩蹇楁枃浠?)
        print(f"  [鎻愮ず] 鍙煡鐪嬫棩蹇楄幏鍙栬缁嗙殑鎼滅储鍏抽敭璇嶅拰鏁版嵁婧?)
```

#### F. 手动结果回写（V3.3.1新增）

新增 --websearch-results 参数后，Stage2a 可以直接读取手动整理的 WebSearch 结果 JSON，自动写入 market_data_enhanced.json 并将 is_estimated=False，彻底消除 Stage 2 对外部抓数的硬依赖。

`ash
python scripts/stage2a_mcp_enhancer.py     --market-data data/20251112_stage1_fixed_test.json     --output data/20251112_stage1_manual_enhanced.json     --websearch-results data/websearch_results_20251112.json     --log-output logs/stage2a_20251112_log.json
`

结果文件结构示例：

`json
{
  "macro_indicators": {
    "ppi": {
      "current_value": -2.5,
      "previous_value": -2.9,
      "change_rate": 0.4,
      "unit": "%",
      "date": "2025-10-31",
      "source": "stats.gov.cn"
    }
  },
  "monetary_policy": {
    "m2": {
      "current_value": 8.7,
      "change_from_120d": 0.3,
      "unit": "%",
      "date": "2025-10-31",
      "source": "pbc.gov.cn"
    }
  }
}
`

回写逻辑要点：

- 支持 macro_indicators、monetary_policy、onds、commodities 四大类，统一记录到 enhancement_log['manual_updates']。
- 自动清理 metadata.missing_items，并重新计算 data_completeness，Stage 2 因此可以直接复用 Stage 1/Stage 2a 提供的数据。
- 日志中会记录 manual_results_file，方便追溯每次手动补数据的来源。

---

## 涓夈€佷紭鍖栨晥鏋?

### 3.1 浠ｇ爜缁熻

| 鎸囨爣 | 浼樺寲鍓?| 浼樺寲鍚?| 鍙樺寲 |
|------|--------|--------|------|
| 鎬昏鏁?| 641琛?| ~850琛?| +32.6% |
| 鏂板鏂规硶 | - | 2涓檷绾ф柟娉?| +2 |
| 閰嶇疆鏁版嵁婧?| 0 | 7涓?2鍊哄埜+5鍟嗗搧) | +7 |
| 鏃ュ織瀛楁 | 4涓?| 6涓?| +2 |

### 3.2 鍔熻兘瀵规瘮

| 鍦烘櫙 | 浼樺寲鍓?| 浼樺寲鍚?|
|------|--------|--------|
| MCP姝ｅ父 | 鉁?鎴愬姛鑾峰彇 | 鉁?鎴愬姛鑾峰彇 |
| MCP寮傚父 | 鉂?璁板綍閿欒锛岃烦杩?| 鉁?鑷姩闄嶇骇锛岀敓鎴愭彁绀鸿瘝 |
| 鏁版嵁瀹屾暣鎬?| 浣庯紙MCP澶辫触鏃讹級 | 涓瓑锛堟彁渚涜ˉ鏁戞柟妗堬級 |
| 鐢ㄦ埛浣撻獙 | 鏃犳槑纭寚寮?| 娓呮櫚鐨刉ebSearch鎻愮ず |
| 鏃ュ織杩借釜 | 浠呴敊璇褰?| 瀹屾暣闄嶇骇杩囩▼ |

### 3.3 瀹為檯鏁堟灉婕旂ず

**MCP姝ｅ父鏃?*:
```
[3/5] 濉厖鍊哄埜鏁版嵁...
  [INFO] 闇€瑕佽幏鍙栧€哄埜鏁版嵁: 2 椤?
    [OK] CN10Y - MCP鑾峰彇鎴愬姛
    [OK] CN10Y_CDB - MCP鑾峰彇鎴愬姛

澧炲己瀹屾垚:
  - 澶勭悊椤规暟: 7
  - 閿欒鏁? 0
```

**MCP寮傚父鏃讹紙闄嶇骇锛?*:
```
[3/5] 濉厖鍊哄埜鏁版嵁...
  [INFO] 闇€瑕佽幏鍙栧€哄埜鏁版嵁: 2 椤?
    [MCP澶辫触] CN10Y: Connection timeout
    [闄嶇骇] 灏濊瘯WebSearch鑾峰彇 CN10Y
    [WebSearch闄嶇骇] 涓浗10骞存湡鍥藉€?- 浣跨敤鍙俊鏁版嵁婧?
    [鎻愮ず] 璇锋墜鍔ㄦ墽琛學ebSearch: 涓浗10骞存湡鍥藉€烘敹鐩婄巼 鏈€鏂?鍊哄埜
    [鎻愮ず] 鍙俊鏁版嵁婧? 涓浗鍊哄埜淇℃伅缃?yield.chinabond.com.cn, ...

澧炲己瀹屾垚:
  - 澶勭悊椤规暟: 7
  - 閿欒鏁? 2
  - WebSearch闄嶇骇: 7 椤?        鈫?鏂板
  - 鐢熸垚鎻愮ず璇? 7 涓?           鈫?鏂板

  [鎻愮ず] WebSearch鎻愮ず璇嶅凡淇濆瓨鍒版棩蹇楁枃浠?
  [鎻愮ず] 鍙煡鐪嬫棩蹇楄幏鍙栬缁嗙殑鎼滅储鍏抽敭璇嶅拰鏁版嵁婧?
```


