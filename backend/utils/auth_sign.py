"""火山引擎 AK/SK 签名（HMAC-SHA256 V4），用于 VOLC_AUTH_MODE=aksk。

实现火山标准签名：X-Date + X-Content-Sha256 + Authorization。
密钥仅从环境/配置读取，绝不硬编码、不打印、不入响应。

注：火山方舟 Ark /api/v3 端点通常用 Bearer API Key；AK/SK 签名用于火山
OpenAPI 风格服务。本模块作为可切换鉴权提供，默认仍走 bearer。
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import urlparse


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, short_date: str, region: str, service: str) -> bytes:
    k_date = _hmac(secret_key.encode("utf-8"), short_date)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "request")


def signed_headers(
    method: str,
    url: str,
    body: bytes,
    ak: str,
    sk: str,
    region: str = "cn-beijing",
    service: str = "ark",
    now: datetime | None = None,
) -> dict[str, str]:
    """返回需要附加到请求上的签名头。"""
    now = now or datetime.now(timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]

    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    canonical_query = parsed.query  # 调用方需保证 query 已规范排序（本项目无 query）

    payload_hash = _sha256_hex(body or b"")

    canonical_headers = (
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed = "host;x-content-sha256;x-date"

    canonical_request = "\n".join(
        [method.upper(), path, canonical_query, canonical_headers, signed, payload_hash]
    )

    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        ["HMAC-SHA256", x_date, credential_scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )

    key = _signing_key(sk, short_date, region, service)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Host": host,
    }
