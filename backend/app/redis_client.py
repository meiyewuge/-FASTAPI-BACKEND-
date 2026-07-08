"""Redis 客户端封装 — P0B-1 ticket 存储层。

功能：
  - 惰性初始化 Redis 连接（从 settings.redis_url 读取）
  - Redis 不可用时自动降级为内存 dict + WARNING log
  - 日志脱敏：禁止输出完整 REDIS_URL（密码部分用 **** 替代）
  - ticket 读写：SET with TTL / GET / DEL

约束：
  - Redis 必须 requirepass（由运维保证，代码侧仅消费 REDIS_URL）
  - Redis 只绑定 127.0.0.1（由运维保证）
  - 报告 / 日志 / 异常栈不得输出完整 Redis 密码
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

from ..config import settings

logger = logging.getLogger("redis_client")

# ──────────────────────────────────────────────────────────────────────
# 内部状态
# ──────────────────────────────────────────────────────────────────────
_redis: Any = None           # redis.Redis 实例或 None
_init_attempted: bool = False  # 是否已尝试过初始化

# 内存降级存储（Redis 不可用时使用）
_MEMORY_TICKETS: Dict[str, Dict[str, Any]] = {}
_MEMORY_TTLS: Dict[str, float] = {}  # ticket -> expire_at (unix timestamp)


# ──────────────────────────────────────────────────────────────────────
# URL 脱敏
# ──────────────────────────────────────────────────────────────────────
def _sanitize_url(url: str) -> str:
    """将 Redis URL 中的密码替换为 ****，用于日志输出。

    示例效果：带密码的 URL 显示为 redis://<掩码>@127.0.0.1:6379/0
    """
    try:
        parsed = urlparse(url)
        if parsed.password:
            # 重建 netloc：user:****@host:port
            netloc = f"{parsed.username or ''}:****@{parsed.hostname or '127.0.0.1'}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return "redis://(unconfigured)"


# ──────────────────────────────────────────────────────────────────────
# Redis 初始化
# ──────────────────────────────────────────────────────────────────────
def _init_redis() -> Any:
    """尝试初始化 Redis 连接。失败返回 None（降级内存模式）。"""
    global _redis, _init_attempted
    _init_attempted = True

    if not settings.redis_url:
        logger.warning(
            "REDIS_URL not configured — ticket store running in MEMORY mode. "
            "Production MUST set REDIS_URL in .env"
        )
        return None

    try:
        import redis as _redis_lib
        client = _redis_lib.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        logger.info(
            "Redis connected | url=%s | mode=requirepass",
            _sanitize_url(settings.redis_url),
        )
        _redis = client
        return client
    except Exception as exc:
        logger.warning(
            "Redis connection FAILED — falling back to MEMORY mode | url=%s | error=%s",
            _sanitize_url(settings.redis_url),
            str(exc)[:120],  # 截断防止异常信息泄露密码
        )
        _redis = None
        return None


def get_redis() -> Any:
    """获取 Redis 客户端。首次调用时惰性初始化；失败则返回 None。"""
    if _redis is not None:
        return _redis
    if _init_attempted:
        return None
    return _init_redis()


# ──────────────────────────────────────────────────────────────────────
# Ticket 读写（统一接口，Redis / 内存自动切换）
# ──────────────────────────────────────────────────────────────────────
TICKET_TTL = 300  # 秒（5 分钟）
KEY_PREFIX = "wuyou:ticket:"


def ticket_set(ticket: str, data: dict, ttl: int = TICKET_TTL) -> None:
    """写入 ticket。优先 Redis，不可用时降级内存。"""
    value = json.dumps(data, ensure_ascii=False)
    r = get_redis()
    if r is not None:
        try:
            r.setex(f"{KEY_PREFIX}{ticket}", ttl, value)
            return
        except Exception as exc:
            logger.warning("Redis SET failed, fallback to memory | error=%s", str(exc)[:120])

    # 内存降级
    _MEMORY_TICKETS[ticket] = data
    _MEMORY_TTLS[ticket] = time.time() + ttl


def ticket_get(ticket: str) -> Optional[dict]:
    """读取 ticket 数据。不存在或已过期返回 None。"""
    r = get_redis()
    if r is not None:
        try:
            raw = r.get(f"{KEY_PREFIX}{ticket}")
            if raw is not None:
                return json.loads(raw)
            return None
        except Exception as exc:
            logger.warning("Redis GET failed, fallback to memory | error=%s", str(exc)[:120])

    # 内存降级
    expire_at = _MEMORY_TTLS.get(ticket)
    if expire_at is None:
        return None
    if time.time() > expire_at:
        # 已过期，清理
        _MEMORY_TICKETS.pop(ticket, None)
        _MEMORY_TTLS.pop(ticket, None)
        return None
    return _MEMORY_TICKETS.get(ticket)


def ticket_delete(ticket: str) -> None:
    """删除 ticket（一次性消费）。"""
    r = get_redis()
    if r is not None:
        try:
            r.delete(f"{KEY_PREFIX}{ticket}")
            return
        except Exception:
            pass

    # 内存降级
    _MEMORY_TICKETS.pop(ticket, None)
    _MEMORY_TTLS.pop(ticket, None)
