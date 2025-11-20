import asyncio
import time
from typing import Dict
from loguru import logger


class RateLimiter:
    """异步速率限制器"""
    
    def __init__(self, rate_limit: int = 10):
        """
        初始化速率限制器
        
        Args:
            rate_limit: 每秒允许的请求数量
        """
        self.rate_limit = rate_limit
        self.interval = 1.0 / rate_limit if rate_limit > 0 else 0
        self.last_request_time = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """获取请求许可"""
        async with self._lock:
            current_time = time.time()
            time_since_last_request = current_time - self.last_request_time
            
            if time_since_last_request < self.interval:
                sleep_time = self.interval - time_since_last_request
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
            
            self.last_request_time = time.time()


class RateLimiterManager:
    """速率限制器管理器"""
    
    def __init__(self):
        self._limiters: Dict[str, RateLimiter] = {}
    
    def get_limiter(self, source_name: str, rate_limit: int) -> RateLimiter:
        """获取或创建指定数据源的速率限制器"""
        if source_name not in self._limiters:
            self._limiters[source_name] = RateLimiter(rate_limit)
        return self._limiters[source_name]
    
    def update_limiter(self, source_name: str, rate_limit: int):
        """更新速率限制器配置"""
        self._limiters[source_name] = RateLimiter(rate_limit)