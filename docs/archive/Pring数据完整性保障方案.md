# Pring周期判断数据完整性保障方案

## 问题分析

当前V4.0框架存在的数据完整性风险：

1. **货币周期数据缺失**: M2/逆回购/MLF/降准/TSF数据获取失败时，评分为0，导致货币周期判断失真
2. **债券数据缺失**: 国债ETF代理失败时，使用中性信号，可能误判Pring阶段
3. **资金流向异常**: 北向/南向资金返回零值时，未阻止分析继续
4. **无数据质量门槛**: 缺乏最低数据完整性要求，允许不完整数据参与判断

## 解决方案设计

### 方案1: 数据依赖检查器 (Data Dependency Validator)

#### 1.1 数据完整性模型

```python
# src/datasource/calculators/data_validator.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum

class DataQuality(Enum):
    """数据质量等级"""
    EXCELLENT = "优秀"      # 100% 数据完整
    GOOD = "良好"           # 80-99% 数据完整
    ACCEPTABLE = "可接受"   # 60-79% 数据完整
    POOR = "较差"           # 40-59% 数据完整
    CRITICAL = "严重不足"   # <40% 数据完整

@dataclass
class DataRequirement:
    """数据需求定义"""
    name: str                          # 数据名称
    is_required: bool                  # 是否必需
    weight: float                      # 权重(0-1)
    fallback_strategy: Optional[str]   # 降级策略
    min_records: int = 1               # 最少记录数

@dataclass
class DataAvailability:
    """数据可用性状态"""
    name: str
    is_available: bool
    record_count: int
    data_source: str
    quality_score: float  # 0-1
    error_message: Optional[str] = None

@dataclass
class ValidationResult:
    """验证结果"""
    overall_quality: DataQuality
    completeness_score: float  # 0-100
    missing_required: List[str]
    missing_optional: List[str]
    warnings: List[str]
    is_sufficient: bool
    data_availability: Dict[str, DataAvailability] = field(default_factory=dict)
```

#### 1.2 Pring分析数据需求定义

```python
# src/datasource/calculators/pring_data_requirements.py

PRING_DATA_REQUIREMENTS = {
    # 第一层：库存周期数据需求
    "layer_1_inventory": {
        "PPI": DataRequirement(
            name="工业生产者出厂价格指数(PPI)",
            is_required=True,
            weight=0.30,
            fallback_strategy="use_historical",
            min_records=12  # 至少12个月数据
        ),
        "PMI": DataRequirement(
            name="制造业采购经理指数(PMI)",
            is_required=True,
            weight=0.25,
            fallback_strategy="use_historical",
            min_records=3   # 至少3个月数据
        ),
        "INDUSTRIAL_VALUE": DataRequirement(
            name="工业增加值",
            is_required=True,
            weight=0.20,
            fallback_strategy="interpolate",
            min_records=12
        ),
        "BDI": DataRequirement(
            name="波罗的海干散货指数(BDI)",
            is_required=False,
            weight=0.15,
            fallback_strategy="skip",
            min_records=30  # 至少30天
        ),
        "CPI": DataRequirement(
            name="居民消费价格指数(CPI)",
            is_required=True,
            weight=0.10,
            fallback_strategy="use_historical",
            min_records=12
        )
    },

    # 第二层：货币周期数据需求
    "layer_2_monetary": {
        "M2_GROWTH": DataRequirement(
            name="M2同比增速",
            is_required=True,
            weight=0.25,
            fallback_strategy="websearch",
            min_records=3
        ),
        "REVERSE_REPO_7D": DataRequirement(
            name="7天逆回购利率",
            is_required=True,
            weight=0.25,
            fallback_strategy="websearch",
            min_records=1
        ),
        "MLF_1Y": DataRequirement(
            name="1年期MLF利率",
            is_required=True,
            weight=0.20,
            fallback_strategy="websearch",
            min_records=1
        ),
        "RRR_CHANGE": DataRequirement(
            name="存款准备金率变化",
            is_required=True,
            weight=0.15,
            fallback_strategy="websearch",
            min_records=1
        ),
        "TSF_GROWTH": DataRequirement(
            name="社会融资规模增速",
            is_required=True,
            weight=0.15,
            fallback_strategy="websearch",
            min_records=3
        )
    },

    # 第三层：Pring资产信号数据需求
    "layer_3_pring": {
        "BOND_SIGNAL": DataRequirement(
            name="债券信号(国债/国开债)",
            is_required=True,
            weight=0.33,
            fallback_strategy="neutral_signal",
            min_records=120  # 至少120个交易日
        ),
        "STOCK_SIGNAL": DataRequirement(
            name="股票信号(沪深300/上证50)",
            is_required=True,
            weight=0.33,
            fallback_strategy="none",  # 必需，无降级
            min_records=120
        ),
        "COMMODITY_SIGNAL": DataRequirement(
            name="商品信号(WTI/Brent/COMEX铜/黄金)",
            is_required=True,
            weight=0.34,
            fallback_strategy="partial_analysis",
            min_records=120
        )
    }
}

# 最低数据完整性阈值
MINIMUM_COMPLETENESS_THRESHOLDS = {
    "layer_1_inventory": 0.70,      # 库存周期至少70%数据完整
    "layer_2_monetary": 0.60,       # 货币周期至少60%数据完整
    "layer_3_pring": 0.80,          # Pring信号至少80%数据完整
    "overall": 0.70                 # 总体至少70%数据完整
}
```

#### 1.3 数据验证器实现

```python
# src/datasource/calculators/pring_data_validator.py

class PringDataValidator:
    """Pring分析数据完整性验证器"""

    def __init__(self, requirements: Dict[str, Dict[str, DataRequirement]]):
        self.requirements = requirements
        self.validation_results: Dict[str, ValidationResult] = {}

    def validate_layer(
        self,
        layer_name: str,
        data_collection: Dict[str, any]
    ) -> ValidationResult:
        """
        验证单层数据完整性

        Args:
            layer_name: 层名称 (layer_1_inventory/layer_2_monetary/layer_3_pring)
            data_collection: 实际获取的数据集合

        Returns:
            ValidationResult: 验证结果
        """
        layer_requirements = self.requirements.get(layer_name, {})

        missing_required = []
        missing_optional = []
        warnings = []
        data_availability = {}

        total_weight = 0.0
        available_weight = 0.0

        for data_key, requirement in layer_requirements.items():
            total_weight += requirement.weight

            # 检查数据是否存在
            data_item = data_collection.get(data_key)

            if data_item is None or self._is_empty(data_item):
                # 数据缺失
                availability = DataAvailability(
                    name=requirement.name,
                    is_available=False,
                    record_count=0,
                    data_source="N/A",
                    quality_score=0.0,
                    error_message="数据未获取"
                )

                if requirement.is_required:
                    missing_required.append(requirement.name)
                    warnings.append(
                        f"[严重] 必需数据缺失: {requirement.name} "
                        f"(权重{requirement.weight*100:.0f}%, "
                        f"降级策略: {requirement.fallback_strategy})"
                    )
                else:
                    missing_optional.append(requirement.name)
                    warnings.append(
                        f"[提示] 可选数据缺失: {requirement.name} "
                        f"(权重{requirement.weight*100:.0f}%)"
                    )
            else:
                # 数据存在，检查质量
                record_count = self._get_record_count(data_item)
                quality_score = self._assess_quality(
                    record_count,
                    requirement.min_records
                )

                availability = DataAvailability(
                    name=requirement.name,
                    is_available=True,
                    record_count=record_count,
                    data_source=self._get_data_source(data_item),
                    quality_score=quality_score
                )

                if quality_score >= 0.8:
                    available_weight += requirement.weight
                elif quality_score >= 0.5:
                    available_weight += requirement.weight * quality_score
                    warnings.append(
                        f"[警告] 数据质量不足: {requirement.name} "
                        f"(记录数{record_count}/{requirement.min_records}, "
                        f"质量分{quality_score*100:.0f}%)"
                    )
                else:
                    warnings.append(
                        f"[严重] 数据质量极差: {requirement.name} "
                        f"(记录数{record_count}/{requirement.min_records})"
                    )

            data_availability[data_key] = availability

        # 计算完整性评分
        completeness_score = (available_weight / total_weight * 100) if total_weight > 0 else 0

        # 判断数据质量等级
        if completeness_score >= 100:
            overall_quality = DataQuality.EXCELLENT
        elif completeness_score >= 80:
            overall_quality = DataQuality.GOOD
        elif completeness_score >= 60:
            overall_quality = DataQuality.ACCEPTABLE
        elif completeness_score >= 40:
            overall_quality = DataQuality.POOR
        else:
            overall_quality = DataQuality.CRITICAL

        # 判断是否满足最低要求
        min_threshold = MINIMUM_COMPLETENESS_THRESHOLDS.get(layer_name, 0.70)
        is_sufficient = completeness_score >= (min_threshold * 100)

        return ValidationResult(
            overall_quality=overall_quality,
            completeness_score=completeness_score,
            missing_required=missing_required,
            missing_optional=missing_optional,
            warnings=warnings,
            is_sufficient=is_sufficient,
            data_availability=data_availability
        )

    def validate_all_layers(
        self,
        layer_1_data: Dict,
        layer_2_data: Dict,
        layer_3_data: Dict
    ) -> Dict[str, ValidationResult]:
        """
        验证所有三层数据完整性

        Returns:
            Dict[str, ValidationResult]: 每层的验证结果
        """
        results = {
            "layer_1_inventory": self.validate_layer("layer_1_inventory", layer_1_data),
            "layer_2_monetary": self.validate_layer("layer_2_monetary", layer_2_data),
            "layer_3_pring": self.validate_layer("layer_3_pring", layer_3_data)
        }

        # 计算总体完整性
        overall_score = sum(r.completeness_score for r in results.values()) / 3
        overall_threshold = MINIMUM_COMPLETENESS_THRESHOLDS["overall"] * 100

        results["overall"] = ValidationResult(
            overall_quality=self._get_quality_level(overall_score),
            completeness_score=overall_score,
            missing_required=[],
            missing_optional=[],
            warnings=[],
            is_sufficient=overall_score >= overall_threshold
        )

        self.validation_results = results
        return results

    def generate_report(self) -> str:
        """生成数据完整性报告"""
        if not self.validation_results:
            return "[ERROR] 未进行数据验证"

        report_lines = [
            "=" * 70,
            "Pring周期判断数据完整性报告",
            "=" * 70,
            ""
        ]

        for layer_name, result in self.validation_results.items():
            if layer_name == "overall":
                continue

            report_lines.append(f"\n【{layer_name}】")
            report_lines.append(f"  数据质量: {result.overall_quality.value}")
            report_lines.append(f"  完整性评分: {result.completeness_score:.1f}/100")
            report_lines.append(f"  是否满足最低要求: {'✓ 是' if result.is_sufficient else '✗ 否'}")

            if result.missing_required:
                report_lines.append(f"  缺失必需数据({len(result.missing_required)}项):")
                for item in result.missing_required:
                    report_lines.append(f"    - {item}")

            if result.missing_optional:
                report_lines.append(f"  缺失可选数据({len(result.missing_optional)}项):")
                for item in result.missing_optional:
                    report_lines.append(f"    - {item}")

            if result.warnings:
                report_lines.append(f"  警告信息({len(result.warnings)}条):")
                for warning in result.warnings:
                    report_lines.append(f"    {warning}")

        overall = self.validation_results.get("overall")
        if overall:
            report_lines.extend([
                "",
                "=" * 70,
                f"总体数据完整性: {overall.completeness_score:.1f}/100 ({overall.overall_quality.value})",
                f"是否可执行Pring分析: {'✓ 可以执行' if overall.is_sufficient else '✗ 数据不足，不建议执行'}",
                "=" * 70
            ])

        return "\n".join(report_lines)

    def _is_empty(self, data: any) -> bool:
        """检查数据是否为空"""
        if data is None:
            return True
        if isinstance(data, (list, dict, str)) and len(data) == 0:
            return True
        if hasattr(data, 'empty') and data.empty:  # pandas DataFrame
            return True
        return False

    def _get_record_count(self, data: any) -> int:
        """获取记录数"""
        if hasattr(data, '__len__'):
            return len(data)
        return 1 if data is not None else 0

    def _assess_quality(self, actual_records: int, min_records: int) -> float:
        """评估数据质量分数 (0-1)"""
        if actual_records >= min_records:
            return 1.0
        elif actual_records >= min_records * 0.5:
            return actual_records / min_records
        else:
            return 0.3  # 记录数不足一半，质量极差

    def _get_data_source(self, data: any) -> str:
        """获取数据来源"""
        if hasattr(data, 'source'):
            return data.source
        if isinstance(data, dict) and 'source' in data:
            return data['source']
        return "unknown"

    def _get_quality_level(self, score: float) -> DataQuality:
        """根据分数获取质量等级"""
        if score >= 100:
            return DataQuality.EXCELLENT
        elif score >= 80:
            return DataQuality.GOOD
        elif score >= 60:
            return DataQuality.ACCEPTABLE
        elif score >= 40:
            return DataQuality.POOR
        else:
            return DataQuality.CRITICAL
```

#### 1.4 集成到PringAnalyzer

```python
# 在 pring_analyzer.py 的 analyze_pring_stage() 方法中集成

async def analyze_pring_stage(self, days: int = 250) -> Dict:
    """
    完整的普林格六阶段分析（三层框架：库存周期 → 货币周期 → Pring修正）

    V4.1: 新增数据完整性验证
    """
    try:
        print("=" * 60)
        print("开始三层框架分析")
        print("=" * 60)

        # ===== 数据收集阶段 =====
        print("\n[阶段1] 数据收集...")

        # 第一层：库存周期数据
        print("  收集库存周期数据...")
        macro_data = await self.get_macro_economic_data()

        # 第二层：货币周期数据
        print("  收集货币周期数据...")
        monetary_data = await self.get_monetary_cycle_data()

        # 第三层：Pring资产信号数据
        print("  收集Pring资产信号数据...")
        asset_signals = await self.get_asset_signals(days)

        # ===== 数据验证阶段 =====
        print("\n[阶段2] 数据完整性验证...")

        validator = PringDataValidator(PRING_DATA_REQUIREMENTS)
        validation_results = validator.validate_all_layers(
            layer_1_data=macro_data,
            layer_2_data=monetary_data,
            layer_3_data=asset_signals
        )

        # 打印验证报告
        print(validator.generate_report())

        # 检查是否满足最低要求
        if not validation_results["overall"].is_sufficient:
            error_msg = (
                f"数据完整性不足，无法执行Pring分析！\n"
                f"当前完整性: {validation_results['overall'].completeness_score:.1f}%, "
                f"最低要求: {MINIMUM_COMPLETENESS_THRESHOLDS['overall']*100:.0f}%\n"
                f"缺失必需数据:\n"
            )

            for layer_name in ["layer_1_inventory", "layer_2_monetary", "layer_3_pring"]:
                result = validation_results[layer_name]
                if result.missing_required:
                    error_msg += f"  {layer_name}: {', '.join(result.missing_required)}\n"

            print(f"\n[ERROR] {error_msg}")

            return {
                "stage": "数据不足",
                "confidence": 0.0,
                "error": error_msg,
                "data_validation": validation_results
            }

        # ===== 继续执行三层分析 =====
        print("\n[阶段3] 执行三层框架分析...")

        # 第一层：库存周期分析
        print("\n【第一层】库存周期分析...")
        inventory_analysis = self.calculate_inventory_cycle_score(macro_data)
        # ... (原有代码)

        # 第二层：货币周期叠加
        print("\n【第二层】货币周期叠加...")
        monetary_analysis = self.calculate_monetary_cycle_score(monetary_data)
        # ... (原有代码)

        # 第三层：Pring最终判定
        print("\n【第三层】Pring最终阶段判定...")
        # ... (原有代码)

        return {
            "stage": final_stage.to_display_format(),
            "confidence": final_confidence,
            "layer_1_inventory_cycle": inventory_analysis,
            "layer_2_monetary_cycle": monetary_analysis,
            "layer_3_pring_final": {
                "base_stage": base_stage.to_display_format(),
                "base_confidence": base_confidence,
                "final_stage": final_stage.to_display_format(),
                "final_confidence": final_confidence,
                "adjustment": adjustment_info,
                "asset_signals": asset_signals_summary
            },
            "data_validation": validation_results,  # 新增：验证结果
            "technical_score": technical_score,
            "inventory_cycle_score": inventory_analysis.get('fundamental_score', 0)
        }

    except Exception as e:
        print(f"[ERROR] Pring分析失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "stage": "分析失败",
            "confidence": 0.0,
            "error": str(e)
        }
```

### 方案2: 实时数据获取状态跟踪

在数据获取过程中实时跟踪状态：

```python
# src/datasource/utils/data_tracker.py

class DataAcquisitionTracker:
    """数据获取状态跟踪器"""

    def __init__(self):
        self.acquisition_log: List[Dict] = []
        self.start_time = None
        self.end_time = None

    def start_tracking(self):
        """开始跟踪"""
        self.start_time = datetime.now()
        self.acquisition_log = []

    def log_acquisition(
        self,
        data_name: str,
        is_success: bool,
        data_source: str,
        record_count: int = 0,
        error_message: Optional[str] = None
    ):
        """记录数据获取事件"""
        self.acquisition_log.append({
            "timestamp": datetime.now(),
            "data_name": data_name,
            "is_success": is_success,
            "data_source": data_source,
            "record_count": record_count,
            "error_message": error_message
        })

    def get_summary(self) -> Dict:
        """获取获取摘要"""
        self.end_time = datetime.now()

        total = len(self.acquisition_log)
        successful = sum(1 for log in self.acquisition_log if log["is_success"])
        failed = total - successful

        return {
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "total_attempts": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "acquisition_log": self.acquisition_log
        }

    def print_summary(self):
        """打印获取摘要"""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("数据获取摘要")
        print("=" * 60)
        print(f"总耗时: {summary['duration_seconds']:.1f}秒")
        print(f"尝试获取: {summary['total_attempts']}项")
        print(f"成功: {summary['successful']}项")
        print(f"失败: {summary['failed']}项")
        print(f"成功率: {summary['success_rate']*100:.1f}%")

        if summary['failed'] > 0:
            print("\n失败项详情:")
            for log in summary['acquisition_log']:
                if not log['is_success']:
                    print(f"  - {log['data_name']}: {log['error_message']}")

        print("=" * 60)
```

### 方案3: 数据获取前置检查

在执行Pring分析前先检查数据源可用性：

```python
# src/datasource/calculators/pring_preflight_check.py

class PringPreflightChecker:
    """Pring分析前置检查器"""

    def __init__(self, manager: DataSourceManager):
        self.manager = manager

    async def check_data_sources(self) -> Dict[str, bool]:
        """检查所有必需数据源的可用性"""

        availability = {}

        # 检查TuShare连接
        try:
            test_response = await self.manager.get_index_daily("000300", "2025-01-01", "2025-01-31")
            availability["tushare"] = not test_response.error
        except:
            availability["tushare"] = False

        # 检查AKShare连接
        try:
            import akshare as ak
            test_data = ak.stock_zh_index_daily(symbol="sh000300")
            availability["akshare"] = test_data is not None and not test_data.empty
        except:
            availability["akshare"] = False

        # 检查国际金融数据
        try:
            forex_response = await self.manager.get_forex_data("USDCNY", "2025-01-01", "2025-01-31")
            availability["international_finance"] = not forex_response.error
        except:
            availability["international_finance"] = False

        return availability

    async def check_minimum_requirements(self) -> Tuple[bool, List[str]]:
        """
        检查是否满足最低数据需求

        Returns:
            Tuple[bool, List[str]]: (是否满足, 缺失项列表)
        """
        availability = await self.check_data_sources()

        missing = []

        # 至少需要TuShare或AKShare之一可用
        if not (availability.get("tushare") or availability.get("akshare")):
            missing.append("股票市场数据源(TuShare或AKShare)")

        # 国际金融数据源可选，但建议可用
        if not availability.get("international_finance"):
            print("[WARNING] 国际金融数据源不可用，将使用降级策略")

        is_sufficient = len(missing) == 0

        return is_sufficient, missing
```

## 实施建议

### 阶段1: 立即实施 (优先级最高)

1. **在`analyze_pring_stage()`开始处添加数据验证日志**:
```python
print("\n[数据验证] 检查必需数据...")
required_checks = {
    "库存周期-PPI": macro_data.get('ppi') is not None,
    "库存周期-PMI": macro_data.get('pmi') is not None,
    "货币周期-M2": monetary_data.get('m2_growth') is not None,
    "Pring-股票信号": asset_signals.get('stock_signal') is not None,
}

missing = [k for k, v in required_checks.items() if not v]
if missing:
    print(f"[WARNING] 缺失必需数据: {', '.join(missing)}")
    print("[WARNING] 分析结果可能不可靠!")
```

2. **在每个数据获取方法中添加状态检查**:
```python
async def get_macro_economic_data(self) -> Dict:
    data = {}
    acquisition_status = []

    # PPI
    try:
        ppi_data = ...
        if ppi_data is not None:
            data['ppi'] = ppi_data
            acquisition_status.append(("PPI", True, len(ppi_data)))
        else:
            acquisition_status.append(("PPI", False, 0))
    except Exception as e:
        acquisition_status.append(("PPI", False, 0))

    # 打印获取状态
    print("\n[数据获取状态]")
    for name, success, count in acquisition_status:
        status = "[OK]" if success else "[FAIL]"
        print(f"  {status} {name}: {count}条记录")

    return data
```

### 阶段2: 短期实施 (1-2天)

1. 实现完整的`PringDataValidator`类
2. 集成到`analyze_pring_stage()`方法
3. 添加数据完整性报告输出到日志和报告中

### 阶段3: 中期优化 (1周)

1. 实现`DataAcquisitionTracker`实时跟踪
2. 实现`PringPreflightChecker`前置检查
3. 添加数据获取重试机制
4. 添加数据质量评分系统

## 使用示例

```python
# 在background_scan_120d_generator.py中使用

async def get_pring_cycle_analysis(self) -> Dict[str, Any]:
    """
    获取Pring三层框架完整分析
    V4.1: 新增数据完整性验证
    """

    # 前置检查
    preflight = PringPreflightChecker(self.manager)
    is_sufficient, missing = await preflight.check_minimum_requirements()

    if not is_sufficient:
        print(f"[ERROR] 数据源不满足最低要求，缺失: {', '.join(missing)}")
        return {
            "stage": "数据源不可用",
            "error": f"缺失: {', '.join(missing)}"
        }

    # 执行分析
    pring_result = await self.pring_analyzer.analyze_pring_stage(250)

    # 检查数据验证结果
    if 'data_validation' in pring_result:
        validation = pring_result['data_validation']['overall']
        print(f"\n[数据质量] {validation.overall_quality.value} ({validation.completeness_score:.1f}%)")

        if not validation.is_sufficient:
            print("[WARNING] 数据完整性不足，分析结果仅供参考！")

    return pring_result
```

## 总结

该方案提供三个层次的数据完整性保障：

1. **前置检查**: 确保基础数据源可用
2. **实时验证**: 在分析过程中验证数据完整性
3. **结果校验**: 根据数据质量调整分析置信度

通过这些机制，可以确保Pring周期判断基于可靠的完整数据，避免因数据缺失导致的误判。
