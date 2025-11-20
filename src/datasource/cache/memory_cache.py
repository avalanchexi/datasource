import time
import hashlib
from typing import Any, Optional, Dict
from loguru import logger


class MemoryCache:
    """内存缓存实现"""
    
    def __init__(self, default_ttl: int = 300):
        """
        初始化内存缓存
        
        Args:
            default_ttl: 默认缓存过期时间（秒）
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def _make_key(self, *args, **kwargs) -> str:
        """生成缓存键"""
        key_data = str(args) + str(sorted(kwargs.items()))
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self._cache:
            return None
        
        cache_entry = self._cache[key]
        current_time = time.time()
        
        if current_time > cache_entry['expires_at']:
            del self._cache[key]
            logger.debug(f"Cache key {key} expired and removed")
            return None
        
        logger.debug(f"Cache hit for key {key}")
        return cache_entry['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值"""
        if ttl is None:
            ttl = self.default_ttl
        
        expires_at = time.time() + ttl
        self._cache[key] = {
            'value': value,
            'expires_at': expires_at,
            'created_at': time.time()
        }
        logger.debug(f"Cache set for key {key} with TTL {ttl}s")
    
    def delete(self, key: str) -> bool:
        """删除缓存值"""
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache key {key} deleted")
            return True
        return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        logger.info("All cache cleared")
    
    def clean_expired(self) -> int:
        """清理过期的缓存项"""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if current_time > entry['expires_at']
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        logger.info(f"Cleaned {len(expired_keys)} expired cache entries")
        return len(expired_keys)
    
    def size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)


def cache_key(*args, **kwargs) -> str:
    """生成缓存键的辅助函数"""
    cache = MemoryCache()
    return cache._make_key(*args, **kwargs)