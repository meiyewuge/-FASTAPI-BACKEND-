"""Source Credibility Scorer — P0.2 Phase1 + Stage1.

Stage1 修复:
  1. 支持 source_url 参数, 从 URL hostname 提取信源身份 (优先于 display name)
  2. 严格域名边界匹配: candidate == known_domain 或 candidate.endswith("." + known_domain)
     替换原 domain in source_lower 的 substring contains 缺陷

未识别信源→NaN→quarantine，不得默认C级或0.55。
支持中文显示名匹配(如"搜狐"→sohu.com)。
"""
from __future__ import annotations
import math
from typing import Any
from urllib.parse import urlparse

_KNOWN_SOURCES = {
    "gov.cn": ("A", 0.9), "people.com.cn": ("A", 0.9),
    "xinhuanet.com": ("A", 0.9), "cctv.com": ("A", 0.9),
    # Batch1 新增 A级
    "news.cn": ("A", 0.9), "chinadaily.com.cn": ("A", 0.9),
    "sohu.com": ("B", 0.8), "163.com": ("B", 0.8),
    "qq.com": ("B", 0.8), "sina.com.cn": ("B", 0.8),
    "36kr.com": ("B", 0.8), "jiemian.com": ("B", 0.8),
    "thepaper.cn": ("B", 0.8),
    # Batch1 新增 B级
    "stcn.com": ("B", 0.8), "xhby.net": ("B", 0.8),
    "cet.com.cn": ("B", 0.8), "zqrb.cn": ("B", 0.8),
    "meiye.com": ("C", 0.55), "cosmeticschina.net": ("C", 0.55),
    "morketing.com": ("C", 0.55),
    "toutiao.com": ("D", 0.4), "zhihu.com": ("D", 0.4),
    "baijiahao.baidu.com": ("D", 0.4), "mp.weixin.qq.com": ("D", 0.4),
    "douyin.com": ("D", 0.4),
}

_CHINESE_DISPLAY_NAMES = {
    "搜狐": "sohu.com", "网易": "163.com",
    "腾讯": "qq.com", "新浪": "sina.com.cn",
    "36氪": "36kr.com", "界面": "jiemian.com",
    "澎湃": "thepaper.cn",
    "人民日报": "people.com.cn", "新华网": "xinhuanet.com",
    "央视": "cctv.com",
    "今日头条": "toutiao.com", "知乎": "zhihu.com",
    "百家号": "baijiahao.baidu.com", "微信公众号": "mp.weixin.qq.com",
    "抖音": "douyin.com",
    "美业": "meiye.com",
}

NAN_SCORE = float("nan")


def _extract_hostname(source_url: str | None) -> str | None:
    """从 URL 中提取 hostname。

    只接受 http 或 https 协议。
    hostname 转小写, 去除末尾 "."
    去除单个明确的 "www." 前缀用于匹配。
    URL 无效/非HTTP/hostname为空 → 返回 None。
    """
    if not source_url or not isinstance(source_url, str):
        return None
    try:
        parsed = urlparse(source_url)
        if parsed.scheme not in ("http", "https"):
            return None
        hostname = parsed.hostname
        if not hostname:
            return None
        hostname = hostname.lower().rstrip(".")
        # 去除单个明确的 www. 前缀
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return None


def _safe_url_for_trace(source_url: str | None) -> str:
    """source_url 进入 trace 前只保留 scheme://hostname。

    不得保存 path / query / fragment / userinfo / port后凭据 / API Key。
    URL无效或非HTTP/HTTPS → 返回空字符串。
    """
    if not source_url or not isinstance(source_url, str):
        return ""
    try:
        parsed = urlparse(source_url)
        if parsed.scheme not in ("http", "https"):
            return ""
        hostname = parsed.hostname or ""
        if not hostname:
            return ""
        return f"{parsed.scheme}://{hostname}"
    except Exception:
        return ""


def _match_domain(candidate: str, known_domain: str) -> bool:
    """严格域名边界匹配。

    candidate == known_domain 或 candidate.endswith("." + known_domain)
    不使用 contains / 正则模糊命中。
    """
    if candidate == known_domain:
        return True
    if candidate.endswith("." + known_domain):
        return True
    return False


def score_source_credibility(source_name: str, source_url: str | None = None) -> tuple[float, dict]:
    """评估信源可信度。

    身份优先级:
      1. 有效 URL hostname → 严格边界匹配 _KNOWN_SOURCES
      2. source_name 精确中文别名 → _CHINESE_DISPLAY_NAMES
      3. source_name 作为域名候选 → 严格边界匹配
      4. 未识别 → NaN

    Args:
        source_name: 信源显示名 (siteName / media / source field)
        source_url: 可选 URL, 用于提取 hostname 作为评分身份

    Returns:
        (score, trace): score 为 0.0-1.0 或 NaN, trace 包含完整诊断信息

    Trace 11个必须字段 (所有分支始终存在):
      source_display_name, source_url, source_hostname, source_identity,
      identity_source, match_type, matched_rule, matched_domain, tier,
      credibility_tier, reason
    """
    # 初始化所有11个trace字段，确保每个分支都有
    trace: dict[str, Any] = {
        "module": "source_credibility_scorer",
        "input_source": source_name,
        "source_display_name": source_name or "",
        "source_url": _safe_url_for_trace(source_url),
        "source_hostname": "",
        "source_identity": "",
        "identity_source": "none",
        "match_type": "none",
        "matched_rule": "none",
        "matched_domain": None,
        "tier": None,
        "credibility_tier": None,
        "reason": "",
    }

    # Step 1: 从 URL 提取 hostname
    hostname = _extract_hostname(source_url)
    trace["source_hostname"] = hostname or ""

    if hostname:
        trace["source_identity"] = hostname
        trace["identity_source"] = "url_hostname"
        # 用 hostname 做严格边界匹配
        for domain, (tier, score) in _KNOWN_SOURCES.items():
            if _match_domain(hostname, domain):
                trace["match_type"] = "url_hostname_domain_match"
                trace["matched_rule"] = "strict_domain_boundary"
                trace["matched_domain"] = domain
                trace["tier"] = tier
                trace["credibility_tier"] = tier
                trace["reason"] = f"URL hostname '{hostname}' 匹配已知{tier}级域名{domain}"
                return score, trace
        # hostname 有效但不在已知列表
        trace["match_type"] = "url_hostname_unrecognized"
        trace["matched_rule"] = "unrecognized"
        trace["matched_domain"] = None
        trace["tier"] = None
        trace["credibility_tier"] = None
        trace["reason"] = f"URL hostname '{hostname}' 不在已知域名列表"
        return NAN_SCORE, trace

    # Step 2: source_name 中文显示名精确匹配
    source_stripped = (source_name or "").strip()
    if source_stripped in _CHINESE_DISPLAY_NAMES:
        domain = _CHINESE_DISPLAY_NAMES[source_stripped]
        tier, score = _KNOWN_SOURCES[domain]
        trace["source_identity"] = source_stripped
        trace["identity_source"] = "display_name_fallback"
        trace["match_type"] = "chinese_display_name_match"
        trace["matched_rule"] = "chinese_display_name_exact"
        trace["matched_domain"] = domain
        trace["tier"] = tier
        trace["credibility_tier"] = tier
        trace["reason"] = f"中文显示名'{source_stripped}'匹配已知{tier}级域名{domain}"
        return score, trace

    # Step 3: source_name 作为域名候选, 严格边界匹配
    if source_stripped:
        source_lower = source_stripped.lower().rstrip(".")
        if source_lower.startswith("www."):
            source_lower = source_lower[4:]
        for domain, (tier, score) in _KNOWN_SOURCES.items():
            if _match_domain(source_lower, domain):
                trace["source_identity"] = source_lower
                trace["identity_source"] = "display_name_fallback"
                trace["match_type"] = "domain_match"
                trace["matched_rule"] = "display_name_domain_boundary"
                trace["matched_domain"] = domain
                trace["tier"] = tier
                trace["credibility_tier"] = tier
                trace["reason"] = f"信源'{source_lower}'匹配已知{tier}级域名{domain}"
                return score, trace

    # Step 4: 未识别
    trace["source_identity"] = source_stripped or ""
    trace["identity_source"] = "none"
    trace["match_type"] = "unrecognized"
    trace["matched_rule"] = "unrecognized"
    trace["matched_domain"] = None
    trace["tier"] = None
    trace["credibility_tier"] = None
    trace["reason"] = f"信源{source_name}不在已知列表，标记NaN"
    return NAN_SCORE, trace
