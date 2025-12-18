#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS Patch: 在缺失 /etc/resolv.conf 或 DNS 失效时，用 DoH(A 记录) 兜底解析域名。

背景：某些容器/WSL 环境可能没有系统 DNS 配置，导致 socket.getaddrinfo 全部失败。
该补丁通过 monkey patch socket.getaddrinfo，在解析失败时调用 Cloudflare DoH（1.1.1.1）。
"""

from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

from loguru import logger


_PATCHED = False
_ORIG_GETADDRINFO = None
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_CACHE_MAX = 256


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except Exception:
        return False


def _get_doh_proxies() -> Optional[Dict[str, str]]:
    """
    DoH 代理配置（可选）。

    说明：在某些环境里“直连 HTTPS”不可用，但本机 HTTP 代理可用（例如公司/本机代理）。
    通过 DATASOURCE_DOH_PROXY 显式指定，可在清空 http_proxy/https_proxy 后仍可解析 DNS。
    """
    proxy = (os.getenv("DATASOURCE_DOH_PROXY") or "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _doh_query_a(host: str, timeout_s: float = 5.0) -> Tuple[List[str], Optional[int]]:
    """
    通过 Cloudflare DoH (1.1.1.1) 查询 A 记录。
    返回 (ips, ttl)；ttl 取 Answer 中 A 记录的最小 TTL（若缺失则 None）。
    """
    import requests  # 延迟导入，避免非网络场景额外依赖

    endpoints = [
        "https://1.1.1.1/dns-query",
        "https://1.0.0.1/dns-query",
    ]
    headers = {"accept": "application/dns-json"}
    params = {"name": host, "type": "A"}
    proxies = _get_doh_proxies()

    last_err: Optional[Exception] = None
    for endpoint in endpoints:
        for attempt in range(2):
            try:
                session = requests.Session()
                # 默认不读环境代理，避免与业务请求的代理策略耦合；如需代理，仅通过 DATASOURCE_DOH_PROXY 显式指定。
                session.trust_env = False
                resp = session.get(
                    endpoint,
                    params=params,
                    headers=headers,
                    timeout=(timeout_s, timeout_s),
                    proxies=proxies,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("Status") != 0:
                    return [], None

                answers = data.get("Answer") or []
                ips: List[str] = []
                ttls: List[int] = []
                for ans in answers:
                    # type: 1 = A, 5 = CNAME
                    if ans.get("type") == 1 and ans.get("data"):
                        ips.append(str(ans["data"]))
                        if isinstance(ans.get("TTL"), int):
                            ttls.append(ans["TTL"])

                ttl = min(ttls) if ttls else None
                return ips, ttl
            except Exception as e:
                last_err = e
                # 简单退避，避免瞬时抖动
                time.sleep(0.2 * (attempt + 1))

    if last_err is not None:
        proxy_hint = f", proxy={proxies.get('https')}" if proxies else ""
        logger.debug(f"DoH resolve failed for {host}{proxy_hint}: {last_err}")
    return [], None


def _cache_get(host: str) -> Optional[List[str]]:
    now = time.time()
    with _CACHE_LOCK:
        item = _CACHE.get(host)
        if not item:
            return None
        expires_at, ips = item
        if expires_at <= now:
            _CACHE.pop(host, None)
            return None
        return list(ips)


def _cache_set(host: str, ips: List[str], ttl: Optional[int]) -> None:
    if not ips:
        return
    ttl_s = int(ttl) if ttl and ttl > 0 else 60
    expires_at = time.time() + min(ttl_s, 300)
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            # 简单淘汰：移除一个最早过期项
            oldest_key = None
            oldest_exp = None
            for k, (exp, _) in _CACHE.items():
                if oldest_exp is None or exp < oldest_exp:
                    oldest_key = k
                    oldest_exp = exp
            if oldest_key:
                _CACHE.pop(oldest_key, None)
        _CACHE[host] = (expires_at, list(ips))


def _should_enable_dns_patch() -> bool:
    if os.getenv("DATASOURCE_DNS_PATCH", "1").strip() in {"0", "false", "False"}:
        return False
    if os.getenv("DATASOURCE_FORCE_DNS_PATCH", "").strip() in {"1", "true", "True"}:
        return True
    # 常见失效场景：/etc/resolv.conf 缺失或为空
    try:
        if not os.path.exists("/etc/resolv.conf"):
            return True
        if os.path.getsize("/etc/resolv.conf") == 0:
            return True
    except Exception:
        return True
    return False


def apply_dns_patch() -> bool:
    """
    Patch socket.getaddrinfo: 当系统解析失败时，用 DoH 解析域名并返回结果。
    """
    global _PATCHED, _ORIG_GETADDRINFO
    if _PATCHED:
        return True
    if not _should_enable_dns_patch():
        return False

    _ORIG_GETADDRINFO = socket.getaddrinfo

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host is None:
            return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
        if isinstance(host, bytes):
            try:
                host_str = host.decode("utf-8", errors="ignore")
            except Exception:
                host_str = str(host)
        else:
            host_str = str(host)

        if _is_ip_literal(host_str):
            return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)

        try:
            return _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
        except socket.gaierror:
            cached = _cache_get(host_str)
            if cached:
                results = []
                for ip in cached:
                    results.extend(_ORIG_GETADDRINFO(ip, port, family, type, proto, flags))
                return results

            ips, ttl = _doh_query_a(host_str)
            if not ips:
                raise
            _cache_set(host_str, ips, ttl)

            results = []
            for ip in ips:
                results.extend(_ORIG_GETADDRINFO(ip, port, family, type, proto, flags))
            return results

    socket.getaddrinfo = patched_getaddrinfo  # type: ignore[assignment]
    _PATCHED = True
    logger.warning("DNS patch enabled: DoH fallback via 1.1.1.1 (socket.getaddrinfo)")
    return True
