"""Tavily error classification helpers for Stage2."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_TAVILY_LIMIT_STATUSES = {402, 403, 429, 432, 433}

_TAVILY_ERROR_TEXT_LIMIT = 500

_TAVILY_REQUEST_ID_HEADERS = (
    "x-request-id",
    "x-tavily-request-id",
    "x-tavily-trace-id",
    "request-id",
)


def _coerce_http_status(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_header_value(headers: Any, names: Tuple[str, ...]) -> Optional[str]:
    if not headers:
        return None
    for name in names:
        value = None
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        if value is None:
            try:
                value = headers.get(name.lower())
            except AttributeError:
                value = None
        if value is None:
            try:
                target = name.casefold()
                for header_name, header_value in headers.items():
                    if str(header_name).casefold() == target:
                        value = header_value
                        break
            except AttributeError:
                value = None
        if value:
            return str(value)
    return None


def _sanitize_tavily_error_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    sanitized = re.sub(
        r"(?i)(api[_-]?key[\"']?\s*[:=]\s*)[\"']?[^\"'\s,}]+",
        r"\1[redacted]",
        raw,
    )
    if len(sanitized) > _TAVILY_ERROR_TEXT_LIMIT:
        return sanitized[:_TAVILY_ERROR_TEXT_LIMIT] + "...[truncated]"
    return sanitized


def _tavily_error_metadata(source: Any) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    response = getattr(source, "response", None)

    if isinstance(source, dict):
        status = _coerce_http_status(source.get("status") or source.get("status_code"))  # noqa: E501
        message = " ".join(
            str(source.get(key) or "")
            for key in ("error", "message", "detail", "warning")
            if source.get(key)
        )
        request_id = source.get("request_id") or source.get("tavily_request_id")  # noqa: E501
        error_type = "tavily_response"
    else:
        status = _coerce_http_status(getattr(response, "status_code", None))
        message = getattr(response, "text", None) or str(source or "")
        request_id = _safe_header_value(
            getattr(response, "headers", None),
            _TAVILY_REQUEST_ID_HEADERS,
        )
        error_type = source.__class__.__name__

    if status is not None:
        metadata["tavily_http_status"] = status
    metadata["tavily_error_type"] = error_type
    sanitized_message = _sanitize_tavily_error_text(message)
    if sanitized_message:
        metadata["tavily_error_message"] = sanitized_message
    if request_id:
        metadata["tavily_request_id"] = str(request_id)
    return metadata


def _is_tavily_quota_error(exc: Exception) -> bool:
    status = _coerce_http_status(getattr(getattr(exc, "response", None), "status_code", None))  # noqa: E501
    if status in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(str(exc))


def _text_indicates_quota_or_rate_limit(text: Any) -> bool:
    msg = str(text or "").lower()
    return any(
        token in msg
        for token in [
            "quota",
            "rate limit",
            "rate-limit",
            "rate_limited",
            "ratelimit",
            "too many requests",
            "usage limit",
            "usage exceeded",
            "usage quota",
            "usage cap",
            "usage capped",
            "plan limit",
            "key limit",
            "paygo",
            "billing",
            "payment",
            "402",
            "403",
            "429",
            "432",
            "433",
        ]
    )


def _is_tavily_quota_response(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status_int = _coerce_http_status(payload.get("status") or payload.get("status_code"))  # noqa: E501
    if status_int in _TAVILY_LIMIT_STATUSES:
        return True
    return _text_indicates_quota_or_rate_limit(
        " ".join(
            str(payload.get(key) or "")
            for key in ("error", "message", "detail", "warning")
        )
    )


def _is_environment_proxy_error(exc: Exception) -> bool:
    msg = f"{exc.__class__.__name__} {exc}".lower()
    strong_markers = [
        "using socks proxy",
        "socksio",
        "proxyconnect",
        "failed to connect to proxy",
        "cannot connect to proxy",
        "can't connect to proxy",
        "could not connect to proxy",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ]
    if any(token in msg for token in strong_markers):
        return True
    connectivity_markers = [
        "temporary failure in name resolution",
        "name resolution",
        "nameresolutionerror",
        "name or service not known",
        "getaddrinfo failed",
        "failed to resolve",
        "dns",
        "connecterror",
        "connectionerror",
        "connecttimeout",
        "readtimeout",
        "connect timeout",
        "connection timeout",
        "read operation timed out",
        "timed out",
        "all connection attempts failed",
        "ssl",
        "tls",
        "certificate",
        "connection reset",
        "connection refused",
        "connection aborted",
        "network is unreachable",
        "network error",
    ]
    if any(token in msg for token in connectivity_markers):
        return True
    if "socks" in msg and "proxy" in msg and re.search(r"socks[45]?h?://", msg):  # noqa: E501
        return True
    if "proxy error" not in msg and "proxyerror" not in msg:
        return False
    local_context = [
        "connect",
        "connection",
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "socks",
        "environment",
        "env",
        "proxy_url",
        "proxies",
    ]
    return any(token in msg for token in local_context)


def _structured_audit_fields_from_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: task[key]
        for key in (
            "structured_provider_attempted",
            "structured_provider_fallback_reason",
            "structured_provider_latency_ms",
            "structured_provider_diagnostics",
            "structured_provider_name",
        )
        if key in task
    }


def _build_environment_proxy_error_records(
    task: Dict[str, Any],
    exc: Exception,
    *,
    attempt_index: int = 0,
    elapsed_ms: int = 0,
    extraction_backend: str = "deepseek",
    query_attempts: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now_ts = int(datetime.now().timestamp())
    query = task.get("query_used") or task.get("query") or task.get("indicator_key")  # noqa: E501
    note = f"environment_proxy_error:{exc}"
    source = "Stage2 manual_required"
    category = task.get("category") or task.get("stage_phase")
    task_payload = {
        **task,
        "category": category,
        "query": query,
        "query_used": task.get("query_used") or query,
        "query_attempts": query_attempts or task.get("query_attempts") or [],
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "source": source,
        "note": note,
        "environment_proxy_fast_switch": True,
    }
    extraction = {
        "value": None,
        "unit": task.get("unit"),
        "source_url": None,
        "confidence": 0.0,
        "note": note,
        "llm_error": str(exc),
        "environment_proxy_error": str(exc),
        "llm_latency_ms": 0,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "environment_proxy_fast_switch": True,
    }
    task_record = {
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "search_backend": task.get("search_backend", "tavily"),
        "fund_flow_backend": task.get("fund_flow_backend"),
        "extraction_backend": extraction_backend,
        "source": source,
        "source_url": None,
        "confidence": 0.0,
        "error": str(exc),
        "llm_error": str(exc),
        "environment_proxy_error": str(exc),
        "llm_latency_ms": None,
        "attempt_index": attempt_index,
        "elapsed_ms": elapsed_ms,
        "created_at": task.get("created_at", now_ts),
        "finished_at": now_ts,
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "note": note,
        "raw_results": [],
        "environment_proxy_fast_switch": True,
        "result_type": "manual_required",
    }
    task_record.update(_structured_audit_fields_from_task(task))
    websearch_item = {
        "task_id": task["task_id"],
        "indicator_key": task["indicator_key"],
        "category": category,
        "stage_phase": task["stage_phase"],
        "query": query,
        "task": task_payload,
        "extraction": extraction,
        "extraction_backend": extraction_backend,
        "raw_results": [],
        "search_backend": task.get("search_backend", "tavily"),
        "manual_required": True,
        "manual_reason": "environment_proxy_error",
        "source": source,
        "note": note,
        "environment_proxy_fast_switch": True,
        "result_type": "manual_required",
    }
    return task_record, websearch_item
