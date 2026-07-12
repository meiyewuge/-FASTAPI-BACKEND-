"""ResolutionTicket — DNS解析凭证数据类与验证逻辑。

实现一次性解析凭证，防止DNS rebinding攻击。
- hostname与URL严格一致
- scheme一致
- port一致
- 全部IP安全(任一危险IP则整票拒绝)
- 有效期最多5秒
- 一次性使用(使用后标记consumed)
- 不得跨请求复用
- 不得跨重定向复用
- nonce不可为空
- 过期、重复使用、host不一致立即拒绝
- ticket和日志不得包含完整URL query或凭据
"""
from __future__ import annotations

import ipaddress
import time
import uuid
from dataclasses import dataclass
from typing import Any


# ── 常量 ────────────────────────────────────────────────

_TICK_MAX_TTL_SECONDS = 5.0


# ── IP安全检查 ─────────────────────────────────────────

def is_safe_ip(ip_str: str) -> bool:
    """检查IP是否安全（全局单播，非私有/保留/loopback等）。

    覆盖: loopback, private, link-local, reserved, multicast, unspecified,
          TEST-NET, CGNAT(100.64.0.0/10), IPv4-mapped IPv6危险地址。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False

    # IPv4-mapped IPv6: ::ffff:a.b.c.d → 检查映射的IPv4
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return _is_global_unicast_v4(mapped)
        # 原生IPv6: 检查是否全局单播
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
        return ip.is_global

    return _is_global_unicast_v4(ip)


def _is_global_unicast_v4(ip: ipaddress.IPv4Address) -> bool:
    """IPv4全局单播检查，显式覆盖TEST-NET/CGNAT等。"""
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    # 兜底: 非全局一律拒绝
    if not ip.is_global:
        return False
    return True


# ── ResolutionTicket ───────────────────────────────────

@dataclass(frozen=True)
class ResolutionTicket:
    """DNS解析凭证 — 一次性使用，防止DNS rebinding。

    Attributes:
        scheme: http/https
        hostname: 请求hostname（严格一致）
        port: 请求端口（80/443）
        approved_ips: 批准的IP元组（全安全才签发）
        issued_at_monotonic: 签发时间(time.monotonic)
        expires_at_monotonic: 过期时间(time.monotonic)
        nonce: 唯一标识（防止重放）
    """
    scheme: str
    hostname: str
    port: int
    approved_ips: tuple[str, ...]
    issued_at_monotonic: float
    expires_at_monotonic: float
    nonce: str

    def __post_init__(self) -> None:
        """冻结dataclass的post_init：验证基本不变量。"""
        if not self.nonce:
            raise ValueError("ResolutionTicket nonce不可为空")
        if self.scheme not in ("http", "https"):
            raise ValueError(f"ResolutionTicket scheme必须为http/https, 得到: {self.scheme}")
        if self.port not in (80, 443):
            raise ValueError(f"ResolutionTicket port必须为80/443, 得到: {self.port}")
        if not self.hostname:
            raise ValueError("ResolutionTicket hostname不可为空")
        if not self.approved_ips:
            raise ValueError("ResolutionTicket approved_ips不可为空")
        if self.expires_at_monotonic <= self.issued_at_monotonic:
            raise ValueError("ResolutionTicket expires_at必须晚于issued_at")


class TicketConsumedError(Exception):
    """Ticket已被消费（一次性使用违反）。"""
    pass


class TicketExpiredError(Exception):
    """Ticket已过期。"""
    pass


class TicketMismatchError(Exception):
    """Ticket与请求不匹配。"""
    pass


class TicketValidationError(Exception):
    """Ticket验证失败通用异常。"""
    pass


# ── 签发 ───────────────────────────────────────────────

def issue_ticket(
    scheme: str,
    hostname: str,
    port: int,
    resolved_ips: list[str],
    ttl: float = _TICK_MAX_TTL_SECONDS,
) -> ResolutionTicket:
    """签发ResolutionTicket。

    Args:
        scheme: URL scheme
        hostname: URL hostname
        port: URL port
        resolved_ips: DNS解析结果
        ttl: 有效期（秒），最多5秒

    Returns:
        ResolutionTicket

    Raises:
        TicketValidationError: 如果任何IP不安全或参数无效
    """
    # 参数验证
    if scheme not in ("http", "https"):
        raise TicketValidationError(f"invalid_scheme: {scheme}")
    if not hostname:
        raise TicketValidationError("empty_hostname")
    if port not in (80, 443):
        raise TicketValidationError(f"invalid_port: {port}")
    if not resolved_ips:
        raise TicketValidationError("no_resolved_ips")

    # 全部IP必须安全 — 任一危险则整票拒绝
    for ip_str in resolved_ips:
        if not is_safe_ip(ip_str):
            raise TicketValidationError(f"unsafe_ip: {ip_str}")

    now = time.monotonic()
    effective_ttl = min(ttl, _TICK_MAX_TTL_SECONDS)

    return ResolutionTicket(
        scheme=scheme,
        hostname=hostname,
        port=port,
        approved_ips=tuple(resolved_ips),
        issued_at_monotonic=now,
        expires_at_monotonic=now + effective_ttl,
        nonce=uuid.uuid4().hex,
    )


# ── 验证与消费 ──────────────────────────────────────────

class TicketValidator:
    """Ticket验证器：负责验证+一次性消费标记。

    线程安全：每个TicketValidator实例独立管理consumed集合。
    """

    def __init__(self) -> None:
        self._consumed: set[str] = set()

    def validate_and_consume(
        self,
        ticket: ResolutionTicket,
        url: str,
    ) -> dict[str, Any]:
        """验证Ticket并标记为已消费。

        Args:
            ticket: 待验证的ResolutionTicket
            url: 实际请求URL

        Returns:
            dict with keys: valid, rejection_reason, trace

        Raises:
            无（所有失败通过返回值报告）
        """
        trace: dict[str, Any] = {}

        # 1. 一次性使用检查
        if ticket.nonce in self._consumed:
            trace["nonce"] = ticket.nonce[:8] + "..."
            return {"valid": False, "rejection_reason": "ticket_already_consumed", "trace": trace}

        # 2. 过期检查
        now = time.monotonic()
        if now >= ticket.expires_at_monotonic:
            trace["expired_by"] = now - ticket.expires_at_monotonic
            return {"valid": False, "rejection_reason": "ticket_expired", "trace": trace}

        # 3. URL hostname与ticket一致
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
        except Exception:
            return {"valid": False, "rejection_reason": "invalid_url", "trace": trace}

        url_hostname = (parsed.hostname or "").lower().rstrip(".")
        ticket_hostname = ticket.hostname.lower().rstrip(".")
        if url_hostname != ticket_hostname:
            trace["url_hostname"] = url_hostname
            trace["ticket_hostname"] = ticket_hostname
            return {"valid": False, "rejection_reason": "hostname_mismatch", "trace": trace}

        # 4. scheme一致
        if parsed.scheme != ticket.scheme:
            trace["url_scheme"] = parsed.scheme
            trace["ticket_scheme"] = ticket.scheme
            return {"valid": False, "rejection_reason": "scheme_mismatch", "trace": trace}

        # 5. port一致
        url_port = parsed.port
        if url_port is None:
            url_port = 443 if parsed.scheme == "https" else 80
        if url_port != ticket.port:
            trace["url_port"] = url_port
            trace["ticket_port"] = ticket.port
            return {"valid": False, "rejection_reason": "port_mismatch", "trace": trace}

        # 全部通过 → 标记消费
        self._consumed.add(ticket.nonce)

        return {"valid": True, "rejection_reason": "", "trace": trace}

    def is_consumed(self, nonce: str) -> bool:
        """检查nonce是否已被消费。"""
        return nonce in self._consumed


def validate_peer_ip(ticket: ResolutionTicket, peer_ip: str) -> dict[str, Any]:
    """验证实际连接的peer IP是否属于ticket批准集合。

    Returns:
        dict with keys: valid, rejection_reason
    """
    if peer_ip not in ticket.approved_ips:
        return {"valid": False, "rejection_reason": "peer_ip_not_approved"}
    return {"valid": True, "rejection_reason": ""}
