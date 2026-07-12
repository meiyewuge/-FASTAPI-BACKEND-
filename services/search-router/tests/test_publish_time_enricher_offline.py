"""Publish Time Enricher Offline Tests.

25+ test cases covering:
  1-4: HTML fixture parsing (4 domains)
  5: P1/P2/P3/NONE classification
  6: datePublished vs dateModified priority
  7: date conflict
  8: future date rejection
  9: invalid date
  10: page-irrelevant year not misidentified
  11-14: dangerous IP types (loopback, private, link-local, reserved)
  15: IPv6 + mapped IPv6
  16: mixed safe/unsafe IP → reject all
  17: 3 redirect hops rejected
  18: cross-domain redirect rejected
  19: userinfo rejected
  20: non-80/443 port rejected
  21: 4xx robots allowed
  22: 5xx robots rejected
  23: timeout rejected
  24: HTML fake robots rejected
  25: Disallow rejected
  26: publish_time already present → no fetch
  27: D-grade/unknown source → no fetch
  28: unapproved domain → no fetch
  29: exception fail-closed
  30: input object not modified
  31: sensitive info not in trace
"""
import asyncio
import copy
import math
import os
from datetime import datetime, timedelta, timezone

import pytest

from search_router.enrichers.publish_time_enricher import (
    extract_publish_time,
    validate_fetch_target,
    evaluate_robots_result,
    enrich_publish_time,
    EnrichmentResult,
    _is_safe_ip,
    _check_ip_version_safety,
    _parse_date_string,
    _resolve_domain,
)
from search_router.enrichers.safe_transport import FetchResult

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "publish_time")
_APPROVED_DOMAINS = {"news.cn", "chinadaily.com.cn", "stcn.com"}


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


# ── 1-4. HTML fixture parsing ──────────────────────────

def test_news_cn_fixture_parsing():
    """news.cn fixture: meta[publishdate] + div.info date → P2。"""
    html = _load_fixture("news_cn_sample.html")
    result = extract_publish_time(html, "https://www.news.cn/2026-07/10/c_123456.htm", "news.cn")
    assert result.publish_time is not None
    assert "2026-07-10" in result.publish_time
    assert result.evidence_level == "P2"
    assert result.extraction_method in ("meta_publishdate", "div_info_date")
    assert result.conflict is False


def test_chinadaily_fixture_parsing():
    """chinadaily.com.cn fixture: meta[publishdate] + div#pubtime → P2。"""
    html = _load_fixture("chinadaily_com_cn_sample.html")
    result = extract_publish_time(html, "https://ex.chinadaily.com.cn/a/123", "chinadaily.com.cn")
    assert result.publish_time is not None
    assert "2026-07-08" in result.publish_time
    assert result.evidence_level == "P2"
    assert result.extraction_method in ("meta_publishdate", "div_pubtime")


def test_stcn_fixture_parsing():
    """stcn.com fixture: 来源/作者上下文span日期 → P2, 诱饵日期不误取。"""
    html = _load_fixture("stcn_com_sample.html")
    result = extract_publish_time(html, "https://www.stcn.com/article/123.html", "stcn.com")
    assert result.publish_time is not None
    assert "2025-06-19" in result.publish_time  # 真实文章日期
    assert "2025-01-01" not in result.publish_time  # 导航诱饵
    assert "2024-12-15" not in result.publish_time  # 推荐诱饵
    assert "2025-12-31" not in result.publish_time  # 版权诱饵
    assert result.evidence_level == "P2"
    assert result.extraction_method == "stcn_context_span_date"


def test_js_news_cn_fixture_parsing():
    """js.news.cn 按 news.cn 规则处理。"""
    html = _load_fixture("js_news_cn_sample.html")
    result = extract_publish_time(html, "https://js.news.cn/a/123", "news.cn")
    assert result.publish_time is not None
    assert "2026-07-05" in result.publish_time
    assert result.evidence_level == "P2"


# ── 5. P1/P2/P3/NONE classification ───────────────────

def test_p1_json_ld_datepublished():
    """JSON-LD datePublished → P1。"""
    html = '<html><script type="application/ld+json">{"datePublished":"2026-07-01T10:00:00+08:00"}</script></html>'
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    assert result.evidence_level == "P1"
    assert result.publish_time is not None


def test_none_no_candidates():
    """无日期候选 → NONE。"""
    html = "<html><body><p>No dates here at all.</p></body></html>"
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    assert result.evidence_level == "NONE"
    assert result.publish_time is None


# ── 6. datePublished vs dateModified priority ─────────

def test_datepublished_priority_over_datemodified():
    """datePublished 优先于 dateModified。"""
    html = '''<html><script type="application/ld+json">
    {"datePublished":"2026-07-01T10:00:00+08:00","dateModified":"2026-07-05T12:00:00+08:00"}
    </script></html>'''
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    assert result.publish_time is not None
    assert "2026-07-01" in result.publish_time  # datePublished, not dateModified


# ── 7. date conflict ──────────────────────────────────

def test_date_conflict():
    """多个 P1/P2 候选日期不一致 → conflict=True, publish_time=None。"""
    html = '''<html>
    <meta name="publishdate" content="2026-07-01 10:00:00">
    <div class="info">来源：新华网　　2026-07-10 15:30:00</div>
    </html>'''
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    assert result.conflict is True
    assert result.failure_reason == "date_conflict"
    assert result.publish_time is None


# ── 8. future date ────────────────────────────────────

def test_future_date_rejected():
    """未来超过 reference_time 24 小时的日期 → 拒绝。"""
    ref_time = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    html = '<html><script type="application/ld+json">{"datePublished":"2026-08-15T10:00:00+08:00"}</script></html>'
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn", reference_time=ref_time)
    assert result.publish_time is None
    assert result.failure_reason == "future_date"


# ── 9. invalid date ───────────────────────────────────

def test_invalid_date_rejected():
    """无效日期格式 → 拒绝。"""
    html = '<html><meta name="publishdate" content="not-a-date-at-all"></html>'
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    # The invalid date won't parse → no candidates from that method
    assert result.evidence_level == "NONE"


# ── 10. page-irrelevant year not misidentified ────────

def test_copyright_year_not_misidentified():
    """版权年份不误认为发布日期。"""
    html = '<html><body><footer>© 2015-2024 新华网版权所有</footer></body></html>'
    result = extract_publish_time(html, "https://www.news.cn/a/123", "news.cn")
    assert result.evidence_level == "NONE"
    assert result.publish_time is None


# ── 11-14. Dangerous IP types ─────────────────────────

def test_loopback_ip_rejected():
    assert not _is_safe_ip("127.0.0.1")
    assert not _is_safe_ip("::1")

def test_private_ip_rejected():
    assert not _is_safe_ip("10.0.0.1")
    assert not _is_safe_ip("192.168.1.1")
    assert not _is_safe_ip("172.16.0.1")

def test_link_local_ip_rejected():
    assert not _is_safe_ip("169.254.1.1")

def test_reserved_ip_rejected():
    assert not _is_safe_ip("0.0.0.0")
    assert not _is_safe_ip("240.0.0.1")


def test_multicast_ip_rejected():
    assert not _is_safe_ip("224.0.0.1")


# ── V1.1新增: unspecified + non-global ─────────────────

def test_unspecified_ipv4_rejected():
    """0.0.0.0 → is_unspecified → 显式拒绝。"""
    assert not _is_safe_ip("0.0.0.0")


def test_unspecified_ipv6_rejected():
    """:: → is_unspecified → 显式拒绝。"""
    assert not _is_safe_ip("::")


def test_test_net_1_rejected():
    """192.0.2.1 (TEST-NET-1) → not is_global → 拒绝。"""
    assert not _is_safe_ip("192.0.2.1")


def test_test_net_2_rejected():
    """198.51.100.1 (TEST-NET-2) → not is_global → 拒绝。"""
    assert not _is_safe_ip("198.51.100.1")


def test_test_net_3_rejected():
    """203.0.113.1 (TEST-NET-3) → not is_global → 拒绝。"""
    assert not _is_safe_ip("203.0.113.1")


def test_carrier_grade_nat_rejected():
    """100.64.0.1 (Carrier-Grade NAT) → not is_global → 拒绝。"""
    assert not _is_safe_ip("100.64.0.1")


def test_ipv4_mapped_test_net_rejected():
    """::ffff:192.0.2.1 → mapped TEST-NET → 不安全。"""
    assert not _check_ip_version_safety("::ffff:192.0.2.1")


def test_global_ip_accepted():
    """1.1.1.1 (Cloudflare) → is_global → 安全。"""
    assert _is_safe_ip("1.1.1.1")
    assert _is_safe_ip("8.8.8.8")


def test_stcn_decoy_dates_not_misidentified():
    """stcn fixture: 导航/推荐/版权区域日期不被误取。"""
    html = _load_fixture("stcn_com_sample.html")
    result = extract_publish_time(html, "https://www.stcn.com/article/123.html", "stcn.com")
    if result.publish_time:
        assert "2025-01-01" not in result.publish_time  # 导航
        assert "2024-12-15" not in result.publish_time  # 推荐
        assert "2025-12-31" not in result.publish_time  # 版权


# ── 15. IPv6 + mapped IPv6 ────────────────────────────

def test_ipv6_safety():
    assert _is_safe_ip("2606:4700:4700::1111")  # Cloudflare DNS, public
    assert not _is_safe_ip("fc00::1")  # ULA/private
    assert not _is_safe_ip("fe80::1")  # link-local


def test_ipv4_mapped_ipv6_safety():
    """IPv4-mapped IPv6: ::ffff:127.0.0.1 → loopback → unsafe。"""
    assert not _check_ip_version_safety("::ffff:127.0.0.1")
    assert not _check_ip_version_safety("::ffff:10.0.0.1")


# ── 16. Mixed safe/unsafe IP → reject all ─────────────

def test_mixed_ips_reject_all():
    """一个安全 IP + 一个危险 IP → 整体拒绝。"""
    result = validate_fetch_target(
        "https://www.news.cn/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1", "127.0.0.1"],  # safe + loopback
    )
    assert result["is_valid"] is False
    assert result["rejection_reason"] == "unsafe_ip"


# ── 17. 3 redirect hops rejected ──────────────────────

def test_three_redirects_rejected():
    """3次redirect → 超过限制 → 拒绝。"""
    redirect_chain = [
        {"url": "https://www.news.cn/r1", "resolved_ips": ["1.1.1.1"]},
        {"url": "https://www.news.cn/r2", "resolved_ips": ["1.1.1.1"]},
        {"url": "https://www.news.cn/r3", "resolved_ips": ["1.1.1.1"]},
    ]
    result = validate_fetch_target(
        "https://www.news.cn/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
        redirect_chain=redirect_chain,
    )
    assert result["is_valid"] is False
    assert "redirect" in result["rejection_reason"]


# ── 18. cross-domain redirect rejected ────────────────

def test_cross_domain_redirect_rejected():
    """redirect 跳出批准域名集合 → 拒绝。"""
    redirect_chain = [
        {"url": "https://evil.example.com/r1", "resolved_ips": ["1.1.1.1"]},
    ]
    result = validate_fetch_target(
        "https://www.news.cn/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
        redirect_chain=redirect_chain,
    )
    assert result["is_valid"] is False


# ── 19. userinfo rejected ─────────────────────────────

def test_userinfo_rejected():
    """URL含userinfo → 拒绝。"""
    result = validate_fetch_target(
        "https://user:pass@www.news.cn/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
    )
    assert result["is_valid"] is False
    assert result["rejection_reason"] == "userinfo_present"


# ── 20. non-80/443 port rejected ──────────────────────

def test_non_standard_port_rejected():
    """非80/443端口 → 拒绝。"""
    result = validate_fetch_target(
        "https://www.news.cn:8443/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
    )
    assert result["is_valid"] is False
    assert result["rejection_reason"] == "invalid_port"


# ── 21. 4xx robots allowed ────────────────────────────

def test_4xx_robots_allowed():
    """4xx → robots不存在, 允许。"""
    result = evaluate_robots_result(404, "text/html", "Not Found", "/article", "*")
    assert result["allowed"] is True


# ── 22. 5xx robots rejected ───────────────────────────

def test_5xx_robots_rejected():
    """5xx → fail-closed, 拒绝。"""
    result = evaluate_robots_result(503, "text/html", "Service Unavailable", "/article", "*")
    assert result["allowed"] is False


# ── 23. timeout rejected ──────────────────────────────

def test_timeout_robots_rejected():
    """timeout (status=0) → fail-closed, 拒绝。"""
    result = evaluate_robots_result(0, "", "", "/article", "*")
    assert result["allowed"] is False


# ── 24. HTML fake robots rejected ─────────────────────

def test_html_fake_robots_rejected():
    """2xx 但返回 HTML 错误页 → malformed_robots, 拒绝。"""
    html_body = "<!DOCTYPE html><html><body>404 Not Found</body></html>"
    result = evaluate_robots_result(200, "text/html", html_body, "/article", "*")
    assert result["allowed"] is False
    assert "malformed" in result["reason"]


# ── 25. Disallow rejected ─────────────────────────────

def test_disallow_rejected():
    """明确 Disallow → 拒绝。"""
    robots_body = "User-agent: *\nDisallow: /article\n"
    result = evaluate_robots_result(200, "text/plain", robots_body, "/article", "*")
    assert result["allowed"] is False
    assert result["reason"] == "disallow_rule"


# ── 26. publish_time already present → no fetch ───────

class _FakeSafeFetcher:
    def __init__(self):
        self.called = False
    async def fetch(self, url, approved_domains=None):
        self.called = True
        from search_router.enrichers.safe_transport import FetchResult
        return FetchResult(
            status=200, content_type="text/html", body="<html></html>",
            peer_ip="1.1.1.1", redirect_location=None, bytes_read=14,
            final_url_safe="https://www.news.cn", error_code=None,
        )

class _FakeRobotsProvider:
    async def get_robots(self, scheme, hostname):
        return 200, "text/plain", "User-agent: *\nAllow: /\n"

class _MockResult:
    def __init__(self, publish_time=None, source_credibility_score=float("nan"),
                 url="", computation_trace=None):
        self.publish_time = publish_time
        self.source_credibility_score = source_credibility_score
        self.url = url
        self.computation_trace = computation_trace or {}


def test_publish_time_already_present_no_fetch():
    """publish_time已有值 → 不调用fetcher。"""
    fetcher = _FakeSafeFetcher()
    result = _MockResult(
        publish_time="2026-07-01",
        source_credibility_score=0.9,
        url="https://www.news.cn/a/1",
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    enr = asyncio.run(enrich_publish_time(
        result, fetcher, _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    assert fetcher.called is False
    assert enr.skipped_reason == "publish_time_already_present"


# ── 27. D-grade/unknown source → no fetch ─────────────

def test_d_grade_source_no_fetch():
    """D级来源 → 不调用fetcher。"""
    fetcher = _FakeSafeFetcher()
    result = _MockResult(
        source_credibility_score=0.4,
        url="https://www.toutiao.com/a/1",
        computation_trace={"_source_credibility": {"credibility_tier": "D"}},
    )
    enr = asyncio.run(enrich_publish_time(
        result, fetcher, _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    assert fetcher.called is False
    assert "tier" in enr.skipped_reason


# ── 28. unapproved domain → no fetch ──────────────────

def test_unapproved_domain_no_fetch():
    """未批准域名 → 不调用fetcher。"""
    fetcher = _FakeSafeFetcher()
    result = _MockResult(
        source_credibility_score=0.8,
        url="https://www.sohu.com/a/1",  # sohu.com not in enrichment approved domains
        computation_trace={"_source_credibility": {"credibility_tier": "B"}},
    )
    enr = asyncio.run(enrich_publish_time(
        result, fetcher, _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    assert fetcher.called is False
    assert "domain" in enr.skipped_reason


# ── 29. exception fail-closed ─────────────────────────

def test_exception_fail_closed():
    """fetcher 异常 → fail-closed, publish_time=None。"""
    class _ErrorFetcher:
        async def fetch(self, url, approved_domains=None):
            raise ConnectionError("network error")
    result = _MockResult(
        source_credibility_score=0.9,
        url="https://www.news.cn/a/1",
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    enr = asyncio.run(enrich_publish_time(
        result, _ErrorFetcher(), _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    assert enr.publish_time is None
    assert enr.enriched is False


# ── 30. input object not modified ─────────────────────

def test_input_object_not_modified():
    """输入对象不被修改。"""
    fetcher = _FakeSafeFetcher()
    result = _MockResult(
        source_credibility_score=0.9,
        url="https://www.news.cn/a/1",
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    original_pt = result.publish_time
    original_url = result.url
    original_trace = copy.deepcopy(result.computation_trace)

    asyncio.run(enrich_publish_time(
        result, fetcher, _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    # Verify input unchanged
    assert result.publish_time == original_pt
    assert result.url == original_url
    assert result.computation_trace == original_trace


# ── 31. sensitive info not in trace ───────────────────

def test_sensitive_info_not_in_trace():
    """trace不得含完整正文/Cookie/凭据。"""
    html = _load_fixture("news_cn_sample.html")
    fetcher = _FakeSafeFetcher()
    fetcher._body = html
    async def fake_fetch(url, approved_domains=None):
        fetcher.called = True
        from search_router.enrichers.safe_transport import FetchResult
        return FetchResult(
            status=200, content_type="text/html", body=html,
            peer_ip="1.1.1.1", redirect_location=None, bytes_read=len(html.encode("utf-8")),
            final_url_safe="https://www.news.cn", error_code=None,
        )
    fetcher.fetch = fake_fetch

    result = _MockResult(
        source_credibility_score=0.9,
        url="https://www.news.cn/a/1",
        computation_trace={"_source_credibility": {"credibility_tier": "A"}},
    )
    enr = asyncio.run(enrich_publish_time(
        result, fetcher, _FakeRobotsProvider(),
        _APPROVED_DOMAINS,
    ))
    trace_str = str(enr.trace)
    # No full HTML body in trace
    assert "<html>" not in trace_str
    assert "<meta" not in trace_str
    # No Cookie/Authorization
    assert "Cookie" not in trace_str
    assert "Authorization" not in trace_str
    assert "api_key" not in trace_str.lower()


# ── Additional: domain resolution ─────────────────────

def test_resolve_domain_news_cn():
    assert _resolve_domain("www.news.cn") == "news.cn"
    assert _resolve_domain("js.news.cn") == "news.cn"
    assert _resolve_domain("news.cn") == "news.cn"

def test_resolve_domain_chinadaily():
    assert _resolve_domain("ex.chinadaily.com.cn") == "chinadaily.com.cn"
    assert _resolve_domain("www.chinadaily.com.cn") == "chinadaily.com.cn"

def test_resolve_domain_stcn():
    assert _resolve_domain("www.stcn.com") == "stcn.com"

def test_resolve_domain_unknown():
    assert _resolve_domain("www.unknown.com") is None


# ── Additional: valid fetch target ────────────────────

def test_valid_fetch_target():
    """正常URL+安全IP → 通过。"""
    result = validate_fetch_target(
        "https://www.news.cn/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
    )
    assert result["is_valid"] is True


def test_non_http_scheme_rejected():
    """非HTTP协议 → 拒绝。"""
    result = validate_fetch_target(
        "file:///etc/passwd",
        _APPROVED_DOMAINS,
        [],
    )
    assert result["is_valid"] is False
    assert result["rejection_reason"] == "invalid_scheme"


def test_domain_not_approved_rejected():
    """域名不在批准列表 → 拒绝。"""
    result = validate_fetch_target(
        "https://www.evil.com/article",
        _APPROVED_DOMAINS,
        ["1.1.1.1"],
    )
    assert result["is_valid"] is False
    assert result["rejection_reason"] == "domain_not_approved"
