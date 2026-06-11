#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stage2 Health Check
- 检查必需环境变量、代理配置、缓存路径可写性
- 可选快速连通性（HEAD Tavily / DeepSeek）
"""

import os
import pathlib
import sys
import http.client
import urllib.parse

REQUIRED_ENV = ["TAVILY_API_KEY", "DEEPSEEK_API_KEY"]


def check_env():
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    return missing


def check_path(path_str: str) -> bool:
    p = pathlib.Path(path_str)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        test = p.with_suffix(p.suffix + ".chk")
        test.write_text("ok", encoding="utf-8")
        test.unlink()
        return True
    except Exception:
        return False


def _ping(url: str, timeout: float = 3.0) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=timeout)
        conn.request("HEAD", parsed.path or "/")
        resp = conn.getresponse()
        return resp.status < 500
    except Exception:
        return False


def main():
    missing = check_env()
    if missing:
        print(f"[FAIL] Missing env: {', '.join(missing)}")
    else:
        print("[OK] Env variables present")

    cache_ok = check_path(os.getenv("TAVILY_CACHE_PATH", "data/cache/tavily_cache.sqlite"))
    print(f"[{'OK' if cache_ok else 'FAIL'}] Cache path writable")

    tavily_ping = _ping("https://api.tavily.com")
    deepseek_ping = _ping(os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    print(f"[{'OK' if tavily_ping else 'WARN'}] Tavily connectivity")
    print(f"[{'OK' if deepseek_ping else 'WARN'}] DeepSeek connectivity")

    if missing or not cache_ok:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
