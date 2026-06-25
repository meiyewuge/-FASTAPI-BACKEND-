"""极简 JWT（HS256，仅用标准库，避免 ECS 上新增 PyJWT 依赖）。

只实现本系统所需的 encode/decode + 过期校验，不追求全规范覆盖。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class JWTError(Exception):
    pass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _sign(signing_input: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64e(sig)


def encode(payload: dict, secret: str, ttl_seconds: int = 7 * 24 * 3600) -> str:
    """签发 token。自动写入 iat / exp（ttl_seconds<=0 表示不过期）。"""
    body = dict(payload)
    now = int(time.time())
    body.setdefault("iat", now)
    if ttl_seconds:  # ttl_seconds==0 表示不过期；负数=已过期（便于测试）
        body["exp"] = now + ttl_seconds
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64e(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64e(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    return f"{h}.{p}.{_sign(signing_input, secret)}"


def decode(token: str, secret: str) -> dict:
    """验签 + 过期校验，返回 payload。失败抛 JWTError。"""
    try:
        h, p, sig = token.split(".")
    except (ValueError, AttributeError):
        raise JWTError("token 格式错误")
    signing_input = f"{h}.{p}".encode("ascii")
    expected = _sign(signing_input, secret)
    if not hmac.compare_digest(expected, sig):
        raise JWTError("签名校验失败")
    try:
        payload = json.loads(_b64d(p))
    except Exception:
        raise JWTError("payload 解析失败")
    exp = payload.get("exp")
    if exp is not None and int(time.time()) > int(exp):
        raise JWTError("token 已过期")
    return payload
