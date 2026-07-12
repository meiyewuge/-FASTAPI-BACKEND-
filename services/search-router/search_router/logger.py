"""日志初始化 + 脱敏工具。

desensitize_key(key) → "sk-x8****k9z"
desensitize_url(url) → "domain/path?q=***"
LOG_DESENSITIZE=true 时强制脱敏。
"""

from __future__ import annotations

import logging
import re

# 脱敏开关（默认 True，安全优先）
_DESENSITIZE_ENABLED = True


def set_desensitize(enabled: bool) -> None:
    """设置脱敏开关。"""
    global _DESENSITIZE_ENABLED
    _DESENSITIZE_ENABLED = enabled


def is_desensitize_enabled() -> bool:
    """脱敏是否启用。"""
    return _DESENSITIZE_ENABLED


# ── Key 脱敏 ──────────────────────────────────────────

def desensitize_key(key: str) -> str:
    """API Key 脱敏：前 4 后 4 可见，中间用 **** 替代。

    示例：
        "sk-x8k9z1234567890abcd" → "sk-x****abcd"
        "abc" → "a***" (太短的 key 全脱敏)
        "" → ""
    """
    if not key:
        return ""

    if not _DESENSITIZE_ENABLED:
        return key

    # 去除前后空白
    key = key.strip()

    # 太短的 key（<=8 字符）只保留首字符
    if len(key) <= 8:
        return key[0] + "***" if key else ""

    # 前 4 后 4 可见
    prefix = key[:4]
    suffix = key[-4:]
    return f"{prefix}****{suffix}"


# ── URL 脱敏 ──────────────────────────────────────────

# 需要脱敏的 query 参数名（不区分大小写）
_SENSITIVE_QUERY_PARAMS = {
    "token", "access_token", "api_key", "apikey", "api-key",
    "key", "secret", "password", "pwd", "auth",
    "authorization", "session", "sessionid", "sid",
    "signature", "sign", "hash",
}


def desensitize_url(url: str) -> str:
    """URL 脱敏：对敏感 query 参数值替换为 ***。

    使用正则替换，不破坏原始 URL 编码。

    示例：
        "https://api.example.com/search?q=test&token=abc123"
        → "https://api.example.com/search?q=test&token=***"

        "https://api.example.com/path?key=sk-xxx"
        → "https://api.example.com/path?key=***"
    """
    if not url:
        return ""

    if not _DESENSITIZE_ENABLED:
        return url

    # 用正则替换敏感参数值，不使用 urlparse/urlencode 避免编码问题
    # 匹配 pattern: param=value（value 到 & 或 # 或字符串结尾）
    # 构建正则: (param1|param2|...)=([^&#\s]+)
    param_pattern = "|".join(re.escape(p) for p in _SENSITIVE_QUERY_PARAMS)
    pattern = rf'({param_pattern})=([^&#\s]+)'
    return re.sub(pattern, r'\1=***', url, flags=re.IGNORECASE)


def _desensitize_raw_url(url: str) -> str:
    """对无法解析的 URL 做简单脱敏：替换 token=/key= 后面的值。"""
    # 替换 token=xxx / key=xxx / api_key=xxx 等
    pattern = r'((?:token|api_key|apikey|api-key|key|secret|password|auth)=[^&\s]+)'
    return re.sub(pattern, r'\1=***', url, flags=re.IGNORECASE)


# ── 日志初始化 ────────────────────────────────────────

def _resolve_level(level: str | int) -> int:
    """将日志级别归一化为 logging 整数级别。

    兼容 str（如 "INFO" / "debug"）与 int（如 logging.INFO / 20）。
    无法识别时回退 logging.INFO。
    """
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def setup_logger(
    name: str = "search_router",
    level: str | int = "INFO",
    desensitize: bool = True,
) -> logging.Logger:
    """初始化日志器。

    Args:
        name: 日志器名称
        level: 日志级别，兼容 str（"INFO"）与 int（logging.INFO）
        desensitize: 是否启用脱敏。True 时自动挂载 DesensitizeFilter 到 handler。
    """
    global _DESENSITIZE_ENABLED
    _DESENSITIZE_ENABLED = desensitize

    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    resolved_level = _resolve_level(level)
    logger.setLevel(resolved_level)

    handler = logging.StreamHandler()
    handler.setLevel(resolved_level)

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    # desensitize=True 时挂载 DesensitizeFilter 到 handler
    if desensitize:
        handler.addFilter(DesensitizeFilter())

    logger.addHandler(handler)

    # 防止日志传播到 root logger
    logger.propagate = False

    return logger


class DesensitizeFilter(logging.Filter):
    """日志脱敏过滤器：对日志记录中的 Key/URL 进行脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """对日志消息中的 Key/URL 脱敏。"""
        if not _DESENSITIZE_ENABLED:
            return True

        msg = str(record.msg)
        # 对消息中出现的 URL 做脱敏
        record.msg = _desensitize_message(msg)
        return True


def _desensitize_message(msg: str) -> str:
    """对日志消息中出现的 URL 和疑似 Key 做脱敏。"""
    if not msg:
        return msg

    # 对 http:// 和 https:// 开头的 URL 做脱敏
    url_pattern = r'https?://[^\s\'"<>]+'
    def _replace_url(match: re.Match) -> str:
        return desensitize_url(match.group(0))
    msg = re.sub(url_pattern, _replace_url, msg)

    # 对疑似 API Key 做脱敏（sk- / AKID / ghp_ / github_pat_ 前缀）
    key_patterns = [
        r'sk-[a-zA-Z0-9]{8,}',
        r'AKID[a-zA-Z0-9]{8,}',
        r'ghp_[a-zA-Z0-9]{8,}',
        r'github_pat_[a-zA-Z0-9]{8,}',
    ]
    for pattern in key_patterns:
        def _replace_key(match: re.Match) -> str:
            return desensitize_key(match.group(0))
        msg = re.sub(pattern, _replace_key, msg)

    return msg
