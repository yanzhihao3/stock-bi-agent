"""
Redis 缓存工具模块

为外部 API 响应提供缓存层，降低延迟和外部 API 调用量。
缓存穿透时自动降级为直调外部 API，不影响业务。
GET 用 params 生成缓存 key，POST 用 json body 生成缓存 key。
"""
import json
import os
import traceback
from typing import Optional, Dict, Any

import httpx
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_PREFIX = "api:"
DEFAULT_TTL = 300  # 5 分钟

_redis: Optional[aioredis.Redis] = None


async def _get_client() -> aioredis.Redis:
    """获取或创建 Redis 连接（懒加载，单例）"""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,  # 返回的 key/value 为 str 而非 bytes
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis


async def close():
    """关闭 Redis 连接（服务关闭时调用）"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None

def _make_key(url: str, params: Optional[Dict] = None) -> str:
    """从 URL + 参数生成确定性缓存键"""
    key = url
    if params:
        sorted_items = sorted(
            (k, str(v)) for k, v in params.items() if v is not None
        )
        key += "?" + "&".join(f"{k}={v}" for k, v in sorted_items)
    return CACHE_PREFIX + key


async def get_cache(url: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """读取缓存，未命中或 Redis 异常均返回 None"""
    try:
        client = await _get_client()
        key = _make_key(url, params)
        cached = await client.get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis 异常视为未命中，降级直调外部 API
    return None


async def set_cache(url: str, data: dict, params: Optional[Dict] = None, ttl: int = DEFAULT_TTL):
    """写入缓存（尽最大努力，失败不抛异常）"""
    try:
        client = await _get_client()
        key = _make_key(url, params)
        await client.setex(key, ttl, json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


async def cached_get(
    url: str,
    params: Optional[Dict] = None,
    ttl: int = DEFAULT_TTL,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """带缓存的 HTTP GET

    1. 命中缓存 → 直接返回
    2. 未命中 → 调用外部 API → 写入缓存 → 返回
    3. Redis 异常 → 自动降级为直调
    """
    # 读缓存
    cached = await get_cache(url, params)
    if cached is not None:  # None 表示未命中，而非数据为空
        return cached

    # 调外部 API
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.get(url, params=params)
        result = resp.json()

    # 写缓存
    await set_cache(url, result, params, ttl)
    return result


async def cached_post(
    url: str,
    json_data: Optional[Dict] = None,
    ttl: int = DEFAULT_TTL,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """带缓存的 HTTP POST（同上，缓存键含 json body）"""
    cached = await get_cache(url, json_data)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.post(url, json=json_data)
        result = resp.json()

    await set_cache(url, result, json_data, ttl)
    return result
