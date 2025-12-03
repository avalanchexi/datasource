先把方向说清楚：
**如果你希望“模型阶段定义”严格按你这张表的“先行/同步/滞后”来判定，那现在这套 PringAnalyzer 需要做两件大改：**

1. **增加一个“宏观 6 阶段判定模块”**（只看先行/同步/滞后指标，不看股债商品）；
2. **把这个“宏观阶段”作为锚点，去约束/修正现在的 Pring 六阶段（股债商品版）输出。**

下面我按“怎么改代码”来讲，一步一步来。

---

## 一、先看现状：你的代码现在是怎么判 Pring 阶段的？

从 `PringAnalyzer` 里主流程可以看到（`analyze_pring_stage`）：

1. 第一层：`calculate_inventory_cycle_score(macro_data)`

   * 用 PPI、PMI、工增值、BDI、CPI 等算一个 **fundamental_score (0–60)**，
   * 得到库存周期阶段：主动/被动补库存/去库存（4 阶段）。

2. 第二层：`calculate_monetary_cycle_score(monetary_data)`

   * 用 M2、TSF、RRR、DR007、逆回购等算一个 **monetary_score (0–100)**，
   * 判断货币周期：宽松/中性/收紧。

3. 第三层：`get_asset_signals()` → `determine_pring_stage()`

   * 用 **债券/股票/商品** 三个资产信号（Bullish/Neutral/Bearish），
   * 按经典 Pring 规则映射：

     * 债↑股↑商↑ → 第Ⅲ阶段
     * 债↓股↓商↓ → 第Ⅵ阶段
     * …
   * 然后 `_enforce_stage_consistency` 只对 **Ⅲ/Ⅳ** 做了点校准（跟库存、货币对齐），
   * DR007 作为“领先指标”最多把阶段左右平移 1 格。

也就是说：

> 现在“第几阶段”的**底层本体还是“股债商品价格组合”**，
> 库存周期+货币周期只是用来“修修边缘”，
> 还没有把你这套“先行/同步/滞后 6 阶段表”真正编码进去。

---

## 二、你这张 1–6 阶段表，核心逻辑是什么？

概括一下你的定义（我帮你翻译成“方向向量”）：

| 阶段         | 先行 (信贷/M2/利率) | 同步 (PMI/工增/GDP) | 滞后 (通胀/PPI/CPI) | 关键词               |
| ---------- | ------------- | --------------- | --------------- | ----------------- |
| 1 衰退末/政策拐点 | ↑             | ↓               | ↓               | 大衰退尾声，政策刚开始用力     |
| 2 复苏       | ↑             | ↑               | ↓               | PM I>50 向上，但通胀还很低 |
| 3 扩张中期     | ↑             | ↑               | ↑               | 需求强、通胀抬头，政策转中性    |
| 4 过热       | ↓             | ↑               | ↑               | 信贷增速下行、通胀高位，政策收紧  |
| 5 滞胀       | ↓             | ↓               | ↑               | 增长下滑，通胀还高（类滞胀）    |
| 6 衰退       | ↓             | ↓               | ↓               | 增长和通胀一起塌，走入衰退     |

如果用“+1 / -1”来编码：

* 阶段 1：(**+1, -1, -1**)
* 阶段 2：(**+1, +1, -1**)
* 阶段 3：(**+1, +1, +1**)
* 阶段 4：(**-1, +1, +1**)
* 阶段 5：(**-1, -1, +1**)
* 阶段 6：(**-1, -1, -1**)

这跟现在代码里的 Pring Stage（看股债商品）是两套“坐标系”。
**你现在要做的是：把“宏观六阶段坐标系”也编码进去，然后两套结果做对齐。**

---

## 三、第一步：在模型里显式增加“宏观 6 阶段”的判定函数

### 1.1 定义宏观阶段枚举（可以直接加一个 Enum）

```python
class MacroStage(Enum):
    PHASE_1 = 1
    PHASE_2 = 2
    PHASE_3 = 3
    PHASE_4 = 4
    PHASE_5 = 5
    PHASE_6 = 6

    def to_display(self) -> str:
        return f"宏观第{self.value}阶段"
```

### 1.2 先把“先行 / 同步 / 滞后”三类指标圈出来

结合你现有的字段（`macro_data` + `monetary_data`）：

* **先行指标组**（Leading）：

  * M2增速（`m2_growth`）、M1增速（`m1_growth`）、社融增速（`tsf_growth`）
  * 利率方向：DR007 变化（`dr007_rate.change_from_120d`，降 → 宽松）
  * 可选：BDI（对大宗和外需也有一点领先）

* **同步指标组**（Coincident）：

  * PMI、PMI新订单、PMI生产
  * 工业增加值
  * （季度级）GDP 增速

* **滞后指标组**（Lagging）：

  * PPI 同比
  * CPI 同比

你的 `calculate_inventory_cycle_score` / `calculate_monetary_cycle_score` 已经对这些指标打分，只是没把“方向（↑/↓）”显式拿出来用。

### 1.3 对每一组算出一个“方向信号”（+1 ↑ / 0 平 / -1 ↓）

给你一个简单可落地的写法思路：

```python
def _direction_from_change(value, prev, up_thresh, down_thresh):
    """根据本期-前值的变化方向给 +1 / 0 / -1"""
    if value is None or prev is None:
        return 0
    delta = value - prev
    if delta > up_thresh:
        return 1
    elif delta < -down_thresh:
        return -1
    else:
        return 0
```

然后针对三组指标做一个“加权投票”：

```python
def _leading_direction(self, macro_data, monetary_data) -> int:
    score = 0

    # M2, TSF, M1: 增速变快 → +1；变慢 → -1
    m2 = monetary_data.get("m2_growth")
    tsf = monetary_data.get("tsf_growth")
    m1 = monetary_data.get("m1_growth")
    # 这里 prev 值可以用你在macro_data或monetary_data里的 previous_value / change_rate 近似
    # 简化: 只看绝对水平是否>=8%、>=10%也可以

    if m2 is not None:
        score += 1 if m2 >= 8 else (-1 if m2 <= 6 else 0)
    if tsf is not None:
        score += 1 if tsf >= 8 else (-1 if tsf <= 6 else 0)
    if m1 is not None:
        score += 1 if m1 >= 5 else (-1 if m1 <= 3 else 0)

    # 利率：DR007 上升 = 收紧 = -1；下降 = 宽松 = +1
    dr007 = monetary_data.get("raw_values", {}).get("dr007_rate")
    if dr007 and dr007.get("change_from_120d") is not None:
        chg = dr007["change_from_120d"]
        if chg <= -0.10:
            score += 1
        elif chg >= 0.10:
            score -= 1

    # 最后做 sign 压缩
    return 1 if score > 0 else (-1 if score < 0 else 0)
```

同步、滞后同理，比如：

```python
def _coincident_direction(self, macro_data) -> int:
    score = 0
    pmi = self._extract_macro_value(macro_data, "pmi_data")
    industrial = self._extract_macro_value(macro_data, "industrial_data")
    gdp = self._extract_macro_value(macro_data, "gdp_data")

    # PMI 水平：>50.5 明确 ↑， <49 明确 ↓
    if pmi is not None:
        score += 1 if pmi >= 50.5 else (-1 if pmi <= 49.0 else 0)

    # 工业增加值：>=5.5 强， <=3.5 弱
    if industrial is not None:
        score += 1 if industrial >= 5.5 else (-1 if industrial <= 3.5 else 0)

    # GDP：>=5.5 强，<=4 弱
    if gdp is not None:
        score += 1 if gdp >= 5.5 else (-1 if gdp <= 4.0 else 0)

    return 1 if score > 0 else (-1 if score < 0 else 0)
```

```python
def _lagging_direction(self, macro_data) -> int:
    score = 0
    ppi = self._extract_macro_value(macro_data, "ppi_data")
    cpi = self._extract_macro_value(macro_data, "cpi_data")

    # 滞后这里要兼顾“高位回落”和“低位上升”：你表里 3/4/5/6 的差别就靠这个
    if ppi is not None:
        if ppi > 1.0:        # 通胀明显为正
            score += 1
        elif ppi < -1.0:     # 深度通缩
            score -= 1

    if cpi is not None:
        if cpi > 3.0:
            score += 1
        elif cpi < 0.5:
            score -= 1

    return 1 if score > 0 else (-1 if score < 0 else 0)
```

### 1.4 用 (leading, coincident, lagging) 组合匹配 1–6 阶段

```python
def determine_macro_stage(self, macro_data, monetary_data) -> Tuple[MacroStage, float]:
    L = self._leading_direction(macro_data, monetary_data)
    C = self._coincident_direction(macro_data)
    T = self._lagging_direction(macro_data)

    pattern = (L, C, T)

    mapping = {
        (+1, -1, -1): MacroStage.PHASE_1,
        (+1, +1, -1): MacroStage.PHASE_2,
        (+1, +1, +1): MacroStage.PHASE_3,
        (-1, +1, +1): MacroStage.PHASE_4,
        (-1, -1, +1): MacroStage.PHASE_5,
        (-1, -1, -1): MacroStage.PHASE_6,
    }

    # 完全命中直接返回
    if pattern in mapping:
        return mapping[pattern], 0.9

    # 有 0（中性）的时候，用“距离最近”的阶段
    def dist(p1, p2):
        return (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2

    best_stage, best_conf = MacroStage.PHASE_2, 0.5
    best_d = 10
    for target_pattern, stage in mapping.items():
        d = dist(pattern, target_pattern)
        if d < best_d:
            best_d = d
            best_stage = stage
    # 距离越大，置信度越低
    conf = max(0.3, 0.9 - 0.2 * best_d)
    return best_stage, conf
```

这样你就真正把那张“先行/同步/滞后”表编码成了一个函数。

---

## 四、第二步：用“宏观阶段”来约束 / 修正 Pring 阶段

有了 `MacroStage` 之后，调整主流程 `analyze_pring_stage` 的关键步骤就是：

1. 在第三层之前，先算出宏观阶段：

```python
macro_stage, macro_conf = self.determine_macro_stage(macro_data, monetary_data)
```

2. 然后和 `determine_pring_stage` 出来的 `base_stage` 做一个一致性校验。

你现在的 `_enforce_stage_consistency` 只看库存周期 + 货币周期，建议改成“三层一致性校验”：

### 4.1 扩展 `_enforce_stage_consistency`，加入宏观阶段

示意：

```python
def _enforce_stage_consistency(
    self,
    base_stage: PringStage,
    base_confidence: float,
    inventory_stage: str,
    monetary_stage: str,
    macro_stage: MacroStage
) -> Tuple[PringStage, float]:
    adjusted_stage = base_stage
    adjusted_conf = base_confidence

    # 1）先保证：只有宏观阶段在 2/3/4，才允许给 Pring Ⅲ/Ⅳ
    if adjusted_stage == PringStage.STAGE_III and macro_stage.value not in (2, 3, 4):
        adjusted_stage = PringStage.STAGE_II
        adjusted_conf -= 0.1

    if adjusted_stage == PringStage.STAGE_IV and macro_stage.value not in (3, 4, 5):
        adjusted_stage = PringStage.STAGE_III
        adjusted_conf -= 0.1

    # 2）相反，如果宏观阶段=1 或 6，但价格面给了Ⅲ/Ⅳ，要往前/往后拉
    if macro_stage.value in (1, 6) and adjusted_stage in (PringStage.STAGE_III, PringStage.STAGE_IV):
        # 简化：向 Ⅱ 或 Ⅴ 平移 1 格
        if macro_stage.value == 1:
            adjusted_stage = PringStage.STAGE_II
        else:  # 6
            adjusted_stage = PringStage.STAGE_V
        adjusted_conf -= 0.1

    # 3）如果宏观阶段=3，而 Pring 给了Ⅵ（这就是你现在不满意的情况）：
    if macro_stage.value == 3 and adjusted_stage == PringStage.STAGE_VI:
        # 至少拉回Ⅲ或Ⅳ，这就让“实际价格看起来像3”的情况不会被硬标成6
        adjusted_stage = PringStage.STAGE_III
        adjusted_conf -= 0.15

    # 边界收缩
    adjusted_conf = max(0.0, min(1.0, adjusted_conf))
    return adjusted_stage, adjusted_conf
```

然后在 `analyze_pring_stage` 里调用的时候，把 `macro_stage` 也传进去就行。

---

## 五、第三步：重新校准“谁是主、谁是辅”

你现在的实现里，“基础阶段判定”来自 **股债商品技术+库存矫正**，宏观更多是辅助解释。
如果你想**完全按你这张表来理解阶段**，可以考虑进一步调整权重：

### 方案 A：**宏观阶段为主，Pring阶段为辅（适合你这次的需求）**

1. 先算 `macro_stage` （严格按先行/同步/滞后一张表）。
2. 把 `macro_stage` 映射成一个“目标 Pring 阶段”（简单 1→Ⅰ, 2→Ⅱ, … 6→Ⅵ）。
3. `determine_pring_stage` 输出只是看成“价格验证”，如果价格给出来的阶段和宏观目标差超过 2 档，就**不直接用价格结果，只降低置信度**。

例如伪逻辑：

```python
target_pring = PringStage(self.STAGE_SEQUENCE[macro_stage.value - 1].value)
base_stage, base_conf = self.determine_pring_stage(...)

if abs(self.STAGE_SEQUENCE.index(base_stage) - self.STAGE_SEQUENCE.index(target_pring)) > 2:
    # 差太多：用宏观为主
    final_stage = target_pring
    final_conf = 0.7 * macro_conf
else:
    # 差不多：说明价格和宏观大方向一致，用价格版 Pring 细化
    final_stage = base_stage
    final_conf = 0.5 * macro_conf + 0.5 * base_conf
```

### 方案 B：**两套阶段加权平均**

把“宏观阶段 index（1–6）”和“Pring阶段 index（1–6）”做一个简单的加权：

```python
macro_idx = macro_stage.value
pring_idx = self.STAGE_SEQUENCE.index(base_stage) + 1
blend_idx = round(0.6 * macro_idx + 0.4 * pring_idx)
final_stage = self.STAGE_SEQUENCE[blend_idx - 1]
```

然后 `final_stage` 再做一次一致性约束（比如你不希望出现“宏观=1、Pring=5，结果硬生生算出个3”的情况）。

---

## 六、结合你给的这张表，现阶段大概会怎么落？

用你**当前数据**大致代入一下（来自《A股背景扫描120日报告》）：

* 先行：

  * M2 = 8.2%（还不错，但比高点略回落）、TSF = 8.49%（中性偏弱）、
  * DR007 较 120 日前 **+0.3pp**（明显上行 = 收紧）。
    ➜ 先行大概率是 **“略偏↓ 或中性”**。

* 同步：

  * PMI = 49.0（刚跌回荣枯线下）、
  * 工业增加值 = 4.9%（从 6.5% 降）、
  * GDP = 5.2%（略高于 5% 潜在增速一点点）。
    ➜ 整体是“**同步略偏↓**”。

* 滞后：

  * PPI = -2.1%（深度通缩，稍有收窄）、
  * CPI = 0.2%（刚从负值回来）。
    ➜ 滞后如果按“通胀方向”，是从负往 0 修复，有点接近“↓ 后开始企稳”的阶段，你这张表里更像 **阶段 1/6 交界**。

所以按照你这张表的严格语义，现在更像：

> **先行≈↓ 或中性、同步↓、滞后↓ → MacroStage 6（衰退阶段）或 1（衰退末期/政策拐点）之间。**

而**股债商品价格**这边看起来有“Ⅲ 味道”，你前面直觉没错。
两者冲突时，你是想：——**“阶段 label 要听表（宏观），还是听盘（价格）？”**

* 现在这份代码 → 更偏**听盘**（Pring资产信号主导）；
* 按你这张表调整后 → 会变成**先听宏观，再让价格细化、验证**。

---

## 七、总结一下“模型该怎么调”

**核心调整路径可以概括为三句话：**

1. **把你的“阶段 1–6 宏观定义”编码成一个独立函数 `determine_macro_stage`，
   明确地用（先行、同步、滞后）三个方向向量来判定。**

2. **在 `analyze_pring_stage` 里加入这个“宏观阶段”，并扩展 `_enforce_stage_consistency`，
   让任何 Pring 阶段输出，都必须“与宏观阶段不严重打架”，
   特别是避免“宏观偏 2/3，却给出 Pring Ⅵ”这种极端。**

3. **明确主次：

   * 如果你认为“表是纲，盘是目”，就用宏观阶段作为主导，只让股债商品帮你决定偏多/偏空的强弱；
   * 如果你还是想价格优先，就至少让宏观阶段来“禁止一些不合理的极端阶段”。**

你如果愿意，我可以在下一步直接帮你把
`determine_macro_stage` 和新的 `_enforce_stage_consistency` 写成一版可直接粘到你 `PringAnalyzer` 里的代码草稿（按你现有的字段名来写），你只要再根据实际 backtest 微调阈值就行。

---

## 八、接口兼容与对齐（需落入需求）
- 受影响文件：`scripts/stage3_pring_analyzer.py`、`src/datasource/calculators/pring_analyzer.py`、`scripts/background_scan_unified.py`、`tests/scripts/run_pring_analysis_test.py`、Stage4 报告生成器（`src/datasource/generators/report_generator.py`、`tests/scripts/generate_simple_report_test.py`）。
- 向后兼容要求：
  - 旧键 `final_stage/confidence/recommendation` 保留；新增 `stage` 作为别名。
  - 新增必填字段：`asset_signals`、`asset_allocation_pct`、`leading_indicator`、`leading_summary`、`pending_websearch`、`data_completeness`、`fallback_used`（布尔）。
  - `metadata` 中增加 `ai_websearch_enhanced`、`gap_monitor_cleared`、`min_completeness`。
- 回滚开关：CLI 增加 `--legacy-stage-rules`，启用时沿用旧静态模式匹配。

## 九、权重与阈值的来源与要求
- 默认权重（可配置）：`inventory_bias 0.35`、`monetary_bias 0.35`、`asset_pattern 0.30`；完整性阈值 `0.80`。
- 依据：2025-10~2025-11 至少 18 组样本的回测；MR 需附对比表（预测阶段、置信度、真实标注）。
- 新增日志字段 `weights_version`，用于记录当前权重方案；回调时便于比对。

## 十、测试矩阵（验收最小集）
- UT
  - 缺宏观（ppi/cpi/pmi_new_orders 任意缺）→ 直接失败，`error` 含缺口列表。
  - 缺货币（m2/m1/dr007/rrr 任意缺）→ 失败。
  - 资产信号冲突（债↑股↓商↑）→ 一致性约束收敛到 ≤Ⅳ，置信度 <0.55。
  - 领先指标冲突（DR007 宽松、剪刀差收紧）→ `leading_indicator.status=flat`，不平移阶段。
  - CLI 覆盖：`--days 90` → `data_period=90天历史数据`。
- 集成
  - 样本 A（当前市场）：预期「第Ⅲ阶段±1」，置信度 ≥0.6。
  - 样本 B（删除 M1/M2）：应阻断并写 `reports/pring_stage3_log.json`。
  - 样本 C（`--legacy-stage-rules`）：输出应与旧版本一致，用于差异对比。

## 十一、日志与可观测性
- 新日志：`reports/pring_stage3_log.json`（单次覆盖），字段：
  - `input`: 路径、时间戳、`ai_websearch_enhanced`、`gap_monitor_cleared`
  - `completeness`: overall/layer1/layer2/layer3/pending_websearch
  - `stage`: base/final/confidence/weights_version/legacy_mode
  - `data_sources`: 宏观/货币/资产来源
  - `warnings/errors`: 列表
  - `runtime_sec`
- stdout 精简为：读取→校验→阶段→置信度，其余细节写日志。

## 十二、配置与环境约束
- CLI 默认：`--days 120`，`--min-completeness 0.8`，`--allow-fallback false`，`--gap-monitor reports/gap_monitor.json`。
- `.env/indices_config` 暂不新增字段；若调整权重或阈值，走 CLI 或独立 Stage3 配置段，避免影响 Stage1/2。

## 十三、性能与并发
- Stage3 不再触发外部网络调用（WebSearch/AKShare 禁用），仅消费 Stage1/2 数据。
- 目标耗时：≤5s；日志记录 `runtime_sec`，便于监控。

## 十四、入口前置检查（新增要求）
- Stage3 启动时先读取 `market_data_complete.json` 的 `metadata.missing_items` / `data_completeness`：
  - 若存在缺口或完整性 < `min_completeness`，直接退出并提示“先执行 Stage2/Stage2.5 WebSearch/补数”。
  - 与 `gap_monitor` 校验一致：若 pending/manual 不为空，同样阻断。
- 目的：杜绝用占位/缺失数据进入阶段判定，避免再次出现“应在Ⅲ却落到Ⅵ”的偏差。
- 补数提示模板（stdout/日志复用）：
  - `缺口: {missing_items}; completeness: {data_completeness:.2f} < {min_completeness}. 请先执行 Stage2: PYTHONPATH=. python scripts/stage2_unified_enhancer.py --market-data data/market_data.json --output data/market_data_stage2.json --execute-search --fund-flow-backend hybrid --cache-backend sqlite --cache-path reports/tavily_cache.sqlite --websearch-results reports/websearch_results_auto.json --gap-monitor reports/gap_monitor.json`
  - 若仅需重注入 WebSearch：`python inject_websearch_data_test.py data/market_data_stage2.json reports/websearch_results_auto.json data/market_data_complete.json`
