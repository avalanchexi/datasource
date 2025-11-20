#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SQLiteCache
-----------
轻量键值缓存，支持 TTL。用于 Tavily 搜索结果本地持久化，避免重复请求。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class SQLiteCache:
    """基于 sqlite 的简单 KV 缓存"""

    def __init__(self, db_path: Path, default_ttl: int = 3600) -> None:
        self.db_path = db_path
        self.default_ttl = default_ttl
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _ensure_table(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    payload   TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at);")

    def get(self, cache_key: str) -> Optional[Any]:
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM cache WHERE cache_key=? AND expires_at>?",
                (cache_key, now),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        payload["cache_hit"] = True
        return payload

    def set(self, cache_key: str, payload: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl or self.default_ttl
        expires_at = int(time.time()) + ttl
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO cache(cache_key, payload, expires_at) VALUES(?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, expires_at=excluded.expires_at
                """,
                (cache_key, json.dumps(payload, ensure_ascii=False), expires_at),
            )
        logger.debug(f"[SQLiteCache] set key={cache_key} ttl={ttl}s")

    def purge_expired(self) -> int:
        now = int(time.time())
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM cache WHERE expires_at<=?", (now,))
            return cur.rowcount


__all__ = ["SQLiteCache"]
