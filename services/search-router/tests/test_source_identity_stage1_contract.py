"""Source Identity Stage1 Contract Tests.

验证:
  1. 4个合法域名正例
  2. 6+个边界攻击反例
  3. URL hostname优先于错误display name
  4. 无URL时中文别名fallback仍工作
  5. 未知域名仍NaN
  6. 非HTTP URL不作为可信hostname
  7. trace九项完整
  8. 现有权重不变
  9. Tavily tanh不变
  10. GLM无可执行0.75
  11. Provider角色不变
  12. 两张映射表内容不变
"""
import ast
import math

import pytest

from search_router.scorers.source_credibility_scorer import (
    score_source_credibility,
    _KNOWN_SOURCES,
    _CHINESE_DISPLAY_NAMES,
    _match_domain,
    _extract_hostname,
)
from search_router.scorers.confidence_scorer import (
    WEIGHTS,
    compute_relevance_from_tavily_score,
)
from search_router.adapters.bocha import BochaAdapter
from search_router.adapters.tavily import TavilyAdapter
from search_router.adapters.glm_search import GLMSearchAdapter
from search_router.models.search_response import ProviderType


# ── 1. 合法域名正例 ────────────────────────────────────

@pytest.mark.parametrize("hostname,expected_domain,expected_score", [
    ("gov.cn", "gov.cn", 0.9),
    ("policy.mofcom.gov.cn", "gov.cn", 0.9),
    ("m.163.com", "163.com", 0.8),
    ("zhuanlan.zhihu.com", "zhihu.com", 0.4),
])
def test_domain_match_positive(hostname, expected_domain, expected_score):
    """合法正例: 子域名匹配父域名。"""
    score, trace = score_source_credibility("", source_url=f"https://{hostname}/article/1")
    assert trace["matched_domain"] == expected_domain
    assert score == expected_score
    assert trace["identity_source"] == "url_hostname"


# ── 2. 边界攻击反例 ────────────────────────────────────

@pytest.mark.parametrize("hostname", [
    "fakegov.cn",           # 不匹配 gov.cn
    "gov.cn.example.com",   # 不匹配 gov.cn
    "evil163.com",          # 不匹配 163.com
    "zhihu.com.evil.example",  # 不匹配 zhihu.com
    "notqq.com",            # 不匹配 qq.com
    "sohu.com.evil.com",    # 不匹配 sohu.com
])
def test_domain_match_negative_attack(hostname):
    """边界攻击反例: 不应匹配已知域名。"""
    score, trace = score_source_credibility("", source_url=f"https://{hostname}/path")
    assert math.isnan(score), f"{hostname} should NOT match any known domain, got score={score}"
    assert "unrecognized" in trace["match_type"]


# ── 3. 非HTTP URL不作为可信hostname ────────────────────

def test_non_http_url_not_trusted():
    """非HTTP URL (如 glm-search://ref_1) 不作为可信hostname。"""
    score, trace = score_source_credibility("some_source", source_url="glm-search://ref_1")
    # 应 fallback 到 source_name
    assert trace["identity_source"] in ("display_name_fallback", "none")
    assert not trace["source_hostname"]  # None or empty string


def test_glm_fallback_url_not_trusted():
    """GLM 兜底 URL 不被识别成可信域名。"""
    score, trace = score_source_credibility("glm_search", source_url="glm-search://ref_1")
    assert math.isnan(score)
    assert not trace["source_hostname"]  # None or empty string


# ── 4. URL hostname优先于错误display name ──────────────

def test_url_hostname_priority_over_display_name():
    """URL hostname优先于错误的display name。"""
    # display name 是未知信源, 但 URL hostname 是已知域名
    score, trace = score_source_credibility(
        "未知媒体", source_url="https://www.sohu.com/a/123"
    )
    assert not math.isnan(score)
    assert trace["matched_domain"] == "sohu.com"
    assert trace["identity_source"] == "url_hostname"
    assert trace["source_hostname"] == "sohu.com"


# ── 5. 无URL时中文别名fallback ─────────────────────────

def test_chinese_display_name_fallback_without_url():
    """无URL时, 中文别名仍然工作。"""
    score, trace = score_source_credibility("搜狐")
    assert score == 0.8
    assert trace["match_type"] == "chinese_display_name_match"
    assert trace["matched_domain"] == "sohu.com"
    assert trace["identity_source"] in ("display_name_fallback", "chinese_display_name_match")


def test_chinese_display_name_with_url_still_works():
    """有URL但URL无效时, fallback到中文别名。"""
    score, trace = score_source_credibility("网易", source_url="")
    assert score == 0.8
    assert trace["matched_domain"] == "163.com"


# ── 6. 未知域名仍NaN ───────────────────────────────────

def test_unknown_domain_nan():
    """未知域名仍返回NaN。"""
    score, trace = score_source_credibility("", source_url="https://www.unknown-random-site-xyz.com/article")
    assert math.isnan(score)
    assert "unrecognized" in trace["match_type"]


def test_unknown_source_name_nan():
    """未知source_name无URL仍返回NaN。"""
    score, trace = score_source_credibility("某个完全未知的媒体")
    assert math.isnan(score)


# ── 7. trace十一项完整 ───────────────────────────────────

REQUIRED_TRACE_FIELDS = [
    "source_display_name",
    "source_url",
    "source_hostname",
    "source_identity",
    "identity_source",
    "match_type",
    "matched_rule",
    "matched_domain",
    "tier",
    "credibility_tier",
    "reason",
]


def test_trace_fields_complete_success_branch():
    """11个trace字段在成功分支完整。"""
    score, trace = score_source_credibility("搜狐", source_url="https://www.sohu.com/a/1")
    for key in REQUIRED_TRACE_FIELDS:
        assert key in trace, f"trace missing required field: {key}"
    assert trace["matched_rule"] == "strict_domain_boundary"
    assert trace["credibility_tier"] == trace["tier"]
    assert trace["credibility_tier"] == "B"


def test_trace_fields_complete_unknown_domain_branch():
    """11个trace字段在未知域名分支完整。"""
    score, trace = score_source_credibility("", source_url="https://www.unknown-xyz.com/article")
    for key in REQUIRED_TRACE_FIELDS:
        assert key in trace, f"trace missing required field: {key}"
    assert trace["matched_rule"] == "unrecognized"
    assert trace["credibility_tier"] is None
    assert trace["tier"] is None


def test_trace_fields_complete_empty_input_branch():
    """11个trace字段在空输入分支完整。"""
    score, trace = score_source_credibility("")
    for key in REQUIRED_TRACE_FIELDS:
        assert key in trace, f"trace missing required field: {key}"
    assert trace["matched_rule"] == "unrecognized"
    assert trace["credibility_tier"] is None
    assert trace["source_display_name"] == ""
    assert trace["source_url"] == ""
    assert trace["source_hostname"] == ""


def test_trace_fields_complete_chinese_display_name_branch():
    """11个trace字段在中文别名分支完整。"""
    score, trace = score_source_credibility("网易")
    for key in REQUIRED_TRACE_FIELDS:
        assert key in trace, f"trace missing required field: {key}"
    assert trace["matched_rule"] == "chinese_display_name_exact"
    assert trace["credibility_tier"] == trace["tier"]
    assert trace["credibility_tier"] == "B"


def test_matched_rule_values():
    """matched_rule取值正确。"""
    # strict_domain_boundary (URL hostname match)
    _, t1 = score_source_credibility("", source_url="https://www.sohu.com/a/1")
    assert t1["matched_rule"] == "strict_domain_boundary"
    # chinese_display_name_exact
    _, t2 = score_source_credibility("搜狐")
    assert t2["matched_rule"] == "chinese_display_name_exact"
    # display_name_domain_boundary
    _, t3 = score_source_credibility("sohu.com")
    assert t3["matched_rule"] == "display_name_domain_boundary"
    # unrecognized
    _, t4 = score_source_credibility("未知媒体")
    assert t4["matched_rule"] == "unrecognized"
    # unrecognized (URL hostname valid but unknown)
    _, t5 = score_source_credibility("", source_url="https://www.unknown-xyz.com/a")
    assert t5["matched_rule"] == "unrecognized"


def test_credibility_tier_matches_tier():
    """credibility_tier与tier一致。"""
    # Success branch
    _, t1 = score_source_credibility("", source_url="https://www.gov.cn/policy")
    assert t1["credibility_tier"] == t1["tier"]
    assert t1["credibility_tier"] == "A"
    # NaN branch
    _, t2 = score_source_credibility("unknown")
    assert t2["credibility_tier"] is None
    assert t2["tier"] is None


# ── 7b. URL脱敏收紧 ───────────────────────────────────

def test_trace_url_only_scheme_hostname():
    """source_url只保留scheme+hostname。"""
    score, trace = score_source_credibility(
        "搜狐", source_url="https://www.sohu.com/user/123/article/456?token=secret#section"
    )
    url_in_trace = trace["source_url"]
    assert url_in_trace == "https://www.sohu.com"
    # No path
    assert "/user" not in url_in_trace
    assert "/123" not in url_in_trace
    # No query
    assert "token" not in url_in_trace
    assert "secret" not in url_in_trace
    assert "?" not in url_in_trace
    # No fragment
    assert "#" not in url_in_trace
    assert "section" not in url_in_trace


def test_trace_url_no_path_query_fragment_userinfo():
    """path/query/fragment/userinfo均不进入trace。"""
    score, trace = score_source_credibility(
        "sohu.com",
        source_url="https://user:pass@www.sohu.com:8443/a/b/c?api_key=sk-secret&token=xyz#frag"
    )
    url_in_trace = trace["source_url"]
    assert url_in_trace == "https://www.sohu.com"
    assert "user" not in url_in_trace
    assert "pass" not in url_in_trace
    assert "8443" not in url_in_trace
    assert "api_key" not in url_in_trace
    assert "sk-secret" not in url_in_trace
    assert "token" not in url_in_trace
    assert "/a/b/c" not in url_in_trace
    assert "frag" not in url_in_trace


def test_trace_url_non_http_returns_empty():
    """非HTTP URL的source_url在trace中为空字符串。"""
    score, trace = score_source_credibility("test", source_url="glm-search://ref_1")
    assert trace["source_url"] == ""


def test_trace_url_empty_input_returns_empty():
    """空URL输入的source_url在trace中为空字符串。"""
    score, trace = score_source_credibility("搜狐", source_url="")
    assert trace["source_url"] == ""


def test_trace_url_none_input_returns_empty():
    """None URL输入的source_url在trace中为空字符串。"""
    score, trace = score_source_credibility("搜狐", source_url=None)
    assert trace["source_url"] == ""


# ── 8. 现有权重不变 ────────────────────────────────────

def test_weights_unchanged():
    """Phase1评分权重不变。"""
    assert WEIGHTS["source_credibility"] == 0.45
    assert WEIGHTS["freshness"] == 0.25
    assert WEIGHTS["relevance"] == 0.30


# ── 9. Tavily tanh不变 ─────────────────────────────────

def test_tavily_tanh_unchanged():
    """Tavily relevance tanh规范化公式不变。"""
    rel, trace = compute_relevance_from_tavily_score(0.93)
    import math as _math
    expected = _math.tanh(0.93 * 1.5)
    assert rel == pytest.approx(expected)


# ── 10. GLM无可执行0.75 ────────────────────────────────

def test_glm_no_hardcode_075():
    """GLM可执行代码无0.75硬编码。"""
    import inspect
    from search_router.adapters import glm_search as glm_mod
    source = inspect.getsource(glm_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            assert abs(float(node.value) - 0.75) > 1e-9, f"Line {node.lineno}: hardcoded 0.75"


# ── 11. Provider角色不变 ───────────────────────────────

def test_provider_roles_unchanged():
    """Provider角色: Bocha=PRIMARY, Tavily=PRIMARY, GLM=FALLBACK。"""
    assert BochaAdapter(api_key="x").provider_type == ProviderType.PRIMARY
    assert TavilyAdapter(api_key="x").provider_type == ProviderType.PRIMARY
    assert GLMSearchAdapter(api_key="x").provider_type == ProviderType.FALLBACK


# ── 12. 两张映射表内容不变 ─────────────────────────────

def test_known_sources_unchanged():
    """_KNOWN_SOURCES 内容: 原有19个域名不变 + Batch1新增6个 = 25。"""
    assert len(_KNOWN_SOURCES) == 25
    # A级 (原有4 + Batch1新增2)
    assert _KNOWN_SOURCES["gov.cn"] == ("A", 0.9)
    assert _KNOWN_SOURCES["people.com.cn"] == ("A", 0.9)
    assert _KNOWN_SOURCES["xinhuanet.com"] == ("A", 0.9)
    assert _KNOWN_SOURCES["cctv.com"] == ("A", 0.9)
    # B级
    assert _KNOWN_SOURCES["sohu.com"] == ("B", 0.8)
    assert _KNOWN_SOURCES["163.com"] == ("B", 0.8)
    assert _KNOWN_SOURCES["qq.com"] == ("B", 0.8)
    assert _KNOWN_SOURCES["sina.com.cn"] == ("B", 0.8)
    assert _KNOWN_SOURCES["36kr.com"] == ("B", 0.8)
    assert _KNOWN_SOURCES["jiemian.com"] == ("B", 0.8)
    assert _KNOWN_SOURCES["thepaper.cn"] == ("B", 0.8)
    # C级
    assert _KNOWN_SOURCES["meiye.com"] == ("C", 0.55)
    assert _KNOWN_SOURCES["cosmeticschina.net"] == ("C", 0.55)
    assert _KNOWN_SOURCES["morketing.com"] == ("C", 0.55)
    # D级
    assert _KNOWN_SOURCES["toutiao.com"] == ("D", 0.4)
    assert _KNOWN_SOURCES["zhihu.com"] == ("D", 0.4)
    assert _KNOWN_SOURCES["baijiahao.baidu.com"] == ("D", 0.4)
    assert _KNOWN_SOURCES["mp.weixin.qq.com"] == ("D", 0.4)
    assert _KNOWN_SOURCES["douyin.com"] == ("D", 0.4)


def test_chinese_display_names_unchanged():
    """_CHINESE_DISPLAY_NAMES 内容不变: 16个别名。"""
    assert len(_CHINESE_DISPLAY_NAMES) == 16
    assert _CHINESE_DISPLAY_NAMES["搜狐"] == "sohu.com"
    assert _CHINESE_DISPLAY_NAMES["网易"] == "163.com"
    assert _CHINESE_DISPLAY_NAMES["腾讯"] == "qq.com"
    assert _CHINESE_DISPLAY_NAMES["新浪"] == "sina.com.cn"
    assert _CHINESE_DISPLAY_NAMES["36氪"] == "36kr.com"
    assert _CHINESE_DISPLAY_NAMES["界面"] == "jiemian.com"
    assert _CHINESE_DISPLAY_NAMES["澎湃"] == "thepaper.cn"
    assert _CHINESE_DISPLAY_NAMES["人民日报"] == "people.com.cn"
    assert _CHINESE_DISPLAY_NAMES["新华网"] == "xinhuanet.com"
    assert _CHINESE_DISPLAY_NAMES["央视"] == "cctv.com"
    assert _CHINESE_DISPLAY_NAMES["今日头条"] == "toutiao.com"
    assert _CHINESE_DISPLAY_NAMES["知乎"] == "zhihu.com"
    assert _CHINESE_DISPLAY_NAMES["百家号"] == "baijiahao.baidu.com"
    assert _CHINESE_DISPLAY_NAMES["微信公众号"] == "mp.weixin.qq.com"
    assert _CHINESE_DISPLAY_NAMES["抖音"] == "douyin.com"
    assert _CHINESE_DISPLAY_NAMES["美业"] == "meiye.com"


# ── 13. 旧接口兼容 ────────────────────────────────────

def test_backward_compat_single_arg():
    """旧的一参数调用必须继续工作。"""
    score, trace = score_source_credibility("搜狐")
    assert score == 0.8


def test_backward_compat_empty_source():
    """空source_name无URL返回NaN。"""
    score, trace = score_source_credibility("")
    assert math.isnan(score)


# ── 14. _match_domain 单元测试 ─────────────────────────

def test_match_domain_exact():
    """精确匹配。"""
    assert _match_domain("sohu.com", "sohu.com") is True

def test_match_domain_subdomain():
    """子域名匹配。"""
    assert _match_domain("m.sohu.com", "sohu.com") is True

def test_match_domain_no_false_positive():
    """不匹配伪域名。"""
    assert _match_domain("evilsohu.com", "sohu.com") is False
    assert _match_domain("sohu.com.evil.com", "sohu.com") is False


# ── 15. hostname 提取 ──────────────────────────────────

def test_extract_hostname_valid():
    """有效URL提取hostname。"""
    assert _extract_hostname("https://www.sohu.com/a/123") == "sohu.com"

def test_extract_hostname_no_scheme():
    """无scheme的URL不提取hostname。"""
    assert _extract_hostname("www.sohu.com/a/123") is None

def test_extract_hostname_non_http():
    """非HTTP协议不提取hostname。"""
    assert _extract_hostname("ftp://sohu.com/file") is None
    assert _extract_hostname("glm-search://ref_1") is None

def test_extract_hostname_trailing_dot():
    """去除末尾点。"""
    assert _extract_hostname("https://sohu.com./a") == "sohu.com"
