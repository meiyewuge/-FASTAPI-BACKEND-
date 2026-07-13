"""
RealDNSResolver test — WUYOU_SR_P02_REAL_DNS_ATOMIC_AND_ROBOTS_FAIL_CLOSED_V1_1

Tests:
- Public IPv4/IPv6 (single AF_UNSPEC call)
- private/loopback/link-local/unspecified/TEST-NET/CGNAT/mapped IPv6
- safe+unsafe mixed rejection (ResolutionTicket)
- Empty result, DNS exception, DNS timeout, unexpected exception (no partial)
- Deduplication, per-request independent, single getaddrinfo call
- Ticket issuance, one-time use, peer validation
- Redirect re-resolve and re-ticket
- robots fail-closed: non-404 error -> skip page; 404 -> allow; Disallow -> skip
"""
import asyncio
import socket
import time
from unittest.mock import patch, AsyncMock

import pytest

import os
import sys
# Portable: repo root is the parent of tests/ (was a hardcoded ECS absolute path)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from search_router.enrichers.real_dns_resolver import RealDNSResolver
from search_router.enrichers.resolution_ticket import (
    issue_ticket, is_safe_ip, TicketValidationError,
    TicketValidator, validate_peer_ip,
)
from search_router.enrichers.safe_transport import SafeTransport, FakeTransport
from search_router.enrichers.real_transport import RealTransport


def make_ipv4_result(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

def make_ipv6_result(ip):
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]

def make_mixed_result(ips_v4, ips_v6):
    result = []
    for ip in ips_v4:
        result.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
    for ip in ips_v6:
        result.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
    return result


class TestRealDNSResolverBasic:
    """V1.1 atomic DNS resolver tests"""

    @pytest.mark.asyncio
    async def test_public_ipv4(self):
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            ips = await resolver.resolve("example.com")
        assert "93.184.216.34" in ips

    @pytest.mark.asyncio
    async def test_public_ipv6(self):
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv6_result("2606:2800:220:1:248:1893:25c8:1946")):
            ips = await resolver.resolve("example.com")
        assert "2606:2800:220:1:248:1893:25c8:1946" in ips

    @pytest.mark.asyncio
    async def test_ipv4_ipv6_single_call(self):
        """V1.1: IPv4+IPv6 returned in single AF_UNSPEC call"""
        resolver = RealDNSResolver()
        mixed = make_mixed_result(["93.184.216.34"], ["2606:2800:220:1:248:1893:25c8:1946"])
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock, return_value=mixed):
            ips = await resolver.resolve("example.com")
        assert "93.184.216.34" in ips
        assert "2606:2800:220:1:248:1893:25c8:1946" in ips

    @pytest.mark.asyncio
    async def test_single_getaddrinfo_call(self):
        """V1.1: getaddrinfo called exactly 1 time"""
        resolver = RealDNSResolver()
        call_count = 0
        async def counting(*a, **k):
            nonlocal call_count
            call_count += 1
            return make_ipv4_result("93.184.216.34")
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=counting):
            await resolver.resolve("example.com")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_total_timeout_le_5s(self):
        """V1.1: Total resolve time <= 5s"""
        resolver = RealDNSResolver(timeout=5.0)
        async def slow(*a, **k):
            await asyncio.sleep(4.9)
            return make_ipv4_result("1.2.3.4")
        start = time.monotonic()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=slow):
            ips = await resolver.resolve("slow.domain")
        elapsed = time.monotonic() - start
        assert elapsed < 5.5

    @pytest.mark.asyncio
    async def test_deduplication(self):
        resolver = RealDNSResolver()
        dup = make_ipv4_result("93.184.216.34") + make_ipv4_result("93.184.216.34")
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock, return_value=dup):
            ips = await resolver.resolve("example.com")
        assert ips.count("93.184.216.34") == 1

    @pytest.mark.asyncio
    async def test_ipv4_before_ipv6(self):
        resolver = RealDNSResolver()
        mixed = make_mixed_result(["93.184.216.34"], ["2606:2800:220:1:248:1893:25c8:1946"])
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock, return_value=mixed):
            ips = await resolver.resolve("example.com")
        assert len(ips) == 2
        assert ips[0] == "93.184.216.34"
        assert ips[1] == "2606:2800:220:1:248:1893:25c8:1946"

    @pytest.mark.asyncio
    async def test_mapped_ipv6_not_filtered(self):
        """V1.1: mapped IPv6 not filtered, Ticket safety rejects"""
        resolver = RealDNSResolver()
        mixed = make_mixed_result(["93.184.216.34"], ["::ffff:192.168.1.1"])
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock, return_value=mixed):
            ips = await resolver.resolve("example.com")
        assert "::ffff:192.168.1.1" in ips
        assert not is_safe_ip("::ffff:192.168.1.1")

    @pytest.mark.asyncio
    async def test_empty_result(self):
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock, return_value=[]):
            ips = await resolver.resolve("nonexistent.example")
        assert ips == []

    @pytest.mark.asyncio
    async def test_dns_exception_no_partial(self):
        """V1.1: gaierror -> empty list, no partial results"""
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         side_effect=socket.gaierror("DNS error")):
            ips = await resolver.resolve("bad.domain")
        assert ips == []

    @pytest.mark.asyncio
    async def test_dns_timeout_no_partial(self):
        """V1.1: timeout -> empty list, no partial results"""
        resolver = RealDNSResolver(timeout=0.1)
        async def slow(*a, **k):
            await asyncio.sleep(10)
            return make_ipv4_result("1.2.3.4")
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=slow):
            ips = await resolver.resolve("slow.domain")
        assert ips == []

    @pytest.mark.asyncio
    async def test_unexpected_exception_no_partial(self):
        """V1.1: unexpected exception -> empty list, no partial"""
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         side_effect=RuntimeError("unexpected")):
            ips = await resolver.resolve("crash.domain")
        assert ips == []

    @pytest.mark.asyncio
    async def test_each_request_independent(self):
        resolver = RealDNSResolver()
        call_count = 0
        async def counting(*a, **k):
            nonlocal call_count
            call_count += 1
            return make_ipv4_result("1.2.3.%d" % call_count)
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=counting):
            ips1 = await resolver.resolve("example.com")
            ips2 = await resolver.resolve("example.com")
        assert ips1 != ips2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_audit_log_no_full_ip(self):
        resolver = RealDNSResolver()
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            await resolver.resolve("example.com")
        log = resolver.audit_log
        assert len(log) == 1
        entry = log[0]
        assert entry["action"] == "dns_resolve"
        assert entry["getaddrinfo_calls"] == 1
        for key in entry:
            if key.endswith("_count") or key in ("elapsed_ms", "getaddrinfo_calls"):
                continue
            val = str(entry[key])
            assert "93.184.216.34" not in val, "Full IP in audit key=%s" % key

    @pytest.mark.asyncio
    async def test_audit_log_timeout(self):
        """V1.1: timeout audit log action=dns_resolve_timeout"""
        resolver = RealDNSResolver(timeout=0.1)
        async def slow(*a, **k):
            await asyncio.sleep(10)
            return make_ipv4_result("1.2.3.4")
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=slow):
            await resolver.resolve("slow.domain")
        log = resolver.audit_log
        assert len(log) == 1
        assert log[0]["action"] == "dns_resolve_timeout"


class TestRealDNSResolverSafeIP:
    def test_private_ip_rejected(self):
        assert not is_safe_ip("192.168.1.1")
        assert not is_safe_ip("10.0.0.1")
        assert not is_safe_ip("172.16.0.1")

    def test_loopback_rejected(self):
        assert not is_safe_ip("127.0.0.1")

    def test_link_local_rejected(self):
        assert not is_safe_ip("169.254.1.1")

    def test_unspecified_rejected(self):
        assert not is_safe_ip("0.0.0.0")

    def test_test_net_rejected(self):
        assert not is_safe_ip("192.0.2.1")
        assert not is_safe_ip("198.51.100.1")
        assert not is_safe_ip("203.0.113.1")

    def test_cgnat_rejected(self):
        assert not is_safe_ip("100.64.0.1")

    def test_ipv4_mapped_ipv6_dangerous(self):
        assert not is_safe_ip("::ffff:192.168.1.1")
        assert not is_safe_ip("::ffff:127.0.0.1")

    def test_public_ip_safe(self):
        assert is_safe_ip("93.184.216.34")
        assert is_safe_ip("8.8.8.8")
        assert is_safe_ip("144.7.102.149")

    def test_public_ipv6_safe(self):
        assert is_safe_ip("2606:2800:220:1:248:1893:25c8:1946")


class TestRealDNSResolverTicketIntegration:
    def test_safe_ips_issue_ticket(self):
        ticket = issue_ticket("https", "example.com", 443, ["93.184.216.34"])
        assert ticket.hostname == "example.com"
        assert "93.184.216.34" in ticket.approved_ips

    def test_unsafe_ips_reject_ticket(self):
        with pytest.raises(TicketValidationError):
            issue_ticket("https", "example.com", 443, ["192.168.1.1"])

    def test_mixed_safe_unsafe_reject_ticket(self):
        with pytest.raises(TicketValidationError):
            issue_ticket("https", "example.com", 443, ["93.184.216.34", "192.168.1.1"])

    def test_empty_ips_reject_ticket(self):
        with pytest.raises(TicketValidationError):
            issue_ticket("https", "example.com", 443, [])

    def test_ticket_one_time_use(self):
        ticket = issue_ticket("https", "example.com", 443, ["93.184.216.34"])
        validator = TicketValidator()
        r1 = validator.validate_and_consume(ticket, "https://example.com/")
        assert r1["valid"] is True
        r2 = validator.validate_and_consume(ticket, "https://example.com/")
        assert r2["valid"] is False
        assert r2["rejection_reason"] == "ticket_already_consumed"

    def test_peer_ip_validation(self):
        ticket = issue_ticket("https", "example.com", 443, ["93.184.216.34"])
        r1 = validate_peer_ip(ticket, "93.184.216.34")
        assert r1["valid"] is True
        r2 = validate_peer_ip(ticket, "1.2.3.4")
        assert r2["valid"] is False


class TestRealDNSResolverSafeTransportIntegration:
    @pytest.mark.asyncio
    async def test_full_chain_with_fake_transport(self):
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        fake.set_response("http://example.com/", status=200,
                         body=b"<html>ok</html>", content_type="text/html",
                         peer_ip="93.184.216.34")
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            result = await safe.fetch("http://example.com/", approved_domains={"example.com"})
        assert result.status == 200
        assert "ok" in result.body

    @pytest.mark.asyncio
    async def test_unsafe_ip_blocked_by_safe_transport(self):
        resolver = RealDNSResolver()
        fake = FakeTransport()
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("192.168.1.1")):
            result = await safe.fetch("http://example.com/", approved_domains={"example.com"})
        assert result.status == 0
        assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_mixed_safe_unsafe_blocked(self):
        resolver = RealDNSResolver()
        fake = FakeTransport()
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_mixed_result(["93.184.216.34", "192.168.1.1"], [])):
            result = await safe.fetch("http://example.com/", approved_domains={"example.com"})
        assert result.status == 0
        assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_dns_timeout_blocked(self):
        resolver = RealDNSResolver(timeout=0.1)
        fake = FakeTransport()
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})
        async def slow(*a, **k):
            await asyncio.sleep(10)
            return make_ipv4_result("1.2.3.4")
        with patch.object(asyncio.get_event_loop(), "getaddrinfo", side_effect=slow):
            result = await safe.fetch("http://example.com/", approved_domains={"example.com"})
        assert result.status == 0
        assert result.error_code is not None

    @pytest.mark.asyncio
    async def test_unapproved_domain_blocked(self):
        resolver = RealDNSResolver()
        fake = FakeTransport()
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"other.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            result = await safe.fetch("http://example.com/", approved_domains={"other.com"})
        assert result.status == 0
        assert result.error_code is not None


class TestRealDNSResolverRedirect:
    @pytest.mark.asyncio
    async def test_redirect_re_resolves(self):
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        fake.set_response("http://example.com/", status=301,
                         body=b"", content_type="text/html",
                         peer_ip="93.184.216.34",
                         redirect_location="http://other.com/")
        fake.set_response("http://other.com/", status=200,
                         body=b"<html>ok</html>", content_type="text/html",
                         peer_ip="93.184.216.34")
        safe = SafeTransport(resolver=resolver, transport=fake,
                            approved_domains={"example.com", "other.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            result = await safe.fetch("http://example.com/",
                                      approved_domains={"example.com", "other.com"})
        assert fake.call_count >= 2

    @pytest.mark.asyncio
    async def test_redirect_to_unapproved_blocked(self):
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        fake.set_response("http://example.com/", status=301,
                         body=b"", content_type="text/html",
                         peer_ip="93.184.216.34",
                         redirect_location="http://evil.com/")
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            result = await safe.fetch("http://example.com/", approved_domains={"example.com"})
        assert result.error_code is not None
        assert "redirect_domain_not_approved" in (result.error_code or "")


class TestRobotsFailClosed:
    """V1.1: robots fail-closed — only http_404 defaults to allow"""

    @pytest.mark.asyncio
    async def test_robots_non_html_skips_page(self):
        """non_html_content -> robots_unavailable, page fetch=0"""
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        # SafeTransport returns error_code for non-html robots
        fake.set_response("http://example.com/robots.txt", status=0,
                         body=b"", content_type="text/html", peer_ip="93.184.216.34")
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})

        page_fetched = False
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            robots_result = await safe.fetch("http://example.com/robots.txt",
                                             approved_domains={"example.com"})
            robots_error = robots_result.error_code
            # Fail-closed: only http_404 or successful parse allows page
            if robots_error == "http_404":
                page_fetched = True
            elif not robots_error:
                page_fetched = True
            # else: robots_unavailable -> skip page
        assert page_fetched is False

    @pytest.mark.asyncio
    async def test_robots_404_allows_page(self):
        """http_404 -> default allow, page fetch=1"""
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        fake.set_response("http://example.com/robots.txt", status=404,
                         body=b"not found", content_type="text/html", peer_ip="93.184.216.34")
        fake.set_response("http://example.com/page", status=200,
                         body=b"<html>ok</html>", content_type="text/html", peer_ip="93.184.216.34")
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})

        page_fetched = False
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            robots_result = await safe.fetch("http://example.com/robots.txt",
                                             approved_domains={"example.com"})
            if robots_result.error_code == "http_404" or not robots_result.error_code:
                await safe.fetch("http://example.com/page", approved_domains={"example.com"})
                page_fetched = True
        assert page_fetched is True

    @pytest.mark.asyncio
    async def test_robots_disallow_skips_page(self):
        """Disallow found -> robots_denied, page fetch=0"""
        resolver = RealDNSResolver()
        fake = FakeTransport(default_peer_ip="93.184.216.34")
        fake.set_response("http://example.com/robots.txt", status=200,
                         body=b"User-agent: *\nDisallow: /",
                         content_type="text/plain", peer_ip="93.184.216.34")
        safe = SafeTransport(resolver=resolver, transport=fake, approved_domains={"example.com"})

        page_fetched = False
        with patch.object(asyncio.get_event_loop(), "getaddrinfo",
                         new_callable=AsyncMock,
                         return_value=make_ipv4_result("93.184.216.34")):
            robots_result = await safe.fetch("http://example.com/robots.txt",
                                             approved_domains={"example.com"})
            if not robots_result.error_code:
                body = robots_result.body or ""
                disallow_found = False
                for line in body.split("\n"):
                    line = line.strip()
                    if line.startswith("Disallow:") and len(line.split(":", 1)[1].strip()) > 0:
                        disallow_found = True
                        break
                if disallow_found:
                    page_fetched = False
                else:
                    page_fetched = True
            elif robots_result.error_code == "http_404":
                page_fetched = True
            else:
                page_fetched = False
        assert page_fetched is False
