"""SafeTransport — IP固定连接、peer IP复核、手动重定向安全栈。

V1.4修正（ChatGPT终审V1.3 NEED_ONE_FINAL_MICROFIX）：
- 三、_bounded_gzip_decompress EOF完整性检查：截断gzip流必须返回gzip_invalid_stream
- 四、_check_response_limits中ERR_GZIP_INVALID_STREAM不再pass，已判定is_gzip时必须fail-closed

V1.3修正（ChatGPT终审V1.2 PASS_WITH_ONE_BLOCKING_MICROFIX）：
- 一、FakeTransport: sentinel区分content_length未传 vs 显式None
  - _AUTO_LENGTH = object() → 未传参数时自动用len(body)
  - content_length=None → 服务器没有Content-Length，模拟分块读取
  - 分块累计至max+1停止，bytes_read <= max+1
- 二、_bounded_gzip_decompress替代无限制flush()
  - 每次decompress()传max_length=remaining+1
  - 不使用无限制flush()
  - 处理unconsumed_tail
  - 拒绝拼接gzip成员(gzip_concatenated_member_rejected)
  - 损坏流返回gzip_invalid_stream
  - 解压成功后HTML解析使用解压后的bytes
  - 不把解压正文写入日志
"""
from __future__ import annotations

import asyncio
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse, urljoin

from search_router.enrichers.resolution_ticket import (
    ResolutionTicket,
    TicketValidator,
    TicketValidationError,
    issue_ticket,
    is_safe_ip,
    validate_peer_ip,
)


# ── 常量 ────────────────────────────────────────────────

_MAX_REDIRECTS = 2
_MAX_RESPONSE_BYTES = 524288  # 512KB
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 10.0
_TOTAL_TIMEOUT = 15.0
_USER_AGENT = "WuYouSearchRouter/1.0"
_ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
_ROBOTS_ALLOWED_CONTENT_TYPES = {"text/plain"}
_ROBOTS_MAX_RESPONSE_BYTES = 65536  # 64KB for robots
_GZIP_CHUNK_SIZE = 8192

# 错误码枚举（固定，不含IP/URL/异常原文）
ERR_DNS_RESOLUTION_ERROR = "dns_resolution_error"
ERR_DNS_TIMEOUT = "dns_timeout"
ERR_USERINFO_IN_URL = "userinfo_in_url"
ERR_INVALID_SCHEME = "invalid_scheme"
ERR_INVALID_PORT = "invalid_port"
ERR_DOMAIN_NOT_APPROVED = "domain_not_approved"
ERR_UNSAFE_IP = "unsafe_ip"
ERR_TICKET_ERROR = "ticket_error"
ERR_TICKET_CONSUME_FAILED = "ticket_consume_failed"
ERR_PEER_IP_MISMATCH = "peer_ip_mismatch"
ERR_BLOCKED_TRANSPORT = "blocked_transport_not_configured"
ERR_CONNECT_TIMEOUT = "connect_timeout"
ERR_READ_TIMEOUT = "read_timeout"
ERR_TOTAL_TIMEOUT = "total_timeout"
ERR_CONTENT_LENGTH_EXCEEDED = "content_length_exceeded"
ERR_STREAM_LIMIT_EXCEEDED = "stream_limit_exceeded"
ERR_GZIP_DECOMPRESS_LIMIT = "gzip_decompress_limit_exceeded"
ERR_GZIP_INVALID_STREAM = "gzip_invalid_stream"
ERR_GZIP_CONCATENATED_MEMBER = "gzip_concatenated_member_rejected"
ERR_NON_HTML_CONTENT = "non_html_content"
ERR_REDIRECT_LIMIT = "redirect_limit_exceeded"
ERR_REDIRECT_INVALID = "redirect_invalid"
ERR_REDIRECT_NON_HTTP = "redirect_non_http_https"
ERR_REDIRECT_USERINFO = "redirect_userinfo_present"
ERR_REDIRECT_INVALID_PORT = "redirect_invalid_port"
ERR_REDIRECT_DOMAIN_NOT_APPROVED = "redirect_domain_not_approved"
ERR_REDIRECT_MISSING = "redirect_location_missing"


# ── Sentinel ──────────────────────────────────────────

_AUTO_LENGTH = object()


# ── FetchResult ────────────────────────────────────────

@dataclass(frozen=True)
class FetchResult:
    """SafeTransport fetch结果。

    不得包含Cookie、Authorization、完整query或正文日志。
    body为str（UTF-8解码后），bytes_read登记实际传输字节数。
    """
    status: int
    content_type: str
    body: str
    peer_ip: str
    redirect_location: str | None
    bytes_read: int
    final_url_safe: str  # 脱敏URL：scheme://hostname
    error_code: str | None


# ── 有界gzip解压 ──────────────────────────────────────

def _bounded_gzip_decompress(
    compressed: bytes,
    max_output_bytes: int = _MAX_RESPONSE_BYTES,
) -> tuple[bytes | None, str | None]:
    """有界gzip解压。

    不使用无限制flush()。每次decompress()传max_length=remaining+1。
    拒绝拼接gzip成员。损坏流返回gzip_invalid_stream。

    Returns:
        (decompressed_bytes, None) — 成功
        (None, error_code) — 失败
    """
    if not compressed or len(compressed) < 2:
        return None, ERR_GZIP_INVALID_STREAM

    # 检查gzip magic bytes
    if compressed[0] != 0x1F or compressed[1] != 0x8B:
        return None, ERR_GZIP_INVALID_STREAM

    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decompressed_parts: list[bytes] = []
    decompressed_size = 0
    offset = 0

    while offset < len(compressed):
        chunk = compressed[offset:offset + _GZIP_CHUNK_SIZE]
        offset += _GZIP_CHUNK_SIZE

        try:
            remaining = max_output_bytes - decompressed_size
            if remaining <= 0:
                return None, ERR_GZIP_DECOMPRESS_LIMIT

            out = decompressor.decompress(chunk, max_length=remaining + 1)
            decompressed_size += len(out)

            if decompressed_size > max_output_bytes:
                return None, ERR_GZIP_DECOMPRESS_LIMIT

            if out:
                decompressed_parts.append(out)

            # unconsumed_tail: 容量耗尽后仍有未解压数据
            if decompressor.unconsumed_tail:
                return None, ERR_GZIP_DECOMPRESS_LIMIT

        except zlib.error:
            return None, ERR_GZIP_INVALID_STREAM

    # 有界flush替代: 使用decompress(b"", max_length=...)逐段读取
    try:
        while True:
            remaining = max_output_bytes - decompressed_size
            if remaining <= 0:
                return None, ERR_GZIP_DECOMPRESS_LIMIT
            tail = decompressor.decompress(b"", max_length=remaining + 1)
            if not tail:
                break
            decompressed_size += len(tail)
            if decompressed_size > max_output_bytes:
                return None, ERR_GZIP_DECOMPRESS_LIMIT
            decompressed_parts.append(tail)
    except zlib.error:
        return None, ERR_GZIP_INVALID_STREAM

    # V1.4: EOF完整性检查 — 截断流必须拒绝
    if not decompressor.eof:
        return None, ERR_GZIP_INVALID_STREAM

    # 检查拼接gzip成员（decompressor结束后unused_data含剩余字节）
    if decompressor.unused_data:
        # 存在第二个gzip成员 → 拒绝
        return None, ERR_GZIP_CONCATENATED_MEMBER

    if not decompressed_parts:
        return b"", None

    return b"".join(decompressed_parts), None


# ── Transport Protocol ─────────────────────────────────

class TransportProtocol(Protocol):
    """底层Transport协议 — 必须显式注入，不提供默认Fake。

    V1.2: 显式参数锁定真实Transport必须遵守的接口。
    底层Transport不得在内存中构造超过max_response_bytes+1的body。
    """
    async def raw_fetch(
        self,
        url: str,
        approved_ip: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        max_response_bytes: int,
        user_agent: str,
        trust_env: bool,
    ) -> dict[str, Any]: ...


# ── FakeTransport（仅测试使用）──────────────────────────

class FakeTransport:
    """Fake Transport实现 — 不联网，返回预设响应。

    ⚠️ 仅用于测试。SafeTransport不自动创建FakeTransport。
    V1.3: sentinel区分content_length未传 vs 显式None。
    """
    TEST_ONLY = True  # 标记：仅测试用

    def __init__(
        self,
        default_status: int = 200,
        default_content_type: str = "text/html",
        default_body: bytes = b"<html><body>test</body></html>",
        default_peer_ip: str = "1.2.3.4",
    ) -> None:
        self._default_status = default_status
        self._default_content_type = default_content_type
        self._default_body = default_body
        self._default_peer_ip = default_peer_ip
        self._responses: dict[str, dict[str, Any]] = {}
        self._call_log: list[dict[str, Any]] = []

    def set_response(
        self,
        url: str,
        status: int = 200,
        content_type: str = "text/html",
        body: bytes | str = b"",
        peer_ip: str = "1.2.3.4",
        redirect_location: str | None = None,
        content_length: Any = _AUTO_LENGTH,
    ) -> None:
        """为特定URL预设响应。body统一为bytes。

        V1.3: content_length使用sentinel区分：
        - 未传参数(_AUTO_LENGTH): 自动使用len(body)
        - 显式传None: 服务器没有Content-Length
        - 显式传int: 使用该值
        """
        if isinstance(body, str):
            body = body.encode("utf-8")
        if content_length is _AUTO_LENGTH:
            stored_length = len(body)
        else:
            stored_length = content_length  # 可以是None或int
        self._responses[url] = {
            "status": status,
            "content_type": content_type,
            "body": body,
            "peer_ip": peer_ip,
            "redirect_location": redirect_location,
            "content_length": stored_length,
        }

    @property
    def call_count(self) -> int:
        """Transport调用总次数（可审计）。"""
        return len(self._call_log)

    @property
    def call_log(self) -> list[dict[str, Any]]:
        """完整调用日志（脱敏）。"""
        return list(self._call_log)

    async def raw_fetch(
        self,
        url: str,
        approved_ip: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_response_bytes: int = 524288,
        user_agent: str = _USER_AGENT,
        trust_env: bool = False,
    ) -> dict[str, Any]:
        """模拟底层fetch：记录参数，模拟限长责任。

        V1.3: content_length=None时模拟分块读取：
        - 累计最多max+1
        - 超限立即停止
        - 不构造超过max+1的body
        """
        entry = {
            "url_safe": _sanitize_url(url),
            "approved_ip": approved_ip,
            "connect_timeout": connect_timeout,
            "read_timeout": read_timeout,
            "max_response_bytes": max_response_bytes,
            "user_agent": user_agent,
            "trust_env": trust_env,
            "timestamp": time.monotonic(),
        }
        self._call_log.append(entry)

        resp = self._responses.get(url)
        if resp is None:
            resp = {
                "status": self._default_status,
                "content_type": self._default_content_type,
                "body": self._default_body,
                "peer_ip": self._default_peer_ip,
                "redirect_location": None,
                "content_length": len(self._default_body),
            }

        # B1: Transport限长责任模拟
        body = resp.get("body", b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        content_length = resp.get("content_length")

        if content_length is not None and content_length > max_response_bytes:
            # Content-Length超限 → body读取0字节
            resp = dict(resp)
            resp["body"] = b""
            resp["bytes_read"] = 0
            resp["transport_limit_exceeded"] = True
        elif content_length is None:
            # V1.3: 无Content-Length，模拟分块读取
            # 累计最多max_response_bytes+1，超限立即停止
            limit = max_response_bytes + 1
            if len(body) > limit:
                truncated = body[:limit]
                resp = dict(resp)
                resp["body"] = truncated
                resp["bytes_read"] = len(truncated)
                resp["transport_limit_exceeded"] = True
            else:
                resp = dict(resp)
                resp["bytes_read"] = len(body)
        else:
            resp = dict(resp)
            resp["bytes_read"] = len(body)

        return resp


# ── SafeResolver (Fake) ────────────────────────────────

class SafeResolver:
    """Fake DNS解析器 — 返回预设IP列表。"""

    def __init__(self, default_ips: list[str] | None = None) -> None:
        self._default_ips = default_ips or ["1.2.3.4"]
        self._overrides: dict[str, list[str]] = {}
        self._call_log: list[dict[str, Any]] = []

    def set_ips(self, hostname: str, ips: list[str]) -> None:
        """为特定hostname预设DNS结果。"""
        self._overrides[hostname] = ips

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    async def resolve(self, hostname: str) -> list[str]:
        """DNS解析（Fake）。"""
        self._call_log.append({"hostname": hostname, "timestamp": time.monotonic()})
        return self._overrides.get(hostname, self._default_ips)


# ── SafeTransport ──────────────────────────────────────

class SafeTransport:
    """安全Transport — IP固定连接、peer IP复核、重定向安全。

    核心安全特性：
    - 只连接到DNS预解析的IP（Ticket机制）
    - 连接前消费Ticket（防重放）
    - peer IP复核（防MITM IP漂移）
    - 批准域名锁定（DNS之前拦截）
    - 三层超时（DNS 5s / 读取 10s / 总体 15s）
    - 响应体限长（Content-Length + 流式 + gzip）
    - 有界gzip解压（V1.3: 不使用无限制flush）
    - 非HTML拒绝
    - 重定向安全（重新签票+域名审批）
    - 完全脱敏日志

    不提供默认FakeTransport，必须显式注入。
    """

    def __init__(
        self,
        resolver: SafeResolver | None = None,
        transport: TransportProtocol | None = None,
        approved_domains: set[str] | None = None,
    ) -> None:
        self._resolver = resolver or SafeResolver()
        self._transport = transport
        self._approved_domains = approved_domains or set()
        self._audit_log: list[dict[str, Any]] = []
        self._ticket_validator = TicketValidator()

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """审计日志（脱敏，不含正文/IP原文）。"""
        return list(self._audit_log)

    async def fetch(
        self,
        url: str,
        approved_domains: set[str] | None = None,
    ) -> FetchResult:
        """安全fetch — 全流程IP锁定 + 域名审批 + 限长。

        Args:
            url: 目标URL
            approved_domains: 批准域名集合。
                None=使用构造时默认；
                显式空集合=全部拒绝。
        """
        # A4: 显式空集合=全部拒绝
        domains = (
            self._approved_domains
            if approved_domains is None
            else approved_domains
        )

        if self._transport is None:
            return FetchResult(
                status=0, content_type="", body="", peer_ip="",
                redirect_location=None, bytes_read=0,
                final_url_safe=_sanitize_url(url),
                error_code=ERR_BLOCKED_TRANSPORT,
            )

        # A2: 总体15秒超时
        try:
            return await asyncio.wait_for(
                self._fetch_with_redirects(url, domains),
                timeout=_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return FetchResult(
                status=0, content_type="", body="", peer_ip="",
                redirect_location=None, bytes_read=0,
                final_url_safe=_sanitize_url(url),
                error_code=ERR_TOTAL_TIMEOUT,
            )

    async def fetch_robots(
        self,
        url: str,
        approved_domains: set[str] | None = None,
    ) -> FetchResult:
        """安全fetch robots — 与fetch结构相同，但接受text/plain、限64KB。

        Args:
            url: 目标URL（robots.txt）
            approved_domains: 批准域名集合。
                None=使用构造时默认；
                显式空集合=全部拒绝。
        """
        domains = (
            self._approved_domains
            if approved_domains is None
            else approved_domains
        )

        if self._transport is None:
            return FetchResult(
                status=0, content_type="", body="", peer_ip="",
                redirect_location=None, bytes_read=0,
                final_url_safe=_sanitize_url(url),
                error_code=ERR_BLOCKED_TRANSPORT,
            )

        try:
            return await asyncio.wait_for(
                self._fetch_with_redirects(
                    url, domains,
                    allowed_content_types=_ROBOTS_ALLOWED_CONTENT_TYPES,
                    max_response_bytes=_ROBOTS_MAX_RESPONSE_BYTES,
                ),
                timeout=_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return FetchResult(
                status=0, content_type="", body="", peer_ip="",
                redirect_location=None, bytes_read=0,
                final_url_safe=_sanitize_url(url),
                error_code=ERR_TOTAL_TIMEOUT,
            )

    async def _fetch_with_redirects(
        self,
        url: str,
        approved_domains: set[str],
        *,
        allowed_content_types: set[str] | None = None,
        max_response_bytes: int | None = None,
    ) -> FetchResult:
        """带重定向的fetch内部实现。"""
        current_url = url
        redirect_count = 0

        while True:
            # ── Step 1: URL解析 ──
            try:
                parsed = urlparse(current_url)
            except Exception:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_REDIRECT_INVALID,
                )

            hostname = (parsed.hostname or "").lower().rstrip(".")
            scheme = parsed.scheme
            port = parsed.port

            # ── Step 2: 拒绝userinfo ──
            if parsed.username or parsed.password:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_USERINFO_IN_URL,
                )

            # ── Step 3: 校验scheme和port ──
            if scheme not in ("http", "https"):
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_INVALID_SCHEME,
                )
            if port is None:
                port = 443 if scheme == "https" else 80
            if port not in (80, 443):
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_INVALID_PORT,
                )

            # ── Step 4: 校验批准域名（DNS之前！）──
            if not self._is_domain_approved(hostname, approved_domains):
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_DOMAIN_NOT_APPROVED,
                )

            # ── Step 5: DNS解析（A1: 5秒超时）──
            try:
                resolved_ips = await asyncio.wait_for(
                    self._resolver.resolve(hostname),
                    timeout=_CONNECT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_DNS_TIMEOUT,
                )
            except Exception:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_DNS_RESOLUTION_ERROR,
                )

            # ── Step 6: 全部IP安全检查（任一危险→整票拒绝）──
            for ip in resolved_ips:
                if not is_safe_ip(ip):
                    return FetchResult(
                        status=0, content_type="", body="", peer_ip="",
                        redirect_location=None, bytes_read=0,
                        final_url_safe=_sanitize_url(current_url),
                        error_code=ERR_UNSAFE_IP,
                    )

            # ── Step 7: 签发Ticket ──
            try:
                current_ticket = issue_ticket(
                    scheme=scheme, hostname=hostname, port=port,
                    resolved_ips=resolved_ips,
                )
            except TicketValidationError:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_TICKET_ERROR,
                )

            # ── Step 8: 消费Ticket（在raw_fetch之前！）──
            consume_result = self._ticket_validator.validate_and_consume(current_ticket, current_url)
            if not consume_result["valid"]:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_TICKET_CONSUME_FAILED,
                )

            # ── Step 9: 连接到ticket批准IP（A3: 传入显式参数）──
            connect_ip = current_ticket.approved_ips[0]
            effective_max = max_response_bytes or _MAX_RESPONSE_BYTES
            try:
                raw_resp = await asyncio.wait_for(
                    self._transport.raw_fetch(
                        current_url, connect_ip,
                        connect_timeout=_CONNECT_TIMEOUT,
                        read_timeout=_READ_TIMEOUT,
                        max_response_bytes=effective_max,
                        user_agent=_USER_AGENT,
                        trust_env=False,
                    ),
                    timeout=_READ_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_READ_TIMEOUT,
                )
            except Exception:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_DNS_RESOLUTION_ERROR,
                )

            # ── Step 10: peer IP复核 ──
            peer_ip = raw_resp.get("peer_ip", "")
            peer_check = validate_peer_ip(current_ticket, peer_ip)
            if not peer_check["valid"]:
                return FetchResult(
                    status=0, content_type="", body="", peer_ip="",
                    redirect_location=None, bytes_read=0,
                    final_url_safe=_sanitize_url(current_url),
                    error_code=ERR_PEER_IP_MISMATCH,
                )

            status = raw_resp.get("status", 0)
            content_type = raw_resp.get("content_type", "")
            raw_body = raw_resp.get("body", b"")
            if isinstance(raw_body, str):
                raw_body = raw_body.encode("utf-8")
            redirect_location = raw_resp.get("redirect_location")
            content_length = raw_resp.get("content_length", len(raw_body))

            # ── Step 11: 处理重定向 ──
            if 300 <= status < 400 and redirect_location is not None:
                redirect_count += 1
                if redirect_count > _MAX_REDIRECTS:
                    return FetchResult(
                        status=status, content_type=content_type, body="",
                        peer_ip=peer_ip, redirect_location=redirect_location,
                        bytes_read=0,
                        final_url_safe=_sanitize_url(current_url),
                        error_code=ERR_REDIRECT_LIMIT,
                    )

                abs_redirect = urljoin(current_url, redirect_location)
                from_url = current_url
                to_url = abs_redirect

                redirect_check = self._validate_redirect(abs_redirect, approved_domains)
                if redirect_check is not None:
                    return FetchResult(
                        status=status, content_type=content_type, body="",
                        peer_ip=peer_ip, redirect_location=redirect_location,
                        bytes_read=0,
                        final_url_safe=_sanitize_url(current_url),
                        error_code=redirect_check,
                    )

                self._audit_log.append({
                    "action": "redirect",
                    "from": _sanitize_url(from_url),
                    "to": _sanitize_url(to_url),
                    "hop": redirect_count,
                })
                current_url = abs_redirect
                continue

            # ── Step 12: 响应限制检查（含V1.3有界gzip）──
            size_result = self._check_response_limits(
                status, content_type, raw_body, content_length,
                allowed_content_types=allowed_content_types,
                max_response_bytes=max_response_bytes,
            )
            # V1.3: size_result可以是：
            #   None = 通过（使用raw_body）
            #   (error_code, bytes_read, None) = 超限
            #   (None, 0, decompressed) = gzip解压通过（使用decompressed）
            final_body = raw_body
            if size_result is not None:
                error_code, bytes_read_val, decompressed = size_result
                if error_code is not None:
                    return FetchResult(
                        status=status, content_type=content_type, body="",
                        peer_ip=peer_ip, redirect_location=None,
                        bytes_read=bytes_read_val,
                        final_url_safe=_sanitize_url(current_url),
                        error_code=error_code,
                    )
                # gzip解压通过 → 使用解压后的body
                if decompressed is not None:
                    final_body = decompressed

            # ── Step 13: 解码body（B3: 解码在限制通过后）──
            try:
                body_str = final_body.decode("utf-8")
            except UnicodeDecodeError:
                body_str = final_body.decode("latin-1")

            # bytes_read登记网络读取的压缩字节数（gzip场景仍用raw_body长度）
            bytes_read = len(raw_body)
            self._audit_log.append({
                "action": "fetch_complete",
                "url_safe": _sanitize_url(current_url),
                "status": status,
                "bytes_read": bytes_read,
            })

            return FetchResult(
                status=status,
                content_type=content_type,
                body=body_str,
                peer_ip=peer_ip,
                redirect_location=None,
                bytes_read=bytes_read,
                final_url_safe=_sanitize_url(current_url),
                error_code=None if 200 <= status < 300 else f"http_{status}",
            )

    def _is_domain_approved(self, hostname: str, approved_domains: set[str]) -> bool:
        """检查hostname是否属于批准域名。"""
        for domain in approved_domains:
            if hostname == domain or hostname.endswith("." + domain):
                return True
        return False

    def _check_response_limits(
        self,
        status: int,
        content_type: str,
        raw_body: bytes,
        content_length: int | None,
        *,
        allowed_content_types: set[str] | None = None,
        max_response_bytes: int | None = None,
    ) -> tuple[str | None, int, bytes | None] | None:
        """检查响应限制。

        V1.3: content_length可以是None（无Content-Length）。
        V1.3: 使用_bounded_gzip_decompress替代无限制flush。

        Returns:
            None = 通过（使用raw_body）
            (error_code, bytes_read, None) = 超限
            (None, bytes_read, decompressed) = gzip解压通过，使用decompressed
        """
        effective_allowed = allowed_content_types or _ALLOWED_CONTENT_TYPES
        effective_max = max_response_bytes or _MAX_RESPONSE_BYTES

        # Content-Length超限 → 不读取正文
        if content_length is not None and content_length > effective_max:
            return (ERR_CONTENT_LENGTH_EXCEEDED, 0, None)

        # 流式读取超限检查（实际body字节数超限）
        if len(raw_body) > effective_max:
            return (ERR_STREAM_LIMIT_EXCEEDED, len(raw_body), None)

        # V1.3: gzip有界解压检查（使用_bounded_gzip_decompress）
        ct_lower = (content_type or "").lower()
        is_gzip = (
            ct_lower == "application/gzip"
            or (len(raw_body) >= 2 and raw_body[0] == 0x1F and raw_body[1] == 0x8B)
        )
        if is_gzip:
            decompressed, gzip_err = _bounded_gzip_decompress(
                raw_body, effective_max,
            )
            if gzip_err is not None:
                if gzip_err == ERR_GZIP_INVALID_STREAM:
                    # V1.4: 已判定is_gzip时，损坏流必须fail-closed
                    return (ERR_GZIP_INVALID_STREAM, len(raw_body), None)
                else:
                    # 解压超限/拼接成员 → 拒绝
                    return (gzip_err, len(raw_body), None)
            elif decompressed is not None:
                # 解压成功，后续HTML检查使用解压后的bytes
                # bytes_read仍登记网络读取的压缩字节数
                # 不把解压正文写入日志
                if len(decompressed) > effective_max:
                    return (ERR_GZIP_DECOMPRESS_LIMIT, len(raw_body), None)

                # 非HTML检查：使用解压后内容
                if not (300 <= status < 400):
                    is_html = any(t in ct_lower for t in effective_allowed)
                    # 如果content_type是application/gzip，检查解压后内容
                    if not is_html and ct_lower == "application/gzip":
                        try:
                            dec_str = decompressed[:512].decode("utf-8", errors="ignore").lower()
                            is_html = "<html" in dec_str or "<!doctype" in dec_str
                        except Exception:
                            pass
                    if not is_html and 200 <= status < 300:
                        return (ERR_NON_HTML_CONTENT, len(raw_body), None)

                # gzip解压通过，返回解压后的body供Step 13使用
                return (None, 0, decompressed)

        # 只接受HTML（非重定向、非gzip响应）
        if not (300 <= status < 400):
            ct_lower2 = (content_type or "").lower()
            is_html = any(t in ct_lower2 for t in effective_allowed)
            if not is_html and 200 <= status < 300:
                return (ERR_NON_HTML_CONTENT, len(raw_body), None)

        return None

    def _validate_redirect(self, redirect_url: str, approved_domains: set[str]) -> str | None:
        """验证重定向URL安全性。返回None=通过。"""
        try:
            parsed = urlparse(redirect_url)
        except Exception:
            return ERR_REDIRECT_INVALID

        if parsed.scheme not in ("http", "https"):
            return ERR_REDIRECT_NON_HTTP
        if parsed.username or parsed.password:
            return ERR_REDIRECT_USERINFO
        port = parsed.port
        if port is not None and port not in (80, 443):
            return ERR_REDIRECT_INVALID_PORT
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            return ERR_REDIRECT_MISSING
        if not self._is_domain_approved(hostname, approved_domains):
            return ERR_REDIRECT_DOMAIN_NOT_APPROVED
        return None


# ── URL脱敏：只保留scheme://hostname（V1.2: 不含port）──

def _sanitize_url(url: str) -> str:
    """脱敏URL：只保留scheme://hostname，不含port/path/query/fragment/userinfo。"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return f"{parsed.scheme}://{hostname}"
    except Exception:
        return "[invalid_url]"
