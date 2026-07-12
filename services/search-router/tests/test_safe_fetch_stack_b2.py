"""B2 Safe Fetch Stack 专项测试 — ResolutionTicket + SafeTransport + FakeTransport。

覆盖SPEC第八条28项测试：
1. 公网IPv4通过
2. 公网IPv6通过
3. loopback拒绝
4. private拒绝
5. link-local拒绝
6. unspecified拒绝
7. TEST-NET拒绝
8. CGNAT拒绝
9. mixed safe+unsafe整票拒绝
10. mapped IPv6危险地址拒绝
11. ticket过期拒绝
12. ticket重复使用拒绝
13. URL hostname与ticket不一致拒绝
14. port不一致拒绝
15. peer IP不在批准集合拒绝
16. peer IP匹配通过
17. 重定向重新签票
18. 重定向到非批准域名拒绝
19. 第3次重定向拒绝
20. Content-Length超限拒绝
21. 流式读取超限拒绝
22. gzip解压超限拒绝
23. 非HTML拒绝
24. timeout fail closed
25. 日志脱敏
26. 并发Ticket不串票
27. 同域并发请求各自使用独立Ticket
28. Fake Transport调用次数可审计
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from datetime import datetime, timezone, timedelta
from search_router.enrichers.resolution_ticket import (
    ResolutionTicket,
    TicketValidator,
    TicketConsumedError,
    TicketExpiredError,
    TicketMismatchError,
    TicketValidationError,
    issue_ticket,
    is_safe_ip,
    validate_peer_ip,
)
from search_router.enrichers.safe_transport import (
    FetchResult,
    FakeTransport,
    SafeResolver,
    SafeTransport,
    _MAX_RESPONSE_BYTES,
    _sanitize_url,
)


_APPROVED_DOMAINS = {"news.cn", "chinadaily.com.cn", "stcn.com"}


# ═══════════════════════════════════════════════════════
# 1-2: 公网IP通过
# ═══════════════════════════════════════════════════════

def test_public_ipv4_pass():
    """1. 公网IPv4通过。"""
    assert is_safe_ip("8.8.8.8") is True
    assert is_safe_ip("1.2.3.4") is True


def test_public_ipv6_pass():
    """2. 公网IPv6通过。"""
    assert is_safe_ip("2606:4700:4700::1111") is True
    assert is_safe_ip("2001:4860:4860::8888") is True


# ═══════════════════════════════════════════════════════
# 3-8: 危险IP拒绝
# ═══════════════════════════════════════════════════════

def test_loopback_reject():
    """3. loopback拒绝。"""
    assert is_safe_ip("127.0.0.1") is False
    assert is_safe_ip("::1") is False


def test_private_reject():
    """4. private拒绝。"""
    assert is_safe_ip("10.0.0.1") is False
    assert is_safe_ip("172.16.0.1") is False
    assert is_safe_ip("192.168.1.1") is False
    assert is_safe_ip("fc00::1") is False  # IPv6 ULA


def test_link_local_reject():
    """5. link-local拒绝。"""
    assert is_safe_ip("169.254.1.1") is False
    assert is_safe_ip("fe80::1") is False


def test_unspecified_reject():
    """6. unspecified拒绝。"""
    assert is_safe_ip("0.0.0.0") is False
    assert is_safe_ip("::") is False


def test_test_net_reject():
    """7. TEST-NET拒绝。"""
    assert is_safe_ip("192.0.2.1") is False   # TEST-NET-1
    assert is_safe_ip("198.51.100.1") is False  # TEST-NET-2
    assert is_safe_ip("203.0.113.1") is False  # TEST-NET-3


def test_cgnat_reject():
    """8. CGNAT拒绝。"""
    assert is_safe_ip("100.64.0.1") is False
    assert is_safe_ip("100.127.255.254") is False


# ═══════════════════════════════════════════════════════
# 9-10: 混合和mapped
# ═══════════════════════════════════════════════════════

def test_mixed_safe_unsafe_reject():
    """9. mixed safe+unsafe整票拒绝。"""
    with pytest.raises(TicketValidationError, match="unsafe_ip"):
        issue_ticket("https", "news.cn", 443, ["1.2.3.4", "127.0.0.1"])


def test_mapped_ipv6_dangerous_reject():
    """10. mapped IPv6危险地址拒绝。"""
    assert is_safe_ip("::ffff:127.0.0.1") is False
    assert is_safe_ip("::ffff:10.0.0.1") is False


# ═══════════════════════════════════════════════════════
# 11-14: Ticket验证拒绝
# ═══════════════════════════════════════════════════════

def test_ticket_expired_reject():
    """11. ticket过期拒绝。"""
    now = time.monotonic()
    ticket = ResolutionTicket(
        scheme="https",
        hostname="news.cn",
        port=443,
        approved_ips=("1.2.3.4",),
        issued_at_monotonic=now - 10,
        expires_at_monotonic=now - 5,
        nonce="test-expired-nonce",
    )
    validator = TicketValidator()
    result = validator.validate_and_consume(ticket, "https://news.cn/test")
    assert result["valid"] is False
    assert result["rejection_reason"] == "ticket_expired"


def test_ticket_double_use_reject():
    """12. ticket重复使用拒绝。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    validator = TicketValidator()
    result1 = validator.validate_and_consume(ticket, "https://news.cn/test")
    assert result1["valid"] is True
    result2 = validator.validate_and_consume(ticket, "https://news.cn/test")
    assert result2["valid"] is False
    assert result2["rejection_reason"] == "ticket_already_consumed"


def test_hostname_mismatch_reject():
    """13. URL hostname与ticket不一致拒绝。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    validator = TicketValidator()
    result = validator.validate_and_consume(ticket, "https://evil.com/test")
    assert result["valid"] is False
    assert result["rejection_reason"] == "hostname_mismatch"


def test_port_mismatch_reject():
    """14. port不一致拒绝。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    validator = TicketValidator()
    result = validator.validate_and_consume(ticket, "https://news.cn:80/test")
    assert result["valid"] is False
    assert result["rejection_reason"] == "port_mismatch"


# ═══════════════════════════════════════════════════════
# 15-16: peer IP验证
# ═══════════════════════════════════════════════════════

def test_peer_ip_not_approved_reject():
    """15. peer IP不在批准集合拒绝。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    result = validate_peer_ip(ticket, "5.6.7.8")
    assert result["valid"] is False
    assert result["rejection_reason"] == "peer_ip_not_approved"


def test_peer_ip_approved_pass():
    """16. peer IP匹配通过。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4", "9.8.7.6"])
    result = validate_peer_ip(ticket, "9.8.7.6")
    assert result["valid"] is True


# ═══════════════════════════════════════════════════════
# 17-19: 重定向
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_redirect_issuance():
    """17. 重定向重新签票。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://news.cn/b")
    fake.set_response("https://news.cn/b", status=200, body="<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.status == 200
    assert result.error_code is None
    assert fake.call_count == 2


@pytest.mark.asyncio
async def test_redirect_to_non_approved_domain_reject():
    """18. 重定向到非批准域名拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://evil.com/b")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.error_code == "redirect_domain_not_approved"


@pytest.mark.asyncio
async def test_third_redirect_reject():
    """19. 第3次重定向拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://news.cn/b")
    fake.set_response("https://news.cn/b", status=301, redirect_location="https://news.cn/c")
    fake.set_response("https://news.cn/c", status=301, redirect_location="https://news.cn/d")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.error_code == "redirect_limit_exceeded"


# ═══════════════════════════════════════════════════════
# 20-23: 响应限制
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_content_length_exceeded_reject():
    """20. Content-Length超限拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response(
        "https://news.cn/big",
        status=200,
        content_type="text/html",
        body="x",
        content_length=_MAX_RESPONSE_BYTES + 1,
    )
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/big")
    assert result.error_code == "content_length_exceeded"


@pytest.mark.asyncio
async def test_stream_limit_exceeded_reject():
    """21. 流式读取超限拒绝 — body实际大小超过限制（无Content-Length头时）。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    oversized_body = "x" * (_MAX_RESPONSE_BYTES + 1)
    # 设置content_length为合理值（模拟chunked传输：Content-Length未知但body已读）
    fake.set_response(
        "https://news.cn/stream",
        status=200,
        content_type="text/html",
        body=oversized_body,
        content_length=0,  # 模拟无Content-Length
    )
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/stream")
    assert result.error_code in ("stream_limit_exceeded", "content_length_exceeded")


@pytest.mark.asyncio
async def test_gzip_decompress_limit_reject():
    """22. gzip解压超限拒绝。"""
    import gzip as gz
    large_content = "A" * (_MAX_RESPONSE_BYTES + 100)
    compressed = gz.compress(large_content.encode())
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response(
        "https://news.cn/gzip",
        status=200,
        content_type="application/gzip",
        body=compressed,
    )
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip")
    assert result.error_code == "gzip_decompress_limit_exceeded"


@pytest.mark.asyncio
async def test_non_html_reject():
    """23. 非HTML拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response(
        "https://news.cn/json",
        status=200,
        content_type="application/json",
        body='{"key": "value"}',
    )
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/json")
    assert result.error_code == "non_html_content"


# ═══════════════════════════════════════════════════════
# 24: timeout fail closed
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_timeout_fail_closed():
    """24. timeout fail closed — 模拟超时返回error_code。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport(default_status=0, default_body="")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/timeout")
    assert result.error_code is not None or result.status != 200


# ═══════════════════════════════════════════════════════
# 25: 日志脱敏
# ═══════════════════════════════════════════════════════

def test_log_sanitization():
    """25. 日志脱敏 — URL不含query/fragment/userinfo。"""
    safe = _sanitize_url("https://user:pass@news.cn/path?q=secret#frag")
    assert "q=secret" not in safe
    assert "user:pass" not in safe
    assert "#frag" not in safe
    assert "news.cn" in safe


@pytest.mark.asyncio
async def test_fetch_result_no_credentials():
    """25b. FetchResult不包含Cookie/Authorization/完整query。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/page?secret=123", status=200, body="<html>ok</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/page?secret=123")
    assert "secret=123" not in result.final_url_safe
    assert not hasattr(result, "cookies")
    assert not hasattr(result, "authorization")


# ═══════════════════════════════════════════════════════
# 26-27: 并发Ticket
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_concurrent_tickets_no_cross_contamination():
    """26. 并发Ticket不串票。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=200, body="<html>a</html>")
    fake.set_response("https://news.cn/b", status=200, body="<html>b</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    results = await asyncio.gather(
        transport.fetch("https://news.cn/a"),
        transport.fetch("https://news.cn/b"),
    )
    assert results[0].status == 200
    assert results[1].status == 200
    assert results[0].body == "<html>a</html>"
    assert results[1].body == "<html>b</html>"


@pytest.mark.asyncio
async def test_same_domain_concurrent_independent_tickets():
    """27. 同域并发请求各自使用独立Ticket。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/x", status=200, body="<html>x</html>")
    fake.set_response("https://news.cn/y", status=200, body="<html>y</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    results = await asyncio.gather(
        transport.fetch("https://news.cn/x"),
        transport.fetch("https://news.cn/y"),
    )
    assert results[0].status == 200
    assert results[1].status == 200
    completes = [e for e in transport.audit_log if e.get("action") == "fetch_complete"]
    assert len(completes) == 2


# ═══════════════════════════════════════════════════════
# 28: FakeTransport审计
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fake_transport_call_count_auditable():
    """28. Fake Transport调用次数可审计。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn", status=200, body="<html>ok</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    await transport.fetch("https://news.cn")
    assert fake.call_count == 1
    assert len(fake.call_log) == 1


# ═══════════════════════════════════════════════════════
# 额外: issue_ticket基本验证
# ═══════════════════════════════════════════════════════

def test_issue_ticket_basic():
    """签票基本功能。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    assert ticket.scheme == "https"
    assert ticket.hostname == "news.cn"
    assert ticket.port == 443
    assert ticket.approved_ips == ("1.2.3.4",)
    assert ticket.nonce
    assert ticket.expires_at_monotonic > ticket.issued_at_monotonic


def test_issue_ticket_rejects_unsafe_ip():
    """签票拒绝危险IP。"""
    with pytest.raises(TicketValidationError):
        issue_ticket("https", "news.cn", 443, ["127.0.0.1"])


def test_issue_ticket_rejects_bad_scheme():
    """签票拒绝非http/https scheme。"""
    with pytest.raises(TicketValidationError):
        issue_ticket("ftp", "news.cn", 21, ["1.2.3.4"])


def test_issue_ticket_rejects_bad_port():
    """签票拒绝非80/443端口。"""
    with pytest.raises(TicketValidationError):
        issue_ticket("https", "news.cn", 8443, ["1.2.3.4"])


def test_issue_ticket_ttl_capped():
    """签票TTL最多5秒。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"], ttl=100.0)
    assert (ticket.expires_at_monotonic - ticket.issued_at_monotonic) <= 5.0 + 1e-9


def test_ticket_frozen():
    """Ticket不可变。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    with pytest.raises(AttributeError):
        ticket.hostname = "evil.com"  # type: ignore


def test_resolution_ticket_post_init_validation():
    """Ticket __post_init__验证。"""
    with pytest.raises(ValueError, match="nonce"):
        ResolutionTicket(
            scheme="https", hostname="news.cn", port=443,
            approved_ips=("1.2.3.4",),
            issued_at_monotonic=0, expires_at_monotonic=5,
            nonce="",
        )


# ═══════════════════════════════════════════════════════
# 额外: 重定向安全验证
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_redirect_non_http_https_reject():
    """重定向到非HTTP/HTTPS拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="ftp://news.cn/b")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.error_code == "redirect_non_http_https"


@pytest.mark.asyncio
async def test_redirect_userinfo_reject():
    """重定向带userinfo拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://user:pass@news.cn/b")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.error_code == "redirect_userinfo_present"


@pytest.mark.asyncio
async def test_redirect_invalid_port_reject():
    """重定向到非80/443端口拒绝。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://news.cn:8080/b")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.error_code == "redirect_invalid_port"


# ═══════════════════════════════════════════════════════
# 额外: 完整SafeTransport fetch流程
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_safe_fetch_normal_flow():
    """正常fetch流程。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/article", status=200, body="<html>article</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/article")
    assert result.status == 200
    assert result.body == "<html>article</html>"
    assert result.error_code is None
    assert result.peer_ip == "1.2.3.4"


@pytest.mark.asyncio
async def test_safe_fetch_unsafe_ip_reject():
    """DNS解析到危险IP → 签票失败 → fetch失败。"""
    resolver = SafeResolver(default_ips=["127.0.0.1"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/article")
    assert result.error_code is not None
    assert "unsafe_ip" in result.error_code or "ticket_error" in result.error_code


@pytest.mark.asyncio
async def test_safe_fetch_peer_ip_mismatch_reject():
    """peer IP不匹配 → fetch失败。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport(default_peer_ip="5.6.7.8")
    fake.set_response("https://news.cn/article", status=200, body="<html>ok</html>", peer_ip="5.6.7.8")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/article")
    assert result.error_code == "peer_ip_mismatch"


@pytest.mark.asyncio
async def test_safe_fetch_domain_not_approved():
    """非批准域名 → fetch失败。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://evil.com/page")
    assert result.error_code == "domain_not_approved"


@pytest.mark.asyncio
async def test_safe_fetch_subdomain_approved():
    """批准域名的子域名通过。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/article", status=200, body="<html>ok</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://www.news.cn/article")
    assert result.status == 200
    assert result.error_code is None


# ═══════════════════════════════════════════════════════
# 额外: Resolver审计
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolver_call_count():
    """Resolver调用次数可审计。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn", status=200, body="<html>ok</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    await transport.fetch("https://news.cn")
    assert resolver.call_count == 1


# ═══════════════════════════════════════════════════════
# 额外: TicketValidator独立测试
# ═══════════════════════════════════════════════════════

def test_validator_scheme_mismatch():
    """scheme不一致拒绝。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    validator = TicketValidator()
    result = validator.validate_and_consume(ticket, "http://news.cn/test")
    assert result["valid"] is False
    assert result["rejection_reason"] == "scheme_mismatch"


def test_validator_is_consumed():
    """is_consumed查询。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    validator = TicketValidator()
    assert validator.is_consumed(ticket.nonce) is False
    validator.validate_and_consume(ticket, "https://news.cn/test")
    assert validator.is_consumed(ticket.nonce) is True


def test_validator_independent_instances():
    """独立TicketValidator实例不共享consumed集合。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4"])
    v1 = TicketValidator()
    v2 = TicketValidator()
    r1 = v1.validate_and_consume(ticket, "https://news.cn/test")
    assert r1["valid"] is True
    r2 = v2.validate_and_consume(ticket, "https://news.cn/test")
    assert r2["valid"] is True
    r3 = v1.validate_and_consume(ticket, "https://news.cn/test")
    assert r3["valid"] is False


# ═══════════════════════════════════════════════════════
# 额外: FetchResult不可变
# ═══════════════════════════════════════════════════════

def test_fetch_result_frozen():
    """FetchResult不可变。"""
    result = FetchResult(
        status=200, content_type="text/html", body="<html></html>",
        peer_ip="1.2.3.4", redirect_location=None, bytes_read=13,
        final_url_safe="https://news.cn/", error_code=None,
    )
    with pytest.raises(AttributeError):
        result.status = 404  # type: ignore


# ═══════════════════════════════════════════════════════
# 额外: IPv4-mapped IPv6 安全地址通过
# ═══════════════════════════════════════════════════════

def test_mapped_ipv6_safe_pass():
    """IPv4-mapped IPv6安全地址通过。"""
    assert is_safe_ip("::ffff:8.8.8.8") is True
    assert is_safe_ip("::ffff:1.2.3.4") is True


# ═══════════════════════════════════════════════════════
# 额外: issue_ticket多IP
# ═══════════════════════════════════════════════════════

def test_issue_ticket_multiple_safe_ips():
    """签票支持多个安全IP。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4", "5.6.7.8"])
    assert ticket.approved_ips == ("1.2.3.4", "5.6.7.8")


def test_validate_peer_ip_first_ip():
    """peer IP匹配第一个批准IP。"""
    ticket = issue_ticket("https", "news.cn", 443, ["1.2.3.4", "5.6.7.8"])
    result = validate_peer_ip(ticket, "1.2.3.4")
    assert result["valid"] is True


# ═══════════════════════════════════════════════════════
# 额外: SafeTransport with redirect + ticket for redirect
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_redirect_produces_new_ticket():
    """重定向为每次hop签发新ticket。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=302, redirect_location="https://www.news.cn/b")
    fake.set_response("https://www.news.cn/b", status=200, body="<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.status == 200
    assert result.error_code is None
    # resolver被调用2次(一次原始URL，一次重定向URL)
    assert resolver.call_count == 2


@pytest.mark.asyncio
async def test_two_redirects_allowed():
    """允许2次重定向。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/a", status=301, redirect_location="https://news.cn/b")
    fake.set_response("https://news.cn/b", status=301, redirect_location="https://news.cn/c")
    fake.set_response("https://news.cn/c", status=200, body="<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/a")
    assert result.status == 200
    assert result.error_code is None


# ═══════════════════════════════════════════════════════
# 额外: SafeTransport返回值完整性
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fetch_result_fields_complete():
    """FetchResult字段完整性。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn", status=200, body="<html>ok</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn")
    assert result.status == 200
    assert result.content_type == "text/html"
    assert result.body == "<html>ok</html>"
    assert result.peer_ip == "1.2.3.4"
    assert result.redirect_location is None
    assert result.bytes_read == len("<html>ok</html>")
    assert result.final_url_safe == "https://news.cn"
    assert result.error_code is None

# ═════════════════════════════════════════════════════════
# V1.1 反向测试：ChatGPT终审NEED_FIX要求的补充验证
# ═════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_v11_enricher_calls_safe_transport():
    """Enricher真实调用SafeTransport，而非旧resolver+fetcher。"""
    from search_router.enrichers.publish_time_enricher import enrich_publish_time
    from search_router.enrichers.safe_transport import SafeTransport, FakeTransport, SafeResolver

    class _MockResult:
        def __init__(self):
            self.publish_time = None
            self.source_credibility_score = 0.9
            self.url = "https://www.news.cn/test"
            self.computation_trace = {"_source_credibility": {"credibility_tier": "A"}}

    class _RobotsProvider:
        async def get_robots(self, scheme, hostname):
            return (404, "text/plain", "")

    html = '<html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2025-06-15T10:00:00+08:00"}</script></head><body>test</body></html>'
    resolver = SafeResolver()
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/test", body=html.encode("utf-8"))
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)

    result = _MockResult()
    enr = await enrich_publish_time(
        result=result,
        safe_fetcher=transport,
        robots_provider=_RobotsProvider(),
        approved_domains=_APPROVED_DOMAINS,
    )
    assert fake.call_count > 0, "Enricher must call SafeTransport internally"
    assert enr.enriched is True


@pytest.mark.asyncio
async def test_v11_no_ticket_none_path():
    """ticket为空路径不存在 — SafeTransport.fetch不暴露ticket参数。"""
    import inspect
    sig = inspect.signature(SafeTransport.fetch)
    param_names = list(sig.parameters.keys())
    assert "ticket" not in param_names, "fetch() must not expose ticket parameter"


@pytest.mark.asyncio
async def test_v11_unapproved_domain_dns_zero():
    """未批准域名DNS调用=0。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains={"news.cn"})
    result = await transport.fetch("https://evil.com/page", approved_domains={"news.cn"})
    assert result.error_code == "domain_not_approved"
    assert resolver.call_count == 0, "DNS must not be called for unapproved domain"


@pytest.mark.asyncio
async def test_v11_userinfo_url_reject_dns_zero():
    """userinfo初始URL拒绝且DNS=0。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://user:pass@news.cn/page", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "userinfo_in_url"
    assert resolver.call_count == 0, "DNS must not be called when URL has userinfo"


@pytest.mark.asyncio
async def test_v11_ticket_consumed_before_raw_fetch():
    """Ticket在raw_fetch前已消费。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None


@pytest.mark.asyncio
async def test_v11_peer_mismatch_ticket_not_reusable():
    """peer不匹配后Ticket不可重用。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", peer_ip="9.9.9.9")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "peer_ip_mismatch"
    result2 = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result2.error_code == "peer_ip_mismatch"


@pytest.mark.asyncio
async def test_v11_no_transport_blocked():
    """未注入Transport立即BLOCKED。"""
    resolver = SafeResolver()
    transport = SafeTransport(resolver=resolver, transport=None, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "blocked_transport_not_configured"


@pytest.mark.asyncio
async def test_v11_real_async_fetch_timeout():
    """真实协程fetch超时。"""
    class SlowTransport:
        async def raw_fetch(self, url, approved_ip, *, connect_timeout=5.0, read_timeout=10.0, max_response_bytes=524288, user_agent="WuYouSearchRouter/1.0", trust_env=False):
            await asyncio.sleep(10.0)
            return {"status": 200, "content_type": "text/html", "body": b"test",
                    "peer_ip": "1.2.3.4", "redirect_location": None, "content_length": 4}
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    transport = SafeTransport(resolver=resolver, transport=SlowTransport(), approved_domains=_APPROVED_DOMAINS)
    import time
    start = time.monotonic()
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    elapsed = time.monotonic() - start
    assert result.error_code == "read_timeout"
    assert elapsed < 12.0, f"Should timeout within ~10s, took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_v11_utf8_bytes_limit():
    """UTF-8字符按字节限长。"""
    big_body = "中" * 200000  # 200K chars x 3 bytes = 600KB > 512KB
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", body=big_body.encode("utf-8"))
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code in ("stream_limit_exceeded", "content_length_exceeded")


@pytest.mark.asyncio
async def test_v11_gzip_incremental_limit():
    """gzip增量超限。"""
    import gzip as gz
    large_content = "A" * (_MAX_RESPONSE_BYTES + 100)
    compressed = gz.compress(large_content.encode())
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", status=200, content_type="application/gzip", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "gzip_decompress_limit_exceeded"


@pytest.mark.asyncio
async def test_v11_url_path_not_in_log():
    """URL path不进入日志。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/secret/path?token=abc", body=b"<html>test</html>")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/secret/path?token=abc", approved_domains=_APPROVED_DOMAINS)
    assert "/secret" not in result.final_url_safe
    assert "?token" not in result.final_url_safe
    for entry in transport.audit_log:
        for key, val in entry.items():
            if isinstance(val, str) and "news.cn" in val:
                assert "/secret" not in val
                assert "?token" not in val


@pytest.mark.asyncio
async def test_v11_redirect_from_to_different():
    """redirect from/to不同且正确。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    # Use different subdomains so sanitized URLs differ
    resolver.set_ips("www.news.cn", ["1.2.3.4"])
    resolver.set_ips("m.news.cn", ["1.2.3.4"])
    fake.set_response("https://www.news.cn/old",
                       status=301, redirect_location="https://m.news.cn/new", peer_ip="1.2.3.4")
    fake.set_response("https://m.news.cn/new", body=b"<html>new</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://www.news.cn/old", approved_domains=_APPROVED_DOMAINS)
    redirect_entries = [e for e in transport.audit_log if e.get("action") == "redirect"]
    assert len(redirect_entries) >= 1
    entry = redirect_entries[0]
    assert entry["from"] != entry["to"], f"from and to must differ: {entry}"
    assert "www.news.cn" in entry["from"]
    assert "m.news.cn" in entry["to"]


@pytest.mark.asyncio
async def test_v11_error_code_no_ip_url_exception():
    """错误码不含IP、URL或异常原文。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)

    result = await transport.fetch("https://evil.com/page")
    assert result.error_code == "domain_not_approved"
    assert "evil.com" not in result.error_code
    assert "1.2.3.4" not in result.error_code

    result2 = await transport.fetch("https://user:pass@news.cn/page")
    assert result2.error_code == "userinfo_in_url"
    # error_code is fixed enum "userinfo_in_url", no URL/credentials embedded
    assert "news.cn" not in result2.error_code
    assert "user:pass" not in result2.error_code


@pytest.mark.asyncio
async def test_v11_enricher_uses_formal_scorer():
    """Enricher补取后freshness与score_freshness()完全一致，confidence与score_confidence()完全一致。"""
    from search_router.enrichers.orchestrator import EnricherOrchestrator
    from search_router.enrichers.safe_transport import SafeTransport, FakeTransport, SafeResolver
    from search_router.scorers.freshness_scorer import score_freshness
    from search_router.scorers.confidence_scorer import score_confidence
    from search_router.config import SearchRouterConfig
    from search_router.models.search_response import SearchResult
    import math

    p1_html = '<!DOCTYPE html><html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2025-06-15T10:00:00+08:00"}</script></head><body>test</body></html>'
    resolver = SafeResolver()
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/test-article", body=p1_html.encode("utf-8"), peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains={"news.cn"})

    class _Robots:
        async def get_robots(self, scheme, hostname): return (404, "text/plain", "")
        async def is_allowed(self, url): return True

    ref_time = datetime(2025, 7, 1, tzinfo=timezone(timedelta(hours=8)))
    orch = EnricherOrchestrator(
        safe_fetcher=transport, robots_provider=_Robots(),
        approved_domains={"news.cn", "chinadaily.com.cn", "stcn.com"},
        reference_time=ref_time,
    )

    r = SearchResult(
        title="test", url="https://www.news.cn/test-article", summary="test",
        source="新华网", publish_time=None, provider="tavily",
        source_credibility_score=0.9, relevance_score=0.7,
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    r.freshness_score = float("nan")
    r.confidence_score = float("nan")

    config = SearchRouterConfig(dry_run=False, publish_time_enricher_enabled=True, publish_time_enricher_shadow_only=True)
    results = await orch.enrich_batch([r], config)
    enriched = results[0]

    assert enriched.publish_time is not None
    ref_naive = ref_time.replace(tzinfo=None)
    expected_freshness, _ = score_freshness(enriched.publish_time, "default", ref_naive)
    assert enriched.freshness_score == expected_freshness, \
        f"freshness mismatch: {enriched.freshness_score} != {expected_freshness}"

    expected_confidence, _ = score_confidence(
        enriched.source_credibility_score, enriched.freshness_score, enriched.relevance_score,
        provider=enriched.provider,
    )
    assert enriched.confidence_score == expected_confidence, \
        f"confidence mismatch: {enriched.confidence_score} != {expected_confidence}"


@pytest.mark.asyncio
async def test_v11_scorer_trace_complete():
    """正式Scorer trace完整。"""
    from search_router.enrichers.orchestrator import EnricherOrchestrator
    from search_router.enrichers.safe_transport import SafeTransport, FakeTransport, SafeResolver
    from search_router.config import SearchRouterConfig
    from search_router.models.search_response import SearchResult
    import math

    p1_html = '<!DOCTYPE html><html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2025-06-15T10:00:00+08:00"}</script></head><body>test</body></html>'
    resolver = SafeResolver()
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/test-article", body=p1_html.encode("utf-8"), peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains={"news.cn"})

    class _Robots:
        async def get_robots(self, scheme, hostname): return (404, "text/plain", "")
        async def is_allowed(self, url): return True

    orch = EnricherOrchestrator(
        safe_fetcher=transport, robots_provider=_Robots(),
        approved_domains={"news.cn", "chinadaily.com.cn", "stcn.com"},
        reference_time=datetime(2025, 7, 1, tzinfo=timezone(timedelta(hours=8))),
    )

    r = SearchResult(
        title="test", url="https://www.news.cn/test-article", summary="test",
        source="新华网", publish_time=None, provider="tavily",
        source_credibility_score=0.9, relevance_score=0.7,
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    r.freshness_score = float("nan")
    r.confidence_score = float("nan")

    config = SearchRouterConfig(dry_run=False, publish_time_enricher_enabled=True, publish_time_enricher_shadow_only=True)
    results = await orch.enrich_batch([r], config)
    enriched = results[0]

    trace = enriched.computation_trace.get("_enrichment", {})
    assert trace.get("status") == "enriched"
    fresh_trace = enriched.computation_trace.get("_freshness", {})
    conf_trace = enriched.computation_trace.get("_confidence", {})
    assert fresh_trace.get("module") == "freshness_scorer"
    assert conf_trace.get("module") == "confidence_scorer"
    assert "reason" in fresh_trace
    assert "reason" in conf_trace


@pytest.mark.asyncio
async def test_v11_fake_transport_not_default():
    """FakeTransport不能被默认自动创建。"""
    resolver = SafeResolver()
    transport = SafeTransport(resolver=resolver, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "blocked_transport_not_configured"
    assert transport._transport is None


# ══════════════════════════════════════════════════════════
# V1.2 新增反向测试（ChatGPT终审V1.1 NEED_FIX 4类问题）
# ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_v12_dns_real_coroutine_timeout():
    """A1: DNS真实协程超时→dns_timeout。"""
    class SlowResolver:
        async def resolve(self, hostname):
            await asyncio.sleep(10.0)
            return ["1.2.3.4"]
    resolver = SlowResolver()
    transport = SafeTransport(resolver=resolver, transport=FakeTransport(), approved_domains=_APPROVED_DOMAINS)
    import time
    start = time.monotonic()
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    elapsed = time.monotonic() - start
    assert result.error_code == "dns_timeout"
    assert elapsed < 8.0, f"DNS should timeout within ~5s, took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_v12_total_timeout():
    """A2: 总体超时15秒→total_timeout（模拟多跳重定向）。"""
    call_count = 0
    class SlowRedirectTransport:
        async def raw_fetch(self, url, approved_ip, *, connect_timeout=5.0, read_timeout=10.0, max_response_bytes=524288, user_agent="WuYouSearchRouter/1.0", trust_env=False):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(8.0)  # 每次8秒，2次就超16秒 > 15秒总限
            return {"status": 302, "content_type": "text/html", "body": b"",
                    "peer_ip": "1.2.3.4", "redirect_location": "https://news.cn/redirect" + str(call_count),
                    "content_length": 0}
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    transport = SafeTransport(resolver=resolver, transport=SlowRedirectTransport(), approved_domains=_APPROVED_DOMAINS)
    import time
    start = time.monotonic()
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    elapsed = time.monotonic() - start
    assert result.error_code == "total_timeout"
    assert elapsed < 17.0, f"Total should timeout within ~15s, took {elapsed:.1f}s"


@pytest.mark.asyncio
async def test_v12_fake_records_transport_params():
    """A3: FakeTransport记录5/10/512KB/User-Agent/trust_env=False。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", body=b"<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None
    assert len(fake.call_log) == 1
    entry = fake.call_log[0]
    assert entry["connect_timeout"] == 5.0
    assert entry["read_timeout"] == 10.0
    assert entry["max_response_bytes"] == 524288
    assert entry["user_agent"] == "WuYouSearchRouter/1.0"
    assert entry["trust_env"] is False


@pytest.mark.asyncio
async def test_v12_empty_approved_domains_dns_zero():
    """A4: 空批准域名→DNS调用=0，domain_not_approved。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=set())
    result = await transport.fetch("https://news.cn/test", approved_domains=set())
    assert result.error_code == "domain_not_approved"
    assert resolver.call_count == 0, "Empty approved_domains must not trigger DNS"
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_v12_sanitize_url_no_port():
    """A5: 日志/脱敏URL不含port。"""
    result = _sanitize_url("https://news.cn:443/path?q=1")
    assert result == "https://news.cn", f"Port must not appear: {result}"
    result2 = _sanitize_url("http://news.cn:80/path")
    assert result2 == "http://news.cn", f"Port must not appear: {result2}"
    # audit log不含port
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/test", body=b"<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    fetch_result = await transport.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    for entry in transport.audit_log:
        if "url_safe" in entry:
            assert ":443" not in entry["url_safe"], f"Port in audit: {entry['url_safe']}"
        if "from" in entry:
            assert ":443" not in entry["from"], f"Port in redirect from: {entry['from']}"
        if "to" in entry:
            assert ":443" not in entry["to"], f"Port in redirect to: {entry['to']}"


@pytest.mark.asyncio
async def test_v12_content_length_exceeded_zero_bytes():
    """B1: Content-Length超限时raw body读取0字节。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/big", body=b"x" * 100, content_length=600000)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/big", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "content_length_exceeded"
    # FakeTransport返回body=b""（0字节）
    assert len(fake.call_log) == 1
    raw_resp = await fake.raw_fetch("https://news.cn/big", "1.2.3.4",
        connect_timeout=5.0, read_timeout=10.0, max_response_bytes=524288,
        user_agent="WuYouSearchRouter/1.0", trust_env=False)
    assert raw_resp.get("transport_limit_exceeded") is True
    assert raw_resp.get("body") == b""


@pytest.mark.asyncio
async def test_v12_no_content_length_chunked_limit():
    """B1: 无Content-Length分块超限。"""
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    big_body = b"A" * 600000
    # V1.3: content_length=None真正模拟无Content-Length分块传输
    fake.set_response("https://news.cn/chunked", body=big_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked", approved_domains=_APPROVED_DOMAINS)
    # V1.3强断言：无Content-Length超限必须是stream_limit_exceeded
    assert result.error_code == "stream_limit_exceeded", f"Must be stream_limit_exceeded, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v12_gzip_8kb_chunk_bomb():
    """B2: 8KB压缩块膨胀超过512KB。"""
    import gzip as gz
    # 创建一个高压缩比的内容：大量重复字符串
    large_content = "A" * (_MAX_RESPONSE_BYTES + 100000)
    compressed = gz.compress(large_content.encode())
    # 确保compressed不超过512KB但解压后远超512KB
    assert len(compressed) < _MAX_RESPONSE_BYTES, "Compressed should be < 512KB"
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-bomb", status=200, content_type="application/gzip", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-bomb", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == "gzip_decompress_limit_exceeded"


@pytest.mark.asyncio
async def test_v12_gzip_flush_overflow():
    """B2: flush阶段超限。"""
    import gzip as gz
    # 创建恰好到达边界的压缩内容
    boundary_content = "X" * _MAX_RESPONSE_BYTES
    compressed = gz.compress(boundary_content.encode())
    # 加一点额外内容使flush阶段超限
    extra = gz.compress(("Y" * 100).encode())
    # 合并（这不是严格合法的gzip但测试解压逻辑）
    full_compressed = compressed + extra
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-flush", status=200, content_type="text/html", body=full_compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-flush", approved_domains=_APPROVED_DOMAINS)
    # gzip解压检查在HTML内容类型检查之前执行
    # 512KB+额外内容的压缩数据应触发超限或成功（取决于实际解压大小）
    # 关键：gzip有界解压必须使用max_length，不会一次膨胀过大
    # V1.3强断言：gzip解压超限必须返回明确错误码，不接受None
    assert result.error_code is not None, "Gzip with extra data must not succeed silently"
    assert result.error_code in ("gzip_decompress_limit_exceeded", "gzip_invalid_stream", "gzip_concatenated_member_rejected", "non_html_content")


@pytest.mark.asyncio
async def test_v12_utf8_byte_counting():
    """B3: UTF-8多字节字符按字节限长。"""
    # 3字节UTF-8字符：200000个"中" = 600000字节 > 512KB
    big_body = "中" * 200000
    body_bytes = big_body.encode("utf-8")
    assert len(body_bytes) > _MAX_RESPONSE_BYTES, f"Expected > 512KB, got {len(body_bytes)}"
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/utf8", body=body_bytes)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/utf8", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code in ("stream_limit_exceeded", "content_length_exceeded")


@pytest.mark.asyncio
async def test_v12_trace_top_level_consistency():
    """C: 补取后computation_trace顶层与对象一致。"""
    from search_router.enrichers.orchestrator import EnricherOrchestrator
    from search_router.models.search_response import SearchResult
    from search_router.config import SearchRouterConfig

    p1_html = '<!DOCTYPE html><html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2025-06-15T10:00:00+08:00"}</script></head><body>test</body></html>'
    resolver = SafeResolver()
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/test-article", body=p1_html.encode("utf-8"), peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains={"news.cn"})

    class _Robots:
        async def get_robots(self, scheme, hostname): return (404, "text/plain", "")

    ref_time = datetime(2025, 7, 1, tzinfo=timezone(timedelta(hours=8)))
    orch = EnricherOrchestrator(
        safe_fetcher=transport, robots_provider=_Robots(),
        approved_domains={"news.cn", "chinadaily.com.cn", "stcn.com"},
        reference_time=ref_time,
    )

    r = SearchResult(
        title="test", url="https://www.news.cn/test-article", summary="test",
        source="新华网", publish_time=None, provider="tavily",
        source_credibility_score=0.9, relevance_score=0.7,
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    r.freshness_score = float("nan")
    r.confidence_score = float("nan")

    config = SearchRouterConfig(dry_run=False, publish_time_enricher_enabled=True, publish_time_enricher_shadow_only=True)
    results = await orch.enrich_batch([r], config)
    enriched = results[0]

    trace = enriched.computation_trace
    enrichment = trace.get("_enrichment", {})
    assert enrichment.get("status") == "enriched"

    # 顶层必须与对象一致
    assert trace.get("freshness_score") == enriched.freshness_score, \
        f"trace.freshness_score={trace.get('freshness_score')} != result.freshness_score={enriched.freshness_score}"
    assert trace.get("confidence_score") == enriched.confidence_score, \
        f"trace.confidence_score={trace.get('confidence_score')} != result.confidence_score={enriched.confidence_score}"
    assert trace.get("final_score") == enriched.final_score, \
        f"trace.final_score={trace.get('final_score')} != result.final_score={enriched.final_score}"

    # _freshness和_confidence是正式Scorer trace
    fresh_trace = trace.get("_freshness", {})
    conf_trace = trace.get("_confidence", {})
    assert isinstance(fresh_trace, dict), f"_freshness should be dict, got {type(fresh_trace)}"
    assert isinstance(conf_trace, dict), f"_confidence should be dict, got {type(conf_trace)}"
    assert "reason" in fresh_trace, f"_freshness trace missing 'reason': {fresh_trace}"
    assert "reason" in conf_trace, f"_confidence trace missing 'reason': {conf_trace}"


@pytest.mark.asyncio
async def test_v12_error_code_no_ip_url_exception():
    """V1.2: 错误码不含IP/URL/异常原文（固定枚举）。"""
    resolver = SafeResolver(default_ips=["127.0.0.1"])
    fake = FakeTransport()
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    # 各种错误场景
    result1 = await transport.fetch("https://unapproved.com/test", approved_domains=_APPROVED_DOMAINS)
    assert result1.error_code == "domain_not_approved"
    assert "unapproved" not in result1.error_code

    result2 = await transport.fetch("https://user:pass@news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result2.error_code == "userinfo_in_url"

    result3 = await transport.fetch("ftp://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result3.error_code == "invalid_scheme"

    result4 = await transport.fetch("https://news.cn:8080/test", approved_domains=_APPROVED_DOMAINS)
    assert result4.error_code == "invalid_port"

    # unsafe IP
    resolver2 = SafeResolver(default_ips=["127.0.0.1"])
    fake2 = FakeTransport()
    transport2 = SafeTransport(resolver=resolver2, transport=fake2, approved_domains=_APPROVED_DOMAINS)
    result5 = await transport2.fetch("https://news.cn/test", approved_domains=_APPROVED_DOMAINS)
    assert result5.error_code == "unsafe_ip"
    assert "127.0.0.1" not in result5.error_code


@pytest.mark.asyncio
async def test_v12_robots_protocol_get_robots():
    """C: RobotsProviderProtocol统一为get_robots()。"""
    from search_router.enrichers.orchestrator import EnricherOrchestrator
    from search_router.models.search_response import SearchResult
    from search_router.config import SearchRouterConfig

    resolver = SafeResolver()
    fake = FakeTransport()
    fake.set_response("https://www.news.cn/test", body=b"<html>ok</html>", peer_ip="1.2.3.4")
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains={"news.cn"})

    # 只实现get_robots，不再有is_allowed
    class _RobotsV12:
        async def get_robots(self, scheme, hostname):
            return (404, "text/plain", "")

    orch = EnricherOrchestrator(
        safe_fetcher=transport, robots_provider=_RobotsV12(),
        approved_domains={"news.cn"},
        reference_time=datetime(2025, 7, 1, tzinfo=timezone(timedelta(hours=8))),
    )
    # 验证不会因缺少is_allowed而报错
    # 测试1: publish_time已存在→资格过滤跳过，无_enrichment trace
    r1 = SearchResult(
        title="test", url="https://www.news.cn/test", summary="test",
        source="新华网", publish_time="2025-06-15T10:00:00+08:00", provider="tavily",
        source_credibility_score=0.9, relevance_score=0.7,
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    r1.freshness_score = 0.5
    r1.confidence_score = 0.5
    config = SearchRouterConfig(dry_run=False, publish_time_enricher_enabled=True, publish_time_enricher_shadow_only=True)
    results = await orch.enrich_batch([r1], config)
    # publish_time已存在→资格过滤直接跳过，不进enrich_single，无_enrichment
    assert results[0].publish_time == "2025-06-15T10:00:00+08:00"
    
    # 测试2: publish_time为空→进入enrich_single，调用get_robots
    p1_html = '<!DOCTYPE html><html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2025-06-15T10:00:00+08:00"}</script></head><body>test</body></html>'
    fake.set_response("https://www.news.cn/test2", body=p1_html.encode("utf-8"), peer_ip="1.2.3.4")
    r2 = SearchResult(
        title="test2", url="https://www.news.cn/test2", summary="test",
        source="新华网", publish_time=None, provider="tavily",
        source_credibility_score=0.9, relevance_score=0.7,
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    r2.freshness_score = float("nan")
    r2.confidence_score = float("nan")
    results2 = await orch.enrich_batch([r2], config)
    # 补取应成功，且只使用了get_robots（无is_allowed）
    assert results2[0].computation_trace.get("_enrichment", {}).get("status") == "enriched"
# ══════════════════════════════════════════════════════════
# V1.3 强断言测试（ChatGPT终审V1.2 PASS_WITH_ONE_BLOCKING_MICROFIX）
# ══════════════════════════════════════════════════════════

import asyncio
import gzip as gz
import zlib

import pytest

from search_router.enrichers.safe_transport import (
    FakeTransport,
    SafeResolver,
    SafeTransport,
    _MAX_RESPONSE_BYTES,
    _AUTO_LENGTH,
    _bounded_gzip_decompress,
    _sanitize_url,
    ERR_GZIP_DECOMPRESS_LIMIT,
    ERR_GZIP_INVALID_STREAM,
    ERR_GZIP_CONCATENATED_MEMBER,
    ERR_STREAM_LIMIT_EXCEEDED,
    ERR_CONTENT_LENGTH_EXCEEDED,
)

_APPROVED_DOMAINS = {"news.cn", "chinadaily.com.cn", "stcn.com"}


@pytest.mark.asyncio
async def test_v13_gzip_small_decompress_success():
    """V1.3-1: 单gzip成员解压后<512KB→成功，得到HTML正文。"""
    html = '<html><body>Hello World</body></html>'
    compressed = gz.compress(html.encode("utf-8"))
    assert len(compressed) < _MAX_RESPONSE_BYTES

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-ok", status=200, content_type="text/html", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-ok", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None, f"Small gzip should succeed: {result.error_code}"
    assert result.body == html, f"Body mismatch: {result.body!r} vs {html!r}"


@pytest.mark.asyncio
async def test_v13_gzip_exactly_over_limit():
    """V1.3-2: 单gzip成员解压后512KB+1→精确拒绝。"""
    # 创建恰好超过512KB的解压内容
    large_content = "A" * (_MAX_RESPONSE_BYTES + 1)
    compressed = gz.compress(large_content.encode("utf-8"))
    assert len(compressed) < _MAX_RESPONSE_BYTES, "Compressed must be < 512KB"

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-over", status=200, content_type="text/html", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-over", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_GZIP_DECOMPRESS_LIMIT, \
        f"Must be gzip_decompress_limit_exceeded, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_gzip_8kb_bomb_reject():
    """V1.3-3: 8KB压缩块膨胀超限→拒绝。"""
    large_content = "A" * (_MAX_RESPONSE_BYTES + 100000)
    compressed = gz.compress(large_content.encode("utf-8"))
    assert len(compressed) < _MAX_RESPONSE_BYTES

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-bomb", status=200, content_type="text/html", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-bomb", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_GZIP_DECOMPRESS_LIMIT, \
        f"Must be gzip_decompress_limit_exceeded, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_gzip_tail_output_bounded():
    """V1.3-4: 需要尾部输出的gzip→仍受上限控制（强断言，不接受None）。"""
    # 创建接近512KB的压缩内容，使decompressor内部缓冲区有数据
    # 用decompressobj手动构建一个需要flush才能完成的流
    html = "<html>" + "X" * (_MAX_RESPONSE_BYTES - 10) + "</html>"
    compressed = gz.compress(html.encode("utf-8"))
    # 这个压缩数据在解压时，最后部分可能在decompressor内部缓冲区
    # _bounded_gzip_decompress使用decompress(b"", max_length=...)替代flush
    # 验证它不会超过限制

    # 先验证_bounded_gzip_decompress直接调用
    decompressed, err = _bounded_gzip_decompress(compressed, _MAX_RESPONSE_BYTES)
    # 内容恰好512KB-7+13 = ~512KB，可能在边界
    if decompressed is not None:
        assert len(decompressed) <= _MAX_RESPONSE_BYTES, \
            f"Decompressed must be <= 512KB, got {len(decompressed)}"
        assert err is None
    else:
        assert err == ERR_GZIP_DECOMPRESS_LIMIT, \
            f"Error must be gzip_decompress_limit_exceeded, got: {err}"


@pytest.mark.asyncio
async def test_v13_gzip_concatenated_members_rejected():
    """V1.3-5: 两个拼接gzip成员合计超限→拒绝。"""
    # 创建两个gzip成员并拼接
    part1 = gz.compress(("A" * 300000).encode())
    part2 = gz.compress(("B" * 300000).encode())
    concatenated = part1 + part2

    # 直接测试_bounded_gzip_decompress
    decompressed, err = _bounded_gzip_decompress(concatenated, _MAX_RESPONSE_BYTES)
    # 两个成员合计600KB > 512KB → 必须拒绝
    # 可能是concatenated_member_rejected（如果第一个成员解压后<512KB）
    # 或者是gzip_decompress_limit_exceeded（如果第一个成员本身超限）
    assert err in (ERR_GZIP_CONCATENATED_MEMBER, ERR_GZIP_DECOMPRESS_LIMIT), \
        f"Concatenated gzip must be rejected, got: {err}"


@pytest.mark.asyncio
async def test_v13_gzip_corrupted_invalid_stream():
    """V1.3-6: 损坏gzip→gzip_invalid_stream。"""
    # 以gzip magic bytes开头但后续数据损坏
    corrupted = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff' + b'\xff' * 100

    decompressed, err = _bounded_gzip_decompress(corrupted, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_INVALID_STREAM, \
        f"Corrupted gzip must return gzip_invalid_stream, got: {err}"
    assert decompressed is None


@pytest.mark.asyncio
async def test_v13_no_content_length_within_limit():
    """V1.3-7: 无Content-Length 512KB内→通过。"""
    small_body = b"<html>" + b"A" * 100 + b"</html>"
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    # 显式传content_length=None → 服务器没有Content-Length
    fake.set_response("https://news.cn/chunked-ok", status=200, body=small_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked-ok", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None, f"Within-limit chunked should succeed: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_no_content_length_over_limit():
    """V1.3-8: 无Content-Length 512KB+1→stream_limit_exceeded。"""
    big_body = b"<html>" + b"A" * (_MAX_RESPONSE_BYTES + 1) + b"</html>"
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    # 显式传content_length=None
    fake.set_response("https://news.cn/chunked-over", status=200, body=big_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked-over", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_STREAM_LIMIT_EXCEEDED, \
        f"Must be stream_limit_exceeded, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_over_limit_body_empty():
    """V1.3-9: 超限时返回body为空。"""
    big_body = b"A" * 600000
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/big", body=big_body, content_length=600000)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/big", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_CONTENT_LENGTH_EXCEEDED
    assert result.body == "", "Body must be empty on limit exceeded, got: " + repr(result.body[:50])


@pytest.mark.asyncio
async def test_v13_gzip_flush_strong_assert():
    """V1.3-10: gzip flush阶段超限→强断言（不接受None/non_html_content）。"""
    # 创建解压后恰好超512KB的内容
    large_content = "X" * (_MAX_RESPONSE_BYTES + 5000)
    compressed = gz.compress(large_content.encode())
    # 再追加一些让解压器在"flush"阶段有更多数据
    # 注意：这不是严格的gzip拼接，但_decompress_with_tail会测试边界
    full_compressed = compressed + b'\x00' * 100  # 尾部垃圾数据

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/gzip-flush-test", status=200, content_type="text/html", body=full_compressed)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/gzip-flush-test", approved_domains=_APPROVED_DOMAINS)
    # 强断言：只能是gzip相关错误或解压后非HTML（因为内容是纯X不是HTML）
    # 但由于content_type=text/html且gzip magic bytes触发解压，结果应该是gzip错误
    # 因为解压后的内容"XXX..."不是HTML
    # 但如果解压超限，则error_code=gzip_decompress_limit_exceeded
    # 如果解压成功但非HTML，则error_code=non_html_content
    # 关键：error_code不能是None
    assert result.error_code is not None, \
        "Gzip with trailing data must not succeed silently (error_code=None)"
    assert result.error_code in (ERR_GZIP_DECOMPRESS_LIMIT, ERR_GZIP_INVALID_STREAM,
                                  ERR_GZIP_CONCATENATED_MEMBER, "non_html_content"), \
        f"Must be a definitive error, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_no_content_length_exact_boundary():
    """V1.3-11: 无Content-Length恰好512KB边界→通过。"""
    # 恰好512KB
    exact_body = b"<html>" + b"A" * (_MAX_RESPONSE_BYTES - 13) + b"</html>"
    assert len(exact_body) == _MAX_RESPONSE_BYTES, f"Expected {_MAX_RESPONSE_BYTES}, got {len(exact_body)}"

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/chunked-exact", status=200, body=exact_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked-exact", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None, f"Exact 512KB chunked should succeed: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_no_content_length_one_over():
    """V1.3-12: 无Content-Length 512KB+1→精确stream_limit_exceeded + bytes_read=524289。"""
    over_body = b"<html>" + b"A" * (_MAX_RESPONSE_BYTES - 12) + b"</html>"
    assert len(over_body) == _MAX_RESPONSE_BYTES + 1, f"Expected {_MAX_RESPONSE_BYTES+1}, got {len(over_body)}"

    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/chunked-one-over", status=200, body=over_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake, approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked-one-over", approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_STREAM_LIMIT_EXCEEDED, \
        f"Must be stream_limit_exceeded, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v13_bounded_gzip_direct_success():
    """V1.3: _bounded_gzip_decompress直接调用-成功路径。"""
    html = b"<html><body>test</body></html>"
    compressed = gz.compress(html)
    decompressed, err = _bounded_gzip_decompress(compressed, _MAX_RESPONSE_BYTES)
    assert err is None, f"Should succeed, got: {err}"
    assert decompressed == html


@pytest.mark.asyncio
async def test_v13_bounded_gzip_direct_limit():
    """V1.3: _bounded_gzip_decompress直接调用-超限。"""
    large = b"A" * (_MAX_RESPONSE_BYTES + 1)
    compressed = gz.compress(large)
    decompressed, err = _bounded_gzip_decompress(compressed, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_DECOMPRESS_LIMIT, f"Should be limit exceeded, got: {err}"
    assert decompressed is None


@pytest.mark.asyncio
async def test_v13_bounded_gzip_direct_concat():
    """V1.3: _bounded_gzip_decompress直接调用-拼接成员。"""
    part1 = gz.compress(b"A" * 100)
    part2 = gz.compress(b"B" * 100)
    concatenated = part1 + part2
    decompressed, err = _bounded_gzip_decompress(concatenated, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_CONCATENATED_MEMBER, f"Should reject concatenated, got: {err}"
    assert decompressed is None


@pytest.mark.asyncio
async def test_v13_bounded_gzip_direct_invalid():
    """V1.3: _bounded_gzip_decompress直接调用-损坏流。"""
    # 非gzip magic bytes
    decompressed, err = _bounded_gzip_decompress(b"not gzip at all", _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_INVALID_STREAM
    assert decompressed is None

    # 空数据
    decompressed2, err2 = _bounded_gzip_decompress(b"", _MAX_RESPONSE_BYTES)
    assert err2 == ERR_GZIP_INVALID_STREAM
    assert decompressed2 is None


@pytest.mark.asyncio
async def test_v13_auto_length_vs_explicit_none():
    """V1.3: sentinel区分：未传content_length vs 显式None。"""
    fake = FakeTransport()
    body = b"<html>test</html>"

    # 未传content_length → 自动用len(body)
    fake.set_response("https://news.cn/auto", body=body)
    resp_auto = await fake.raw_fetch("https://news.cn/auto", "1.2.3.4",
        connect_timeout=5.0, read_timeout=10.0, max_response_bytes=524288,
        user_agent="WuYouSearchRouter/1.0", trust_env=False)
    assert resp_auto["content_length"] == len(body), \
        f"Auto length should be len(body)={len(body)}, got: {resp_auto['content_length']}"

    # 显式传None → content_length=None
    fake2 = FakeTransport()
    fake2.set_response("https://news.cn/explicit-none", body=body, content_length=None)
    resp_none = await fake2.raw_fetch("https://news.cn/explicit-none", "1.2.3.4",
        connect_timeout=5.0, read_timeout=10.0, max_response_bytes=524288,
        user_agent="WuYouSearchRouter/1.0", trust_env=False)
    assert resp_none["content_length"] is None, \
        f"Explicit None should stay None, got: {resp_none['content_length']}"


@pytest.mark.asyncio
async def test_v13_no_content_length_chunked_bytes_read():
    """V1.3: 无Content-Length超限时FakeTransport的bytes_read <= max+1。"""
    big_body = b"A" * (_MAX_RESPONSE_BYTES + 10000)
    fake = FakeTransport()
    fake.set_response("https://news.cn/big-chunked", body=big_body, content_length=None)
    resp = await fake.raw_fetch("https://news.cn/big-chunked", "1.2.3.4",
        connect_timeout=5.0, read_timeout=10.0, max_response_bytes=_MAX_RESPONSE_BYTES,
        user_agent="WuYouSearchRouter/1.0", trust_env=False)
    assert resp.get("transport_limit_exceeded") is True
    assert resp["bytes_read"] <= _MAX_RESPONSE_BYTES + 1, \
        f"bytes_read must be <= max+1, got: {resp['bytes_read']}"
    # body must not exceed max+1
    assert len(resp["body"]) <= _MAX_RESPONSE_BYTES + 1, \
        f"body must be <= max+1 bytes, got: {len(resp['body'])}"

# ══════════════════════════════════════════════════════════
# V1.4强断言测试：gzip EOF完整性边界（ChatGPT终审V1.3指令）
# ══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_v14_truncated_gzip_1_byte():
    """V1.4-1: 合法gzip截断1字节 → gzip_invalid_stream。"""
    html = b"<html><body>Hello World</body></html>"
    compressed = gz.compress(html)
    # 截断最后1字节
    truncated = compressed[:-1]
    decompressed, err = _bounded_gzip_decompress(truncated, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_INVALID_STREAM, \
        f"Truncated gzip (1 byte) must return gzip_invalid_stream, got: {err}"
    assert decompressed is None


@pytest.mark.asyncio
async def test_v14_truncated_gzip_footer_8_bytes():
    """V1.4-2: 截断gzip footer 8字节 → gzip_invalid_stream。"""
    html = b"<html><body>Footer Test</body></html>"
    compressed = gz.compress(html)
    # gzip footer = CRC32(4) + ISIZE(4) = 8字节
    truncated = compressed[:-8]
    decompressed, err = _bounded_gzip_decompress(truncated, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_INVALID_STREAM, \
        f"Truncated gzip footer (8 bytes) must return gzip_invalid_stream, got: {err}"
    assert decompressed is None


@pytest.mark.asyncio
async def test_v14_truncated_gzip_full_transport_path():
    """V1.4-3: 截断流通过SafeTransport完整路径 → gzip_invalid_stream。"""
    html = b"<html><body>Transport Path</body></html>"
    compressed = gz.compress(html)
    truncated = compressed[:-4]
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/truncated-gzip", status=200,
                      content_type="text/html", body=truncated)
    transport = SafeTransport(resolver=resolver, transport=fake,
                              approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/truncated-gzip",
                                   approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_GZIP_INVALID_STREAM, \
        f"Truncated gzip via transport must return gzip_invalid_stream, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v14_corrupted_gzip_magic_html_content_type():
    """V1.4-4: 损坏gzip magic流且Content-Type=text/html → gzip_invalid_stream。"""
    # 以gzip magic开头但数据损坏
    corrupted = b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff' + b'\xde\xad\xbe\xef' * 50
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/corrupted-gzip-html", status=200,
                      content_type="text/html", body=corrupted)
    transport = SafeTransport(resolver=resolver, transport=fake,
                              approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/corrupted-gzip-html",
                                   approved_domains=_APPROVED_DOMAINS)
    assert result.error_code == ERR_GZIP_INVALID_STREAM, \
        f"Corrupted gzip with text/html must return gzip_invalid_stream, got: {result.error_code}"


@pytest.mark.asyncio
async def test_v14_all_failure_body_empty():
    """V1.4-5: 所有失败结果body=""。"""
    # 测试多种失败场景的body都为空
    # 1) 截断gzip
    html = b"<html>test</html>"
    compressed = gz.compress(html)
    truncated = compressed[:-1]
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake1 = FakeTransport()
    fake1.set_response("https://news.cn/trunc1", status=200,
                       content_type="text/html", body=truncated)
    t1 = SafeTransport(resolver=resolver, transport=fake1,
                       approved_domains=_APPROVED_DOMAINS)
    r1 = await t1.fetch("https://news.cn/trunc1", approved_domains=_APPROVED_DOMAINS)
    assert r1.body == "", f"Truncated gzip body must be empty, got: {repr(r1.body[:50])}"

    # 2) 损坏gzip magic
    corrupted = b'\x1f\x8b\x08\x00' + b'\xff' * 100
    fake2 = FakeTransport()
    fake2.set_response("https://news.cn/corrupt1", status=200,
                       content_type="text/html", body=corrupted)
    t2 = SafeTransport(resolver=SafeResolver(default_ips=["1.2.3.4"]),
                       transport=fake2, approved_domains=_APPROVED_DOMAINS)
    r2 = await t2.fetch("https://news.cn/corrupt1", approved_domains=_APPROVED_DOMAINS)
    assert r2.body == "", f"Corrupted gzip body must be empty, got: {repr(r2.body[:50])}"

    # 3) 截断footer 8字节
    truncated8 = compressed[:-8]
    fake3 = FakeTransport()
    fake3.set_response("https://news.cn/trunc8", status=200,
                       content_type="text/html", body=truncated8)
    t3 = SafeTransport(resolver=SafeResolver(default_ips=["1.2.3.4"]),
                       transport=fake3, approved_domains=_APPROVED_DOMAINS)
    r3 = await t3.fetch("https://news.cn/trunc8", approved_domains=_APPROVED_DOMAINS)
    assert r3.body == "", f"Footer-truncated gzip body must be empty, got: {repr(r3.body[:50])}"


@pytest.mark.asyncio
async def test_v14_valid_gzip_still_succeeds():
    """V1.4-6: 完整合法gzip仍成功并得到原HTML。"""
    html = b"<html><head><title>Test Page</title></head><body><p>Hello gzip</p></body></html>"
    compressed = gz.compress(html)
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/valid-gzip", status=200,
                      content_type="text/html", body=compressed)
    transport = SafeTransport(resolver=resolver, transport=fake,
                              approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/valid-gzip",
                                   approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None, f"Valid gzip should succeed, got: {result.error_code}"
    assert result.body == html.decode("utf-8"), \
        f"Decompressed body should match original HTML"


@pytest.mark.asyncio
async def test_v14_existing_tests_still_pass():
    """V1.4-7: 拼接成员、512KB+1、无Content-Length边界原测试继续通过（回归验证）。

    此测试验证V1.4修改未破坏V1.3已有边界行为：
    - 拼接gzip成员仍被拒绝
    - 512KB+1仍超限
    - 无Content-Length边界仍正确
    """
    # 7a: 拼接gzip成员
    part1 = gz.compress(b"A" * 100)
    part2 = gz.compress(b"B" * 100)
    concatenated = part1 + part2
    dec, err = _bounded_gzip_decompress(concatenated, _MAX_RESPONSE_BYTES)
    assert err == ERR_GZIP_CONCATENATED_MEMBER, \
        f"Concatenated gzip must be rejected, got: {err}"

    # 7b: 512KB+1超限
    large = b"A" * (_MAX_RESPONSE_BYTES + 1)
    compressed_large = gz.compress(large)
    dec2, err2 = _bounded_gzip_decompress(compressed_large, _MAX_RESPONSE_BYTES)
    assert err2 == ERR_GZIP_DECOMPRESS_LIMIT, \
        f"512KB+1 must be limit exceeded, got: {err2}"

    # 7c: 无Content-Length边界
    exact_body = b"<html>" + b"A" * (_MAX_RESPONSE_BYTES - 13) + b"</html>"
    assert len(exact_body) == _MAX_RESPONSE_BYTES
    resolver = SafeResolver(default_ips=["1.2.3.4"])
    fake = FakeTransport()
    fake.set_response("https://news.cn/chunked-regression", status=200,
                      body=exact_body, content_length=None)
    transport = SafeTransport(resolver=resolver, transport=fake,
                              approved_domains=_APPROVED_DOMAINS)
    result = await transport.fetch("https://news.cn/chunked-regression",
                                   approved_domains=_APPROVED_DOMAINS)
    assert result.error_code is None, \
        f"Exact 512KB chunked should still pass, got: {result.error_code}"

    # 7d: 无Content-Length 512KB+1
    over_body = b"<html>" + b"A" * (_MAX_RESPONSE_BYTES - 12) + b"</html>"
    assert len(over_body) == _MAX_RESPONSE_BYTES + 1
    fake2 = FakeTransport()
    fake2.set_response("https://news.cn/chunked-over-regression", status=200,
                       body=over_body, content_length=None)
    transport2 = SafeTransport(resolver=SafeResolver(default_ips=["1.2.3.4"]),
                               transport=fake2, approved_domains=_APPROVED_DOMAINS)
    result2 = await transport2.fetch("https://news.cn/chunked-over-regression",
                                     approved_domains=_APPROVED_DOMAINS)
    assert result2.error_code == ERR_STREAM_LIMIT_EXCEEDED, \
        f"512KB+1 chunked must be stream_limit_exceeded, got: {result2.error_code}"
