"""Source Mapping Batch1 Contract Tests.

验证6个新增域名的评分、子域继承、攻击反例、映射表delta。
"""
import math

import pytest

from search_router.scorers.source_credibility_scorer import (
    score_source_credibility,
    _KNOWN_SOURCES,
    _CHINESE_DISPLAY_NAMES,
    _match_domain,
)


# ── 1. 6个批准域名分数正确 ────────────────────────────

BATCH1_DOMAINS = {
    "news.cn": ("A", 0.9),
    "chinadaily.com.cn": ("A", 0.9),
    "stcn.com": ("B", 0.8),
    "xhby.net": ("B", 0.8),
    "cet.com.cn": ("B", 0.8),
    "zqrb.cn": ("B", 0.8),
}


@pytest.mark.parametrize("domain,expected_tier,expected_score", [
    (d, t, s) for d, (t, s) in BATCH1_DOMAINS.items()
])
def test_batch1_domain_score_correct(domain, expected_tier, expected_score):
    """6个批准域名分数正确。"""
    score, trace = score_source_credibility("", source_url=f"https://www.{domain}/article")
    assert score == expected_score
    assert trace["matched_domain"] == domain
    assert trace["tier"] == expected_tier
    assert trace["credibility_tier"] == expected_tier
    assert trace["matched_rule"] == "strict_domain_boundary"


# ── 2. 合法子域继承 ────────────────────────────────────

@pytest.mark.parametrize("hostname,expected_domain", [
    ("www.news.cn", "news.cn"),
    ("js.news.cn", "news.cn"),
    ("ex.chinadaily.com.cn", "chinadaily.com.cn"),
    ("www.stcn.com", "stcn.com"),
    ("www.xhby.net", "xhby.net"),
    ("www.cet.com.cn", "cet.com.cn"),
    ("www.zqrb.cn", "zqrb.cn"),
])
def test_batch1_subdomain_inheritance(hostname, expected_domain):
    """合法子域继承父域评分。"""
    score, trace = score_source_credibility("", source_url=f"https://{hostname}/path")
    expected_tier, expected_score = BATCH1_DOMAINS[expected_domain]
    assert score == expected_score
    assert trace["matched_domain"] == expected_domain
    assert trace["tier"] == expected_tier


# ── 3. 攻击反例拒绝 ────────────────────────────────────

@pytest.mark.parametrize("hostname", [
    "fakenews.cn",                    # 不匹配 news.cn
    "news.cn.evil.example",           # 不匹配 news.cn
    "notstcn.com",                    # 不匹配 stcn.com
    "stcn.com.evil.example",          # 不匹配 stcn.com
    "fakexhby.net",                   # 不匹配 xhby.net
    "cet.com.cn.evil.example",        # 不匹配 cet.com.cn
    "notzqrb.cn",                     # 不匹配 zqrb.cn
    "chinadaily.com.cn.evil.example", # 不匹配 chinadaily.com.cn
])
def test_batch1_attack_rejected(hostname):
    """8个攻击反例全部拒绝。"""
    score, trace = score_source_credibility("", source_url=f"https://{hostname}/path")
    assert math.isnan(score), f"{hostname} should NOT match any known domain"
    assert "unrecognized" in trace["match_type"]


# ── 4. 原有19个映射不变 ────────────────────────────────

def test_original_19_domains_unchanged():
    """原有19个域名仍然存在且分数不变。"""
    original_domains = {
        "gov.cn": ("A", 0.9), "people.com.cn": ("A", 0.9),
        "xinhuanet.com": ("A", 0.9), "cctv.com": ("A", 0.9),
        "sohu.com": ("B", 0.8), "163.com": ("B", 0.8),
        "qq.com": ("B", 0.8), "sina.com.cn": ("B", 0.8),
        "36kr.com": ("B", 0.8), "jiemian.com": ("B", 0.8),
        "thepaper.cn": ("B", 0.8),
        "meiye.com": ("C", 0.55), "cosmeticschina.net": ("C", 0.55),
        "morketing.com": ("C", 0.55),
        "toutiao.com": ("D", 0.4), "zhihu.com": ("D", 0.4),
        "baijiahao.baidu.com": ("D", 0.4), "mp.weixin.qq.com": ("D", 0.4),
        "douyin.com": ("D", 0.4),
    }
    for domain, (tier, score_val) in original_domains.items():
        assert domain in _KNOWN_SOURCES, f"{domain} missing from _KNOWN_SOURCES"
        assert _KNOWN_SOURCES[domain] == (tier, score_val), f"{domain} score changed"


# ── 5. 新增后总数=25 ──────────────────────────────────

def test_total_known_sources_is_25():
    """_KNOWN_SOURCES数量=25。"""
    assert len(_KNOWN_SOURCES) == 25


# ── 6. 中文别名仍为16 ─────────────────────────────────

def test_chinese_aliases_still_16():
    """_CHINESE_DISPLAY_NAMES继续保持16。"""
    assert len(_CHINESE_DISPLAY_NAMES) == 16


# ── 7. 未批准域名继续NaN ──────────────────────────────

@pytest.mark.parametrize("domain", [
    "ce.cn",
    "frontiersin.org",
    "chinairn.com",
    "cfi.cn",
    "luxe.co",
    "zhonghongwang.com",
    "unknown-random-site-xyz.com",
])
def test_unapproved_domain_nan(domain):
    """未批准域名继续返回NaN。"""
    score, trace = score_source_credibility("", source_url=f"https://www.{domain}/path")
    assert math.isnan(score)
    assert "unrecognized" in trace["match_type"]


# ── 8. URL脱敏11字段契约不变 ──────────────────────────

REQUIRED_TRACE_FIELDS = [
    "source_display_name", "source_url", "source_hostname",
    "source_identity", "identity_source", "match_type",
    "matched_rule", "matched_domain", "tier", "credibility_tier", "reason",
]


def test_batch1_trace_11_fields_complete():
    """Batch1域名命中后trace仍含11字段。"""
    score, trace = score_source_credibility("", source_url="https://www.news.cn/article")
    for key in REQUIRED_TRACE_FIELDS:
        assert key in trace
    assert trace["source_url"] == "https://www.news.cn"  # 只保留scheme+hostname
    assert trace["matched_rule"] == "strict_domain_boundary"


# ── 11. 不出现默认评分 ────────────────────────────────

def test_no_default_score():
    """未识别域名不得有默认评分(0.5或其他)。"""
    score, trace = score_source_credibility("", source_url="https://www.unknown-xyz.com/path")
    assert math.isnan(score)
    assert score != 0.5
    assert score != 0.0


# ── 12. 权重不变 ──────────────────────────────────────

def test_weights_unchanged():
    """confidence权重仍为0.45/0.25/0.30。"""
    from search_router.scorers.confidence_scorer import WEIGHTS
    assert WEIGHTS == {"source_credibility": 0.45, "freshness": 0.25, "relevance": 0.30}
