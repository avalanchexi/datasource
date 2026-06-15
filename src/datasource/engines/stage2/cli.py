"""CLI and environment helpers for Stage2."""
from __future__ import annotations

import argparse
import inspect
import json
import os
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
