"""CLI and environment helpers for Stage2."""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

try:  # pragma: no cover - optional dependency
    import httpx
except Exception:  # noqa: W0703
    httpx = None

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None

try:  # pragma: no cover - optional dependency
    from datasource.adapters.exa_client import AsyncExaClient
except Exception:  # noqa: W0703
    AsyncExaClient = None  # type: ignore

from datasource.adapters.tavily_client import AsyncTavilyClient
from datasource.cache.memory_cache import MemoryCache
from datasource.cache.sqlite_cache import SQLiteCache
from datasource.engines.deepseek_reasoner import DeepSeekExtractionAgent

try:
    from datasource.engines.stage2_lc_pipeline import run_tasks_lc  # type: ignore
except Exception:  # pragma: no cover - optional dependency missing
    run_tasks_lc = None  # type: ignore

from datasource.engines.stage2.common import _safe_number
from datasource.engines.stage2.diagnostics import (
    _STAGE2_BACKEND_SUMMARY_KEYS,
    _build_stage2_category_breakdown,
    _build_stage2_result_count_fields,
    _build_stage2_summary_diagnostics,
    _build_stale_refresh_fields,
    _format_stage2_category_line,
    _format_stage2_hit_rate_line,
    _format_stage2_stale_line,
    _format_stage2_task_count_line,
    _structured_provider_summary_fields,
)
from datasource.engines.stage2.snippet_filters import _percentile
from datasource.engines.stage2.validation import _flag_fund_flow_anomalies
from datasource.engines.stage2_task_planner import Stage2TaskPlanner
from datasource.utils.contract_validation import validate_market_data
from datasource.utils.json_io import atomic_write_json, load_json_strict
from datasource.utils.key_aliases import normalize_monetary_section
from datasource.utils.missing_items import sync_top_level_missing_view
from datasource.utils.observability import build_observability_log, write_observability_log
from datasource.utils.policy_rules import evaluate_policy, load_policy_rules, write_policy_evaluation
from datasource.utils.quality_metrics import write_quality_metrics
from datasource.utils.run_paths import build_run_paths_from_reference
from datasource.utils.run_snapshot import write_run_snapshot
from datasource.utils.source_conflicts import resolve_websearch_results, write_source_conflicts

try:
    from datasource.providers.stage2_structured import build_default_registry  # noqa: F401,E501
except Exception:  # pragma: no cover
    build_default_registry = None  # type: ignore


def _env_int_default(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _env_float_default(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in {None, ""}:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2 Unified Enhancer (Tavily + DeepSeek)")  # noqa: E501
    parser.add_argument("--market-data", required=True, help="Stage1 生成的 market_data.json 路径")  # noqa: E501
    parser.add_argument("--output", help="增强后输出路径；默认覆盖输入")
    parser.add_argument(
        "--no-validate-output",
        action="store_true",
        help="跳过写盘前 contract 校验(逃生门)",
    )
    parser.add_argument("--phase", choices=["essential", "assets", "all"], default="all")  # noqa: E501
    parser.add_argument("--search-backend", choices=["tavily"], default="tavily")  # noqa: E501
    parser.add_argument("--fund-flow-backend", choices=["tavily"], default="tavily")  # noqa: E501
    parser.add_argument("--task-file", default=None, help="输出任务文件路径（默认: data/runs/YYYYMMDD/search_tasks_stage2.jsonl）")  # noqa: E501
    parser.add_argument("--task-log", default=None, help="逐任务执行日志路径（默认: logs/runs/YYYYMMDD/stage_task_log.jsonl）")  # noqa: E501
    parser.add_argument("--websearch-results", default=None, help="搜索抽取结果保存路径（默认: data/runs/YYYYMMDD/websearch_results_auto.json）")  # noqa: E501
    parser.add_argument("--cache-ttl", type=int, default=3600)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-backend", choices=["memory", "sqlite"], default="memory")  # noqa: E501
    parser.add_argument("--cache-path", default="data/cache/tavily_cache.sqlite")  # noqa: E501
    parser.add_argument("--http-proxy", help="HTTP proxy, overrides env")
    parser.add_argument("--https-proxy", help="HTTPS proxy, overrides env")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--deepseek-timeout", type=float, default=30.0, help="DeepSeek抽取超时时间(秒)")  # noqa: E501
    parser.add_argument("--deepseek-max-concurrency", type=int, default=3, help="DeepSeek并发上限")  # noqa: E501
    parser.add_argument(
        "--deepseek-breaker-consecutive-timeouts",
        type=int,
        default=_env_int_default("DEEPSEEK_BREAKER_CONSECUTIVE_TIMEOUTS", 6),
        help="DeepSeek circuit breaker 连续超时阈值；<=0 禁用连续超时触发",
    )
    parser.add_argument(
        "--deepseek-breaker-timeout-rate",
        type=float,
        default=_env_float_default("DEEPSEEK_BREAKER_TIMEOUT_RATE", 0.6),
        help="DeepSeek circuit breaker 超时率阈值；<=0 禁用超时率触发",
    )
    parser.add_argument(
        "--deepseek-breaker-min-attempts",
        type=int,
        default=_env_int_default("DEEPSEEK_BREAKER_MIN_ATTEMPTS", 8),
        help="DeepSeek circuit breaker 超时率触发的最小尝试数；<=0 禁用超时率触发",
    )
    parser.add_argument("--deepseek-model", default="deepseek-v4-pro", help="DeepSeek模型名")  # noqa: E501
    parser.add_argument(
        "--deepseek-base-url",
        default=os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        help="DeepSeek API Base URL",
    )
    parser.add_argument(
        "--deepseek-serial-keys",
        help="逗号分隔的 indicator_key 列表，这些任务串行等待 DeepSeek（无并发），适用于关键指标",
    )
    parser.add_argument(
        "--extraction-backend",
        choices=["deepseek", "regex", "langchain"],
        default="deepseek",
        help="抽取后端：deepseek 优先，或强制 regex 兜底",
    )
    parser.add_argument(
        "--allow-langchain",
        action="store_true",
        help="显式启用 langchain 抽取（默认禁用）；缺依赖或未开启则直接退出",
    )
    parser.add_argument(
        "--lc-max-concurrency", type=int, default=3, help="LangChain 抽取并发上限（仅在 extraction-backend=langchain 时生效）"  # noqa: E501
    )
    parser.add_argument(
        "--lc-timeout", type=float, default=8.0, help="LangChain 抽取超时(秒)，用于 DeepSeek 调用（langchain模式）"  # noqa: E501
    )
    parser.add_argument("--langsmith", action="store_true", help="启用 LangSmith 追踪（默认关闭）")  # noqa: E501
    parser.add_argument("--resume-from-task-file", help="使用已有任务文件，跳过重新扫描 Stage1")  # noqa: E501
    parser.add_argument("--tasks", help="仅执行指定任务（task_id 或 indicator_key，逗号分隔）")  # noqa: E501
    parser.add_argument("--dry-run", action="store_true", help="仅生成任务文件，不执行搜索")
    parser.add_argument("--execute-search", action="store_true", help="立即执行 Tavily+DeepSeek 任务")  # noqa: E501
    parser.add_argument(
        "--disable-structured-providers",
        action="store_true",
        help="禁用 Stage2 structured provider-first，直接走 Tavily/Exa/DeepSeek 链路",
    )
    parser.add_argument(
        "--enable-exa-fallback",
        action="store_true",
        help="显式启用 Exa 作为 Tavily 后备；默认关闭以保持 Tavily-first 执行边界",
    )
    parser.add_argument("--log-output", default=None, help="Stage2 运行日志路径（默认: logs/runs/YYYYMMDD/stage2_unified_log.json）")  # noqa: E501
    parser.add_argument("--gap-monitor", default=None, help="gap_monitor 输出路径（默认: data/runs/YYYYMMDD/gap_monitor.json）")  # noqa: E501
    parser.add_argument(
        "--use-queue",
        dest="use_queue",
        action="store_true",
        default=True,
        help="开启 extraction 阶段 asyncio.Queue 消费模式（默认开启）",
    )
    parser.add_argument(
        "--no-use-queue",
        dest="use_queue",
        action="store_false",
        help="关闭 extraction 阶段 asyncio.Queue 消费模式，按任务串行抽取",
    )
    parser.add_argument("--queue-concurrency", type=int, default=3, help="Queue 消费者并发数")  # noqa: E501
    parser.add_argument("--queue-maxsize", type=int, default=100, help="Queue 最大容量")  # noqa: E501
    parser.add_argument("--queue-retry-limit", type=int, default=2, help="Queue 抽取重试次数（超时/网络错误）")  # noqa: E501
    parser.add_argument(
        "--disable-extract", action="store_true", help="跳过 Tavily extract 二阶段，直接使用 search 结果"  # noqa: E501
    )
    parser.add_argument(
        "--auto-disable-extract-on-422",
        action="store_true",
        help="Tavily extract 多次返回 422 时自动关闭 extract，后续任务仅 search+regex",
    )
    parser.add_argument(
        "--extract-422-threshold",
        type=int,
        default=1,
        help="触发自动停用 extract 的 Tavily 422 次数阈值（默认1）",
    )
    parser.add_argument(
        "--extract-422-cooldown-sec",
        type=int,
        default=300,
        help="Tavily extract 422 冷却窗口（秒），按指标短窗降级",
    )
    parser.add_argument(
        "--low-score-threshold",
        type=float,
        default=0.2,
        help="Tavily 搜索结果全部低于该分数时跳过抽取并标记人工",
    )
    parser.add_argument(
        "--extract-topk", type=int, default=3, help="Tavily extract 使用的搜索结果条数（默认3）"  # noqa: E501
    )
    parser.add_argument(
        "--llm-hard-timeout", type=float, default=35.0, help="对单次 LLM 抽取的 asyncio 硬超时（秒），0 表示不设硬超时"  # noqa: E501
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help="极速模式：regex 抽取、并发放大、短超时、队列不重试，并禁用 extract 以加速",
    )
    return parser.parse_args()


def _should_enable_exa_fallback(args: argparse.Namespace) -> bool:
    env_value = str(os.getenv("STAGE2_ENABLE_EXA_FALLBACK") or "").strip().lower()  # noqa: E501
    return bool(getattr(args, "enable_exa_fallback", False)) or env_value in {"1", "true", "yes", "on"}  # noqa: E501


def _should_initialize_exa_client(args: argparse.Namespace) -> bool:
    return bool(os.getenv("EXA_API_KEY")) or _should_enable_exa_fallback(args)


def _build_structured_registry_for_args(args: argparse.Namespace) -> Any:
    if getattr(args, "disable_structured_providers", False):
        return None
    if build_default_registry is None:
        return None
    try:
        return build_default_registry()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] structured provider registry init failed, fallback to search: {exc}")  # noqa: E501
        return None


def _is_exa_sdk_available() -> bool:
    return bool(
        AsyncExaClient
        and callable(getattr(AsyncExaClient, "sdk_available", None))
        and AsyncExaClient.sdk_available()  # type: ignore[union-attr]
    )


def _load_tasks_from_file(path: Path) -> List[Dict[str, Any]]:
    tasks = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tasks


def _ensure_keys(require_tavily: bool = True, require_deepseek: bool = True) -> List[str]:  # noqa: E501
    """
    校验必需的密钥，缺失时返回列表。
    默认 Tavily/DeepSeek 都需检查；可按调用场景放宽。
    """
    missing: List[str] = []
    if load_dotenv:
        load_dotenv()
    if require_tavily and not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if require_deepseek and not os.getenv("DEEPSEEK_API_KEY"):
        missing.append("DEEPSEEK_API_KEY")
    return missing


def _callable_supports_kwarg(callable_obj: Any, kwarg: str) -> bool:
    try:
        params = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    if kwarg in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())  # noqa: E501


def _select_proxy_for_url(proxies: Dict[str, str], url: str) -> Optional[str]:
    scheme = urlparse(url).scheme.lower()
    for key in (f"{scheme}://", scheme):
        proxy_url = proxies.get(key)
        if proxy_url:
            return proxy_url

    proxy_values = [proxy_url for proxy_url in proxies.values() if proxy_url]
    if len(proxy_values) == 1:
        return proxy_values[0]
    if proxy_values:
        return proxy_values[0]
    return None


def _validate_proxies(proxies: Dict[str, str]) -> Optional[Dict[str, str]]:
    """快速探测代理可用性；不可用则返回 None 并给出提示。"""
    if not proxies:
        return None
    if httpx is None:
        logger.warning("[Stage2] httpx 未安装，无法验证代理可用性，继续按配置使用。")
        return proxies
    test_url = "https://api.tavily.com"
    get_kwargs: Dict[str, Any] = {"timeout": 3}
    if _callable_supports_kwarg(httpx.get, "proxies"):
        get_kwargs["proxies"] = proxies
    elif _callable_supports_kwarg(httpx.get, "proxy"):
        proxy_url = _select_proxy_for_url(proxies, test_url)
        if not proxy_url:
            logger.warning("[Stage2] 代理配置为空，已自动禁用。")
            return None
        get_kwargs["proxy"] = proxy_url
    else:
        logger.warning("[Stage2] 当前 httpx.get 不支持显式代理验证，跳过代理探测并按配置使用。")
        return proxies
    try:
        resp = httpx.get(test_url, **get_kwargs)
        if resp.status_code < 500:
            logger.info(f"[Stage2] 代理可用，继续使用: {proxies}")
            return proxies
    except Exception as exc:
        logger.warning(f"[Stage2] 代理不可用，已自动禁用：{exc}")
    return None


def _parse_task_filter(arg: Optional[str]) -> (List[str], List[str]):
    if not arg:
        return [], []
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    task_ids, indicators = [], []
    for p in parts:
        if len(p) >= 30 and "-" in p:
            task_ids.append(p)
        else:
            indicators.append(p)
    return task_ids, indicators


CRITICAL_EXTRACT_KEYS = {
    "industrial",
    "industrial_sales",
    "bdi",
    "rrr",
    "reverse_repo",
    "mlf",
    "northbound",
    "southbound",
    "etf",
}


def _load_json(path: Path) -> Dict[str, Any]:
    return load_json_strict(path)


def _merge_missing_items(market_payload: Dict[str, Any]) -> None:
    """把 metadata.missing_items(dict) 扁平化到顶层 missing_items(list)，便于 Stage2 扫描"""
    sync_top_level_missing_view(market_payload)


def _apply_aliases(market_payload: Dict[str, Any], alias_map: Dict[str, str]) -> None:
    """将旧键名映射为新键名，避免历史数据导致空模板任务。只作用于内存数据，不改原文件。"""
    if not alias_map:
        return
    macro = market_payload.get("macro_indicators", {})
    for old, new in alias_map.items():
        if old in macro and new not in macro:
            macro[new] = macro.pop(old)
    market_payload["macro_indicators"] = macro

    miss = market_payload.get("missing_items")
    if isinstance(miss, list):
        for idx, item in enumerate(miss):
            if isinstance(item, dict):
                key = item.get("key")
                if key in alias_map:
                    miss[idx]["key"] = alias_map[key]
            elif item in alias_map:
                miss[idx] = alias_map[item]
        market_payload["missing_items"] = miss


def _warn_disable_extract_on_critical_tasks(tasks: List[Dict[str, Any]], disable_extract: bool) -> None:
    if not disable_extract:
        return
    affected = sorted(
        {
            str(task.get("indicator_key"))
            for task in tasks
            if str(task.get("indicator_key")) in CRITICAL_EXTRACT_KEYS
        }
    )
    if affected:
        logger.warning(
            "[Stage2] --disable-extract 已启用，关键指标可能落入 manual_required: {}；"
            "建议关键指标不要全局禁用 extract。",
            ",".join(affected),
        )


def _check_task_completeness(tasks: List[Dict[str, Any]]) -> List[str]:
    """检查任务的查询信息是否完整，返回警告列表"""
    warnings: List[str] = []
    for t in tasks:
        key = t.get("indicator_key")
        domains = t.get("preferred_domains") or []
        query = t.get("query")
        queries = t.get("queries") or []
        unit = t.get("unit")
        issuer = t.get("issuer")
        if not query and not queries:
            warnings.append(f"{key}: 缺少 query，已回退为 indicator_key")
        if not domains:
            warnings.append(f"{key}: 缺少 preferred_domains，可能命中词典/非目标站点")
        # 对宏观/货币/资金流向指标建议提供单位/发布机构
        if key in {"cpi", "ppi", "pmi", "pmi_new_orders", "industrial", "industrial_sales",
                   "gdp", "m1", "m2", "dr007", "reverse_repo", "rrr", "mlf", "reverse_repo_7d",
                   "northbound", "southbound", "etf"}:
            if not unit:
                warnings.append(f"{key}: 未设置 unit，建议补充以便抽取校验")
            if not issuer:
                warnings.append(f"{key}: 未设置 issuer（发布机构），建议补充筛选提示")
    return warnings


def _dump_json(payload: Dict[str, Any], path: Path) -> None:
    atomic_write_json(payload, path)


def _append_gap_monitor(output_path: Path, pending: List[str], manual: Optional[List[str]] = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pending_tasks": pending,
        "manual_required": manual or [],
        "generated_at": datetime.now().isoformat(),
    }
    _dump_json(payload, output_path)


def _filter_tasks(tasks: List[Dict[str, Any]], task_ids: Optional[List[str]], indicators: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not task_ids and not indicators:
        return tasks
    selected = []
    for t in tasks:
        if task_ids and t["task_id"] in task_ids:
            selected.append(t)
            continue
        if indicators and t["indicator_key"] in indicators:
            selected.append(t)
    return selected


def _compute_derived_metrics(market_payload: Dict[str, Any]) -> None:
    derived = market_payload.setdefault("derived_metrics", {})
    monetary = market_payload.get("monetary_policy", {})

    m1 = _safe_number(monetary.get("m1", {}).get("current_value"))
    m2 = _safe_number(monetary.get("m2", {}).get("current_value"))
    if m1 is not None and m2 is not None:
        derived["m1_m2_spread"] = round(m1 - m2, 4)

    # 简化版 DR007 五日均值：如果存在 dr007_history 列表则计算，否则跳过
    dr007_history = monetary.get("dr007", {}).get("history", [])
    if isinstance(dr007_history, list) and len(dr007_history) >= 1:
        recent = [x for x in dr007_history if _safe_number(x) is not None][-5:]
        if recent:
            avg = sum(_safe_number(x) or 0 for x in recent) / len(recent)
            derived["dr007_5d_avg"] = round(avg, 4)

    commodities = market_payload.get("commodities", [])
    changes = [
        _safe_number(item.get("daily_change")) for item in commodities if _safe_number(item.get("daily_change")) is not None
    ]
    if changes:
        avg_change = sum(changes) / len(changes)
        derived["commodity_trend"] = "上行" if avg_change > 0 else "下行"


def _gap_monitor(
    pending: List[str],
    output_path: Path,
    manual_required: Optional[List[str]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _dedupe_keep_order(values: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for v in values:
            if not v or v in seen:
                continue
            seen.add(v)
            ordered.append(v)
        return ordered

    clean_pending = _dedupe_keep_order([p for p in pending if p])
    clean_manual = _dedupe_keep_order([m for m in manual_required or [] if m])
    payload = {
        "generated_at": datetime.now().isoformat(),
    }
    if clean_pending:
        payload["pending_tasks"] = clean_pending
    if clean_manual:
        payload["manual_required"] = clean_manual
    _dump_json(payload, output_path)


async def main() -> int:
    from datasource.engines.stage2.execution import _execute_tasks

    args = _parse_args()
    if args.no_validate_output:
        os.environ["DATASOURCE_NO_VALIDATE_OUTPUT"] = "1"

    # Apply policy_rules defaults (if present)
    try:
        policy_rules = load_policy_rules()
        if not args.auto_disable_extract_on_422:
            args.auto_disable_extract_on_422 = True
        if policy_rules.get("extract_422_threshold"):
            args.extract_422_threshold = int(policy_rules.get("extract_422_threshold"))
        if policy_rules.get("extract_422_cooldown_sec") is not None:
            args.extract_422_cooldown_sec = int(policy_rules.get("extract_422_cooldown_sec"))
        if policy_rules.get("low_score_threshold") is not None:
            args.low_score_threshold = float(policy_rules.get("low_score_threshold"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] policy_rules load failed: {exc}")
    if args.extraction_backend == "langchain" and not args.allow_langchain:
        print(
            "[ERROR] langchain 模式已默认禁用。如需使用，请添加 --allow-langchain（需安装依赖）或改用 deepseek/regex。",
            file=sys.stderr,
        )
        return 1
    market_path = Path(args.market_data)
    output_path = Path(args.output) if args.output else market_path

    # Fast mode: 优先速度，牺牲部分准确度
    if args.fast_mode:
        logger.info("[Stage2] Fast mode enabled: regex extraction, higher queue concurrency, shorter timeouts.")
        args.extraction_backend = "regex"
        args.queue_concurrency = max(args.queue_concurrency, 6)
        args.queue_retry_limit = 0
        args.deepseek_max_concurrency = 0
        args.deepseek_timeout = 8.0 if args.deepseek_timeout is None else min(args.deepseek_timeout, 8.0)
        args.llm_hard_timeout = 8.0 if args.llm_hard_timeout is None or args.llm_hard_timeout == 0 else min(
            args.llm_hard_timeout, 8.0
        )
        args.disable_extract = True

    market_payload = _load_json(market_path)
    run_paths = build_run_paths_from_reference(
        payload=market_payload,
        path=market_path,
        fallback_to_today=True,
    )
    task_file = Path(args.task_file) if args.task_file else run_paths.search_tasks_stage2
    task_log_path = Path(args.task_log) if args.task_log else run_paths.stage2_task_log
    websearch_results_path = Path(args.websearch_results) if args.websearch_results else run_paths.websearch_results_auto
    log_output = Path(args.log_output) if args.log_output else run_paths.stage2_log
    gap_monitor_path = Path(args.gap_monitor) if args.gap_monitor else run_paths.gap_monitor
    _apply_aliases(market_payload, {"industrial_output": "industrial"})
    if isinstance(market_payload.get("monetary_policy"), dict):
        market_payload["monetary_policy"] = normalize_monetary_section(market_payload.get("monetary_policy"))
    _merge_missing_items(market_payload)

    # 先校验密钥并加载 .env，避免在初始化 TavilyClient 时 api_key 为空
    require_tavily = True  # 当前 search_backend 固定 tavily
    require_deepseek = args.extraction_backend not in {"regex"}  # regex 模式无需 DeepSeek key
    missing_keys = _ensure_keys(require_tavily=require_tavily, require_deepseek=require_deepseek)
    if missing_keys and args.execute_search:
        print(f"[ERROR] 缺少密钥: {', '.join(missing_keys)}。请先执行 `source .env` 或设置环境变量后重试。")
        return 1

    planner = Stage2TaskPlanner(
        stage_phase=args.phase,
        search_backend=args.search_backend,
        task_file=task_file,
        fund_flow_backend=args.fund_flow_backend,
    )
    # 若提供 resume 文件优先加载，否则重建任务（并确保去重逻辑一致）
    if args.resume_from_task_file:
        task_file = Path(args.resume_from_task_file)
        tasks = _load_tasks_from_file(task_file)
        logger.info(f"[Stage2] 使用已有任务文件 {task_file}")
    else:
        tasks = planner.build_tasks(market_payload)
        planner.write_jsonl(tasks)

    task_ids_filter, indicators_filter = _parse_task_filter(args.tasks)
    if task_ids_filter or indicators_filter:
        tasks = _filter_tasks(tasks, task_ids_filter, indicators_filter)
        logger.info(f"[Stage2] 过滤后剩余 {len(tasks)} 条任务")
    # 兼容历史 task_file：统一修正 fund_flow_backend 为 tavily
    normalized_legacy_backend = 0
    for task in tasks:
        b = str(task.get("fund_flow_backend") or "").lower()
        if b and b != "tavily":
            task["fund_flow_backend"] = "tavily"
            normalized_legacy_backend += 1
    if normalized_legacy_backend:
        logger.warning(f"[Stage2] 已将 {normalized_legacy_backend} 条历史任务的 fund_flow_backend 统一为 tavily")
    _warn_disable_extract_on_critical_tasks(tasks, args.disable_extract)
    if not tasks:
        logger.info("[Stage2] 无待执行任务，提前退出。")
        _dump_json([], websearch_results_path)
        return 0

    completeness_warnings = _check_task_completeness(tasks)
    for w in completeness_warnings:
        logger.warning(f"[Stage2] 任务信息不完整: {w}")

    cache = None
    if not args.no_cache:
        if args.cache_backend == "sqlite":
            cache = SQLiteCache(Path(args.cache_path), default_ttl=args.cache_ttl)
            cache.purge_expired()
        else:
            cache = MemoryCache(default_ttl=args.cache_ttl)
    proxies = {}
    if args.http_proxy:
        proxies["http://"] = args.http_proxy
    if args.https_proxy:
        proxies["https://"] = args.https_proxy
    proxies = _validate_proxies(proxies)
    tavily = AsyncTavilyClient(
        api_key=os.getenv("TAVILY_API_KEY"),
        cache=cache,
        timeout=args.read_timeout,
        connect_timeout=args.connect_timeout,
        max_concurrency=4,
        proxies=proxies or None,
        trust_env=(
            os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"
        ),
    )
    exa_client = None
    exa_api_key = os.getenv("EXA_API_KEY")
    exa_sdk_available = _is_exa_sdk_available()
    if _should_initialize_exa_client(args) and exa_api_key and exa_sdk_available:
        exa_client = AsyncExaClient(
            api_key=exa_api_key,
            cache=cache,
            max_concurrency=2,
        )
        if _should_enable_exa_fallback(args):
            logger.info("[Stage2] Exa fallback enabled.")
        else:
            logger.info(
                "[Stage2] EXA_API_KEY 已设置；将仅用于 Tavily quota/rate-limit failover，"
                "非 quota Exa fallback 仍需 --enable-exa-fallback。"
            )
    elif _should_enable_exa_fallback(args) and exa_api_key and not exa_sdk_available:
        logger.warning("[Stage2] EXA_API_KEY 已设置但 exa-py 未安装，Exa 兜底将被跳过。")
    elif _should_enable_exa_fallback(args) and not exa_api_key:
        logger.warning("[Stage2] Exa fallback requested but EXA_API_KEY is not set")
    elif exa_api_key and not exa_sdk_available:
        logger.warning("[Stage2] EXA_API_KEY 已设置但 exa-py 未安装，Tavily quota Exa failover 将被跳过。")
    extractor = DeepSeekExtractionAgent(
        model=args.deepseek_model,
        base_url=args.deepseek_base_url,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        trust_env=(
            os.getenv("DATASOURCE_NETWORK_MODE", "direct").lower() == "proxy"
        ),
    )

    completed_tasks: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    websearch_results: List[Dict[str, Any]] = []
    exec_stats: Dict[str, int] = {"domain_filtered_drop": 0, "regex_hits": 0}
    structured_registry = None
    if args.execute_search and args.extraction_backend != "langchain":
        structured_registry = _build_structured_registry_for_args(args)
    if args.dry_run:
        logger.info("[Stage2] Dry-run 模式：仅生成任务文件，不执行搜索")
    elif args.execute_search and tasks:
        if args.extraction_backend == "langchain":
            if run_tasks_lc is None:
                print("[ERROR] extraction_backend=langchain 但未安装 langchain 依赖。请安装或切换 deepseek。")
                return 1
            completed_tasks, failures, websearch_results = await run_tasks_lc(
                tasks,
                market_payload,
                tavily,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=args.max_retries,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                lc_max_concurrency=args.lc_max_concurrency,
                deepseek_timeout=args.lc_timeout,
                llm_hard_timeout=args.llm_hard_timeout,
            )
        else:
            completed_tasks, failures, websearch_results = await _execute_tasks(
                tasks,
                market_payload,
                tavily,
                exa_client,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=args.max_retries,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                deepseek_timeout=args.deepseek_timeout,
                extraction_backend=args.extraction_backend,
                deepseek_max_concurrency=args.deepseek_max_concurrency,
                stats=exec_stats,
                use_queue=args.use_queue,
                queue_concurrency=args.queue_concurrency,
                queue_maxsize=args.queue_maxsize,
                queue_retry_limit=args.queue_retry_limit,
                disable_extract=args.disable_extract,
                auto_disable_extract_on_422=args.auto_disable_extract_on_422,
                extract_422_threshold=args.extract_422_threshold,
                extract_422_cooldown_sec=args.extract_422_cooldown_sec,
                extract_topk=args.extract_topk,
                low_score_threshold=args.low_score_threshold,
                llm_hard_timeout=args.llm_hard_timeout,
                deepseek_breaker_consecutive_timeouts=args.deepseek_breaker_consecutive_timeouts,
                deepseek_breaker_timeout_rate=args.deepseek_breaker_timeout_rate,
                deepseek_breaker_min_attempts=args.deepseek_breaker_min_attempts,
                allow_exa_non_quota_fallback=_should_enable_exa_fallback(args),
                structured_registry=structured_registry,
            )

    flagged_fund_flow = _flag_fund_flow_anomalies(market_payload)
    # Second WebSearch pass for fund_flow anomalies (zero/None)
    if flagged_fund_flow and args.execute_search and args.fund_flow_backend == "tavily":
        retry_tasks = [t for t in tasks if t.get("indicator_key") in flagged_fund_flow]
        if retry_tasks:
            logger.info(f"[Stage2] fund_flow anomalies detected, retrying: {flagged_fund_flow}")
            retry_completed, retry_failures, retry_results = await _execute_tasks(
                retry_tasks,
                market_payload,
                tavily,
                exa_client,
                extractor,
                task_log_path,
                args.cache_ttl,
                max_retries=0,
                fund_flow_backend=args.fund_flow_backend,
                forex_backend="tavily",
                deepseek_timeout=args.deepseek_timeout,
                extraction_backend="regex",
                deepseek_max_concurrency=1,
                stats=exec_stats,
                use_queue=False,
                queue_concurrency=1,
                queue_maxsize=args.queue_maxsize,
                queue_retry_limit=0,
                disable_extract=True,
                auto_disable_extract_on_422=args.auto_disable_extract_on_422,
                extract_422_threshold=args.extract_422_threshold,
                extract_422_cooldown_sec=args.extract_422_cooldown_sec,
                extract_topk=args.extract_topk,
                low_score_threshold=args.low_score_threshold,
                llm_hard_timeout=args.llm_hard_timeout,
                deepseek_breaker_consecutive_timeouts=args.deepseek_breaker_consecutive_timeouts,
                deepseek_breaker_timeout_rate=args.deepseek_breaker_timeout_rate,
                deepseek_breaker_min_attempts=args.deepseek_breaker_min_attempts,
                allow_exa_non_quota_fallback=_should_enable_exa_fallback(args),
                structured_registry=structured_registry,
            )
            completed_tasks.extend(retry_completed)
            failures.extend(retry_failures)
            websearch_results.extend(retry_results)
            flagged_fund_flow = _flag_fund_flow_anomalies(market_payload)
    if websearch_results:
        websearch_results, conflicts_payload = resolve_websearch_results(websearch_results)
        _dump_json({"results": websearch_results}, websearch_results_path)
        try:
            conflicts_path = run_paths.data_dir / "source_conflicts.json"
            write_source_conflicts(conflicts_payload, conflicts_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Stage2] source_conflicts write failed: {exc}")

    _compute_derived_metrics(market_payload)
    metadata = market_payload.setdefault("metadata", {})
    metadata["ai_websearch_enhanced"] = True
    metadata["stage2_completed_at"] = datetime.now().isoformat()

    validate_market_data(market_payload)
    _dump_json(market_payload, output_path)

    pending_manual = list(
        dict.fromkeys([f["indicator_key"] for f in failures if f.get("manual_required") and f.get("indicator_key")])
    )
    success_keys = {c["indicator_key"] for c in completed_tasks}
    failure_keys = {f["indicator_key"] for f in failures}
    pending_keys = [
        t["indicator_key"]
        for t in tasks
        if t["indicator_key"] not in success_keys and t["indicator_key"] not in failure_keys
    ]
    _gap_monitor(pending_keys, gap_monitor_path, manual_required=pending_manual)

    # quality metrics & observability logs
    try:
        quality_path = run_paths.quality_metrics
        write_quality_metrics(market_payload, quality_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] quality_metrics write failed: {exc}")

    try:
        observability_payload = build_observability_log(tasks, completed_tasks, failures, pending_keys)
        observability_path = run_paths.observability
        write_observability_log(observability_payload, observability_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] observability log write failed: {exc}")

    avg_elapsed = 0
    p50_elapsed = 0
    p95_elapsed = 0
    deepseek_latency_list = exec_stats.get("deepseek_latencies", [])
    p50_llm = _percentile(deepseek_latency_list, 50) if deepseek_latency_list else 0
    p95_llm = _percentile(deepseek_latency_list, 95) if deepseek_latency_list else 0
    if completed_tasks:
        elapsed_vals = sorted([t.get("elapsed_ms", 0) or 0 for t in completed_tasks])
        avg_elapsed = sum(elapsed_vals) / len(elapsed_vals)
        mid = len(elapsed_vals) // 2
        p50_elapsed = elapsed_vals[mid]
        idx95 = max(0, min(len(elapsed_vals) - 1, int(len(elapsed_vals) * 0.95) - 1))
        p95_elapsed = elapsed_vals[idx95]
    cache_hits = sum(1 for t in completed_tasks if t.get("cache_hit"))
    cache_hit_rate = cache_hits / len(completed_tasks) if completed_tasks else 0

    result_count_fields = _build_stage2_result_count_fields(completed_tasks, failures)
    category_breakdown = _build_stage2_category_breakdown(tasks, completed_tasks, failures)
    stale_refresh_fields = _build_stale_refresh_fields(tasks, completed_tasks, failures)
    summary_diagnostics = _build_stage2_summary_diagnostics(
        completed_tasks,
        failures,
        websearch_results,
        exec_stats,
    )

    summary = {
        "task_total": len(tasks),
        "task_completed": len(completed_tasks),
        "task_failed": len(failures),
        **result_count_fields,
        **stale_refresh_fields,
        "retrieval_diagnostics": summary_diagnostics["retrieval_diagnostics"],
        "manual_reason_breakdown": summary_diagnostics["manual_reason_breakdown"],
        "manual_required_details": summary_diagnostics["manual_required_details"],
        "manual_required": pending_manual,
        "output": str(output_path),
        "task_file": str(task_file),
        "log": str(log_output),
        "gap_monitor": str(gap_monitor_path),
        "flagged_fund_flow": flagged_fund_flow,
        "cache_backend": args.cache_backend if not args.no_cache else "disabled",
        "proxy": {"http": args.http_proxy or os.getenv("HTTP_PROXY"), "https": args.https_proxy or os.getenv("HTTPS_PROXY")},
        "fund_flow_backend": args.fund_flow_backend,
        "avg_elapsed_ms": avg_elapsed,
        "p50_elapsed_ms": p50_elapsed,
        "p95_elapsed_ms": p95_elapsed,
        "cache_hit_rate": cache_hit_rate,
        "domain_filtered_drop": exec_stats.get("domain_filtered_drop", 0),
        "regex_hits": exec_stats.get("regex_hits", 0),
        "score_filtered_drop": exec_stats.get("score_filtered_drop", 0),
        "low_score_drop": exec_stats.get("low_score_drop", 0),
        "value_evidence_drop_count": exec_stats.get("value_evidence_drop_count", 0),
        "timeout_count": exec_stats.get("timeout_count", 0),
        "deepseek_timeouts": exec_stats.get("deepseek_timeouts", 0),
        "deepseek_circuit_breaker_triggered": exec_stats.get("deepseek_circuit_breaker_triggered", False),
        "deepseek_circuit_breaker_reason": exec_stats.get("deepseek_circuit_breaker_reason"),
        "deepseek_timeout_rate": exec_stats.get("deepseek_timeout_rate", 0.0),
        "deepseek_breaker_attempts": exec_stats.get("deepseek_breaker_attempts", 0),
        "deepseek_breaker_timeouts": exec_stats.get("deepseek_breaker_timeouts", 0),
        "retry_count": exec_stats.get("retry_count", 0),
        "extract_calls": exec_stats.get("extract_calls", 0),
        "tavily_extract_calls": exec_stats.get("tavily_extract_calls", 0),
        "tavily_extract_422_count": exec_stats.get("tavily_extract_422_count", 0),
        "extract_fallback_to_deepseek": exec_stats.get("extract_fallback_to_deepseek", 0),
        "extract_auto_disabled": exec_stats.get("extract_auto_disabled", False),
        "extract_cooldown_count": exec_stats.get("extract_cooldown_count", 0),
        "extract_globally_disabled": exec_stats.get("extract_globally_disabled", args.disable_extract),
        "extract_global_disable_reason": exec_stats.get("extract_global_disable_reason"),
        "field_retry_count": exec_stats.get("field_retry_count", 0),
        "field_retry_merged_count": exec_stats.get("field_retry_merged_count", 0),
        "field_retry_missing_fields": exec_stats.get("field_retry_missing_fields", {}),
        "post_filter_query_switch_count": exec_stats.get("post_filter_query_switch_count", 0),
        "exa_fallback": exec_stats.get("exa_fallback", 0),
        "exa_empty": exec_stats.get("exa_empty", 0),
        "exa_error": exec_stats.get("exa_error", 0),
        "exa_fallback_after_extract_422": exec_stats.get("exa_fallback_after_extract_422", 0),
        "exa_fallback_after_extract_cooldown": exec_stats.get("exa_fallback_after_extract_cooldown", 0),
        "exa_skipped_no_key_after_extract": exec_stats.get("exa_skipped_no_key_after_extract", 0),
        "deepseek_p50_ms": p50_llm,
        "deepseek_p95_ms": p95_llm,
        "queue_requeued": exec_stats.get("queue_requeued", 0),
        "queue_dead_letters": exec_stats.get("queue_dead_letters", 0),
        "write_back_by_category": exec_stats.get("write_back_by_category", {}),
        "write_back_fallback_count": exec_stats.get("write_back_fallback_count", 0),
        "write_back_miss_count": exec_stats.get("write_back_miss_count", 0),
        "structured_provider": exec_stats.get("structured_provider", {}),
        "structured_policy_gate_blocked": exec_stats.get("structured_policy_gate_blocked", 0),
        "structured_error_samples": exec_stats.get("structured_error_samples", []),
        "stage2_category_breakdown": category_breakdown,
    }
    if "tavily_unavailable_reason" in summary_diagnostics:
        summary["tavily_unavailable_reason"] = summary_diagnostics["tavily_unavailable_reason"]
    for key in _STAGE2_BACKEND_SUMMARY_KEYS:
        if key in summary_diagnostics:
            summary[key] = summary_diagnostics[key]
    for key in _structured_provider_summary_fields({}).keys():
        summary[key] = summary_diagnostics.get(key, summary.get(key))
    _dump_json(summary, log_output)

    try:
        policy_payload = evaluate_policy(market_payload, stage2_summary=summary)
        policy_path = run_paths.policy_evaluation
        write_policy_evaluation(policy_payload, policy_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] policy evaluation write failed: {exc}")

    try:
        snapshot_path = run_paths.run_snapshot
        write_run_snapshot(snapshot_path, " ".join(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Stage2] run_snapshot write failed: {exc}")

    print("\n[Stage2 Summary]")
    print(_format_stage2_hit_rate_line(summary))
    print(_format_stage2_task_count_line(summary, pending_manual_count=len(pending_manual)))
    if summary["proxy"]["http"] or summary["proxy"]["https"]:
        print(f"  Proxy: http={summary['proxy']['http']} https={summary['proxy']['https']}")
    print(f"  输出: {output_path}")
    print(f"  gap_monitor: {gap_monitor_path}")
    print(f"  平均耗时: {summary['avg_elapsed_ms']:.1f} ms; 缓存命中率: {summary['cache_hit_rate']*100:.1f}%")
    print(
        f"  过滤/兜底: 域名过滤丢弃 {summary['domain_filtered_drop']} 条；score 过滤 {summary['score_filtered_drop']} 条；"
        f"低分跳过 {summary['low_score_drop']} 次；regex 命中 {summary['regex_hits']} 次；"
        f"后过滤改选query {summary.get('post_filter_query_switch_count', 0)} 次"
    )
    auto_flag = "已触发按指标冷却" if summary.get("extract_auto_disabled") else "extract保持开启"
    fallback_ds = summary.get("extract_fallback_to_deepseek", 0)
    print(
        f"  LLM: extract {summary['extract_calls']} 次；timeout {summary['timeout_count']} 次；retry {summary['retry_count']} 次; "
        f"tavily_extract {summary['tavily_extract_calls']} 次 (422={summary['tavily_extract_422_count']}, 降级DS={fallback_ds}, {auto_flag}); "
        f"field_retry {summary.get('field_retry_count', 0)} 次；Exa回退 {summary.get('exa_fallback', 0)} 次 "
        f"(422后={summary.get('exa_fallback_after_extract_422', 0)}, cooldown后={summary.get('exa_fallback_after_extract_cooldown', 0)}); "
        f"queue_requeued {summary.get('queue_requeued',0)} dead {summary.get('queue_dead_letters',0)}"
    )
    if summary.get("extract_globally_disabled"):
        print(
            f"  extract全局停用: True (reason={summary.get('extract_global_disable_reason') or 'unknown'})"
        )
    print(
        f"  回写统计: {summary.get('write_back_by_category', {})} "
        f"(fallback={summary.get('write_back_fallback_count', 0)}, miss={summary.get('write_back_miss_count', 0)})"
    )
    if summary.get("stage2_category_breakdown"):
        print(_format_stage2_category_line(summary))
    print(_format_stage2_stale_line(summary))
    if pending_manual or summary["task_failed"] > 0:
        print("  [WARN] 仍有任务未完成或需人工处理，可用 --resume-from-task-file 重试指定任务。")
    logger.info(f"[Stage2 Unified] 完成，写入 {output_path}")
    return 1 if (pending_manual or summary["task_failed"] > 0) else 0
