"""Publish Time Enricher — P0.2 Phase1 Offline Core.

离线核心模块: 日期解析 + URL安全验证 + robots决策 + 可注入fetcher接口。

本轮不实现真实HTTP客户端, 不发任何网络请求, 不接入主链。
仅使用Python标准库。
"""
from __future__ import annotations

import asyncio
import ipaddress
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlparse, urljoin


# ── 常量 ────────────────────────────────────────────────

_PUBLISHED_TIME_APPROVED_DOMAINS = {
    "news.cn": ("A", 0.9),
    "chinadaily.com.cn": ("A", 0.9),
    "stcn.com": ("B", 0.8),
}
# js.news.cn 按 news.cn 规则处理
_DOMAIN_ALIAS = {
    "js.news.cn": "news.cn",
    "www.news.cn": "news.cn",
    "ex.chinadaily.com.cn": "chinadaily.com.cn",
    "www.chinadaily.com.cn": "chinadaily.com.cn",
    "www.stcn.com": "stcn.com",
}

_MAX_REDIRECTS = 2
_MAX_RESPONSE_BYTES = 524288  # 512KB
_DEFAULT_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
_FUTURE_TOLERANCE_HOURS = 24

_DATE_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日",
]

_URL_DATE_PATTERN = re.compile(r'/(\d{4})-(\d{2})-(\d{2})/')
_URL_DATE_PATTERN2 = re.compile(r'/(\d{4})(\d{2})(\d{2})/')


# ── 结果数据类 ──────────────────────────────────────────

@dataclass
class ExtractionResult:
    """日期提取结果。"""
    publish_time: str | None = None
    evidence_level: str = "NONE"  # P1 / P2 / P3 / NONE
    extraction_method: str = "none"
    selector_or_rule: str = ""
    candidates_found: int = 0
    conflict: bool = False
    failure_reason: str = ""
    domain: str = ""
    timezone: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    """Enricher 返回结果。"""
    publish_time: str | None = None
    evidence_level: str = "NONE"
    extraction_method: str = "none"
    enriched: bool = False
    skipped_reason: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


# ── 安全验证 ────────────────────────────────────────────

def _is_safe_ip(ip_str: str) -> bool:
    """检查 IP 是否安全（非 loopback/private/link-local/reserved/multicast/unspecified）。

    V1.1修正: 显式检查 is_unspecified + not is_global 兜底, 不再依赖 is_private 间接覆盖。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    # 兜底: 非全局单播地址一律拒绝 (覆盖 TEST-NET, 100.64.0.0/10 等)
    if not ip.is_global:
        return False
    return True


def _check_ip_version_safety(ip_str: str) -> bool:
    """检查 IPv4/IPv6/IPv4-mapped IPv6 的安全性。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    # IPv4-mapped IPv6: ::ffff:a.b.c.d
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return _is_safe_ip(str(mapped))
    return _is_safe_ip(str(ip))


def validate_fetch_target(
    url: str,
    approved_domains: set[str],
    resolved_ips: list[str],
    redirect_chain: list[dict] | None = None,
) -> dict[str, Any]:
    """验证 fetch 目标 URL 的安全性。

    Returns:
        dict with keys: is_valid, rejection_reason, trace
    """
    trace: dict[str, Any] = {"url_scheme": "", "url_hostname": "", "url_port": None,
                              "has_userinfo": False, "ip_results": [], "redirect_count": 0}

    # 1. scheme 只能 http/https
    try:
        parsed = urlparse(url)
    except Exception:
        return {"is_valid": False, "rejection_reason": "invalid_url", "trace": trace}

    trace["url_scheme"] = parsed.scheme or ""

    if parsed.scheme not in ("http", "https"):
        return {"is_valid": False, "rejection_reason": "invalid_scheme", "trace": trace}

    # 2. 禁止 userinfo
    if parsed.username or parsed.password:
        trace["has_userinfo"] = True
        return {"is_valid": False, "rejection_reason": "userinfo_present", "trace": trace}

    # 3. 端口只能 80/443 或默认端口
    port = parsed.port
    trace["url_port"] = port
    if port is not None and port not in (80, 443):
        return {"is_valid": False, "rejection_reason": "invalid_port", "trace": trace}

    # 4. hostname 严格匹配批准域名
    hostname = parsed.hostname or ""
    trace["url_hostname"] = hostname
    if not hostname:
        return {"is_valid": False, "rejection_reason": "empty_hostname", "trace": trace}

    hostname_lower = hostname.lower().rstrip(".")
    domain_matched = False
    for domain in approved_domains:
        if hostname_lower == domain or hostname_lower.endswith("." + domain):
            domain_matched = True
            break
    if not domain_matched:
        return {"is_valid": False, "rejection_reason": "domain_not_approved", "trace": trace}

    # 5. 所有 DNS 结果必须是 global IP
    if not resolved_ips:
        return {"is_valid": False, "rejection_reason": "no_resolved_ips", "trace": trace}

    ip_results = []
    for ip_str in resolved_ips:
        safe = _check_ip_version_safety(ip_str)
        ip_results.append({"ip": ip_str, "safe": safe})
        if not safe:
            trace["ip_results"] = ip_results
            return {"is_valid": False, "rejection_reason": "unsafe_ip", "trace": trace}

    trace["ip_results"] = ip_results

    # 6. redirect 验证
    if redirect_chain:
        trace["redirect_count"] = len(redirect_chain)
        if len(redirect_chain) > _MAX_REDIRECTS:
            return {"is_valid": False, "rejection_reason": "redirect_limit_exceeded", "trace": trace}

        for i, hop in enumerate(redirect_chain):
            hop_url = hop.get("url", "")
            hop_ips = hop.get("resolved_ips", [])
            hop_result = validate_fetch_target(hop_url, approved_domains, hop_ips)
            if not hop_result["is_valid"]:
                return {"is_valid": False,
                        "rejection_reason": f"redirect_hop_{i}_invalid: {hop_result['rejection_reason']}",
                        "trace": trace}

    return {"is_valid": True, "rejection_reason": "", "trace": trace}


# ── robots 决策 ────────────────────────────────────────

def evaluate_robots_result(
    http_status: int,
    content_type: str,
    body: str,
    target_path: str,
    user_agent: str = "*",
) -> dict[str, Any]:
    """评估 robots.txt 结果。

    Returns:
        dict with keys: allowed, reason, trace
    """
    trace: dict[str, Any] = {"http_status": http_status, "content_type": content_type}

    # 5xx → fail-closed
    if 500 <= http_status < 600:
        return {"allowed": False, "reason": "robots_server_error", "trace": trace}

    # timeout/DNS error represented as status 0 or negative
    if http_status <= 0:
        return {"allowed": False, "reason": "robots_fetch_failed", "trace": trace}

    # 4xx → robots 不存在, 允许
    if 400 <= http_status < 500:
        return {"allowed": True, "reason": "robots_not_found_4xx", "trace": trace}

    # 2xx → 解析 robots
    if 200 <= http_status < 300:
        # 检查是否为有效 robots 文本（非 HTML 错误页）
        ct_lower = (content_type or "").lower()
        if "html" in ct_lower:
            return {"allowed": False, "reason": "malformed_robots_html", "trace": trace}

        # 简单检查: HTML 页面特征
        body_stripped = body.strip()[:200].lower()
        if body_stripped.startswith("<!doctype html") or body_stripped.startswith("<html"):
            return {"allowed": False, "reason": "malformed_robots_html", "trace": trace}

        # 解析 robots 规则
        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        try:
            rp.parse(body.splitlines())
            allowed = rp.can_fetch(user_agent, target_path)
            if not allowed:
                return {"allowed": False, "reason": "disallow_rule", "trace": trace}
            return {"allowed": True, "reason": "allowed_by_robots", "trace": trace}
        except Exception:
            return {"allowed": False, "reason": "robots_parse_error", "trace": trace}

    # 其他状态码
    return {"allowed": False, "reason": "robots_unknown_status", "trace": trace}


# ── HTML 解析器 ─────────────────────────────────────────

class _MetaPublishDateParser(HTMLParser):
    """提取 meta[name=publishdate] 的 content。"""
    def __init__(self):
        super().__init__()
        self.meta_publishdate: str | None = None
        self.json_ld_dates: list[str] = []
        self._in_script_json = False
        self._script_buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "meta":
            name = (attrs_dict.get("name") or "").lower()
            if name == "publishdate":
                self.meta_publishdate = attrs_dict.get("content", "")
        elif tag == "meta":
            prop = (attrs_dict.get("property") or "").lower()
            if prop == "article:published_time":
                self.meta_publishdate = self.meta_publishdate or attrs_dict.get("content", "")
        elif tag == "script":
            stype = (attrs_dict.get("type") or "").lower()
            if stype == "application/ld+json":
                self._in_script_json = True
                self._script_buffer = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_script_json:
            self._in_script_json = False
            text = "".join(self._script_buffer)
            # Simple JSON-LD datePublished extraction
            for match in re.finditer(r'"datePublished"\s*:\s*"([^"]+)"', text):
                self.json_ld_dates.append(match.group(1))

    def handle_data(self, data):
        if self._in_script_json:
            self._script_buffer.append(data)


class _DivPubtimeParser(HTMLParser):
    """提取 div#pubtime (chinadaily) 或 div.info 内日期 (news.cn) 或 span 内日期 (stcn.com)。"""
    def __init__(self, target_id=None, target_class=None, context_class=None):
        super().__init__()
        self.target_id = target_id
        self.target_class = target_class
        self.context_class = context_class
        self._in_target = False
        self._in_context = False
        self._depth = 0
        self.target_text: str | None = None
        self.context_text: str | None = None
        self.span_dates: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if self.target_id and attrs_dict.get("id") == self.target_id:
            self._in_target = True
            self._depth = 1
        elif self.target_class and attrs_dict.get("class") == self.target_class:
            if not self._in_target:
                self._in_target = True
                self._depth = 1
        elif self.context_class and attrs_dict.get("class") == self.context_class:
            self._in_context = True

        if self._in_target and tag == "span":
            pass  # span dates collected in handle_data

        if self._in_target:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._in_target:
            self._depth -= 1
            if self._depth <= 0:
                self._in_target = False
        if self._in_context and tag == "div":
            self._in_context = False

    def handle_data(self, data):
        if self._in_target:
            stripped = data.strip()
            if stripped:
                if self.target_text is None:
                    self.target_text = stripped
                else:
                    self.target_text += " " + stripped
        if self._in_context:
            stripped = data.strip()
            if stripped:
                if self.context_text is None:
                    self.context_text = stripped
                else:
                    self.context_text += " " + stripped


class _StcnSpanParser(HTMLParser):
    """stcn.com 专用 span 解析器。

    V1.1: 不依赖 class="info", 改用"来源/作者"关键词上下文定位。
    收集所有连续 span 文本, 找到含"来源"或"作者"的 span 后,
    在其相邻 span 中查找日期。不扫描导航/推荐/版权区域。
    """

    _DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}(?::\d{2})?)')
    _MAX_SPAN_AFTER = 3  # "来源/作者"span之后最多看3个相邻span (日期通常紧跟其后)

    def __init__(self):
        super().__init__()
        self._spans: list[str] = []  # 所有span文本
        self._in_span = False
        self._span_buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "span":
            self._in_span = True
            self._span_buffer = []

    def handle_endtag(self, tag):
        if tag == "span" and self._in_span:
            self._in_span = False
            text = "".join(self._span_buffer).strip()
            if text:
                self._spans.append(text)

    def handle_data(self, data):
        if self._in_span:
            self._span_buffer.append(data)

    def get_contextual_date(self) -> str | None:
        """返回与"来源/作者"上下文关联的日期, 无则返回 None。

        只向后查找 (_MAX_SPAN_AFTER), 不向前查找, 避免误取导航/推荐区域日期。
        """
        for i, text in enumerate(self._spans):
            if "来源" in text or "作者" in text:
                # 只在"来源/作者"之后的相邻 span 中查找日期
                end = min(len(self._spans), i + self._MAX_SPAN_AFTER + 1)
                for j in range(i, end):
                    match = self._DATE_RE.search(self._spans[j])
                    if match:
                        return match.group(1)
        return None


def _parse_date_string(date_str: str) -> datetime | None:
    """尝试解析日期字符串。"""
    date_str = date_str.strip()
    if not date_str:
        return None
    for fmt in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_DEFAULT_TZ)
            return dt
        except ValueError:
            continue
    return None


def _extract_url_date(url: str) -> str | None:
    """从 URL 路径提取日期（P3佐证）。"""
    for pattern in [_URL_DATE_PATTERN, _URL_DATE_PATTERN2]:
        match = pattern.search(url)
        if match:
            y, m, d = match.groups()
            return f"{y}-{m}-{d}"
    return None


def _resolve_domain(hostname: str) -> str | None:
    """将 hostname 映射到批准域名。"""
    hostname_lower = hostname.lower().rstrip(".")
    if hostname_lower.startswith("www."):
        hostname_lower = hostname_lower[4:]
    # Check alias
    full_hostname = hostname.lower().rstrip(".")
    if full_hostname in _DOMAIN_ALIAS:
        return _DOMAIN_ALIAS[full_hostname]
    for domain in _PUBLISHED_TIME_APPROVED_DOMAINS:
        if hostname_lower == domain or hostname_lower.endswith("." + domain):
            return domain
    return None


# ── 日期提取主函数 ──────────────────────────────────────

def extract_publish_time(
    html: str,
    source_url: str,
    approved_domain: str,
    reference_time: datetime | None = None,
) -> ExtractionResult:
    """从 HTML 提取发布时间。

    Args:
        html: 页面 HTML 文本
        source_url: 页面 URL
        approved_domain: 批准域名 (news.cn / chinadaily.com.cn / stcn.com)
        reference_time: 参考时间（用于未来日期检查）

    Returns:
        ExtractionResult
    """
    result = ExtractionResult(domain=approved_domain, timezone="Asia/Shanghai")

    if reference_time is None:
        reference_time = datetime.now(_DEFAULT_TZ)

    candidates: list[tuple[str, str, str]] = []  # (datetime_str, evidence_level, method)

    # P1: JSON-LD datePublished
    meta_parser = _MetaPublishDateParser()
    try:
        meta_parser.feed(html)
    except Exception:
        pass

    for date_str in meta_parser.json_ld_dates:
        parsed = _parse_date_string(date_str)
        if parsed:
            candidates.append((parsed.isoformat(), "P1", "json_ld_datePublished"))

    # P1: meta[property=article:published_time]
    # Already captured in meta_parser.meta_publishdate if property matches

    # P2: 域名专用规则
    if approved_domain == "news.cn":
        # meta[name=publishdate]
        if meta_parser.meta_publishdate:
            parsed = _parse_date_string(meta_parser.meta_publishdate)
            if parsed:
                candidates.append((parsed.isoformat(), "P2", "meta_publishdate"))

        # div.info 内正则提取
        div_parser = _DivPubtimeParser(context_class="info")
        try:
            div_parser.feed(html)
        except Exception:
            pass
        if div_parser.context_text:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}(?::\d{2})?)', div_parser.context_text)
            if date_match:
                parsed = _parse_date_string(date_match.group(1))
                if parsed:
                    candidates.append((parsed.isoformat(), "P2", "div_info_date"))

    elif approved_domain == "chinadaily.com.cn":
        # meta[name=publishdate]
        if meta_parser.meta_publishdate:
            parsed = _parse_date_string(meta_parser.meta_publishdate)
            if parsed:
                candidates.append((parsed.isoformat(), "P2", "meta_publishdate"))

        # div#pubtime
        div_parser = _DivPubtimeParser(target_id="pubtime")
        try:
            div_parser.feed(html)
        except Exception:
            pass
        if div_parser.target_text:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}(?::\d{2})?)', div_parser.target_text)
            if date_match:
                parsed = _parse_date_string(date_match.group(1))
                if parsed:
                    candidates.append((parsed.isoformat(), "P2", "div_pubtime"))

    elif approved_domain == "stcn.com":
        # V1.1修正: 不依赖 class="info", 改用"来源/作者"关键词上下文定位相邻span日期
        # stcn真实结构: <span>来源：XXX</span><span>作者：XXX</span><span>2025-06-19 07:28</span>
        span_parser = _StcnSpanParser()
        try:
            span_parser.feed(html)
        except Exception:
            pass
        # 只接受与"来源/作者"在同一个连续span序列中的日期
        date_str = span_parser.get_contextual_date()
        if date_str:
            parsed = _parse_date_string(date_str)
            if parsed:
                candidates.append((parsed.isoformat(), "P2", "stcn_context_span_date"))
        # 无上下文时不扫描整页 (fail-closed)

    # P3: URL 日期佐证
    url_date = _extract_url_date(source_url)
    if url_date:
        # P3 is only supporting evidence, not standalone confirmation
        result.trace["url_date_evidence"] = url_date

    # 冲突检测与结果选择
    result.candidates_found = len(candidates)

    if not candidates:
        result.failure_reason = "no_candidates"
        result.evidence_level = "NONE"
        result.trace["methods_tried"] = ["json_ld", "meta_publishdate", "domain_specific_dom"]
        return result

    # 检查冲突: 多个 P1/P2 候选日期不一致
    p1_p2_candidates = [(dt_str, level, method) for dt_str, level, method in candidates if level in ("P1", "P2")]
    unique_dates = set(dt_str[:10] for dt_str, _, _ in p1_p2_candidates)  # Compare date part only

    if len(unique_dates) > 1:
        result.conflict = True
        result.failure_reason = "date_conflict"
        result.evidence_level = "NONE"
        result.publish_time = None
        result.trace["candidates"] = [{"date": dt, "level": lv, "method": m} for dt, lv, m in p1_p2_candidates]
        return result

    # 选择最高证据等级的候选
    p1_p2_candidates.sort(key=lambda x: (0 if x[1] == "P1" else 1, x[2]))
    best_dt_str, best_level, best_method = p1_p2_candidates[0]

    # 未来日期检查
    parsed_dt = _parse_date_string(best_dt_str)
    if parsed_dt and reference_time:
        if parsed_dt > reference_time + timedelta(hours=_FUTURE_TOLERANCE_HOURS):
            result.failure_reason = "future_date"
            result.evidence_level = "NONE"
            result.publish_time = None
            result.trace["rejected_date"] = best_dt_str
            result.trace["reference_time"] = reference_time.isoformat()
            return result

    result.publish_time = best_dt_str
    result.evidence_level = best_level
    result.extraction_method = best_method
    result.selector_or_rule = best_method
    result.trace["selected_candidate"] = {"date": best_dt_str, "level": best_level, "method": best_method}
    return result


# ── Fetcher/Resolver/RobotsProvider 协议 ────────────────

class SafeFetcherProtocol(Protocol):
    """安全fetch协议：内部处理DNS+Ticket+连接+peer验证+重定向。"""
    async def fetch(
        self,
        url: str,
        approved_domains: set[str] | None = None,
    ) -> "FetchResult":  # noqa: F821 — FetchResult from safe_transport
        ...


class RobotsProviderProtocol(Protocol):
    async def get_robots(self, scheme: str, hostname: str) -> tuple[int, str, str]:  # (status, content_type, body)
        ...


# ── 可注入 fetcher 的 Enricher 接口 ────────────────────

async def enrich_publish_time(
    result: Any,
    safe_fetcher: SafeFetcherProtocol,
    robots_provider: RobotsProviderProtocol,
    approved_domains: set[str],
    reference_time: datetime | None = None,
) -> EnrichmentResult:
    """异步 enrich publish_time。

    本轮离线: safe_fetcher/robots_provider 全部由调用方注入。
    不发任何网络请求。
    """
    enr_result = EnrichmentResult()

    # 1. publish_time 已有值 → 不调用 fetcher
    if result.publish_time is not None and str(result.publish_time).strip():
        enr_result.skipped_reason = "publish_time_already_present"
        return enr_result

    # 2. source 未识别或非 A/B 级 → 不调用 fetcher
    if math.isnan(getattr(result, "source_credibility_score", float("nan"))):
        enr_result.skipped_reason = "source_not_identified"
        return enr_result

    src_trace = getattr(result, "computation_trace", {}).get("_source_credibility", {})
    tier = src_trace.get("credibility_tier") or src_trace.get("tier")
    if tier not in ("A", "B"):
        enr_result.skipped_reason = f"tier_{tier}_not_ab"
        return enr_result

    # 3. 域名未批准 → 不调用 fetcher
    source_url = getattr(result, "url", "") or ""
    if not source_url:
        enr_result.skipped_reason = "no_source_url"
        return enr_result

    try:
        parsed = urlparse(source_url)
    except Exception:
        enr_result.skipped_reason = "invalid_url"
        return enr_result

    hostname = (parsed.hostname or "").lower().rstrip(".")
    approved_domain = _resolve_domain(hostname)
    if not approved_domain or approved_domain not in _PUBLISHED_TIME_APPROVED_DOMAINS:
        enr_result.skipped_reason = "domain_not_approved_for_enrichment"
        return enr_result

    # 4. robots 检查（业务层检查，在网络请求前）
    try:
        robots_status, robots_ct, robots_body = await robots_provider.get_robots(
            parsed.scheme, hostname
        )
    except Exception:
        enr_result.skipped_reason = "robots_fetch_error"
        return enr_result

    robots_eval = evaluate_robots_result(
        robots_status, robots_ct, robots_body, parsed.path or "/", "*"
    )
    if not robots_eval["allowed"]:
        enr_result.skipped_reason = f"robots_blocked: {robots_eval['reason']}"
        enr_result.trace["robots"] = {"reason": robots_eval["reason"]}
        return enr_result

    # 5. 安全fetch（DNS+Ticket+连接+peer验证+重定向全部由SafeFetcher内部处理）
    try:
        fetch_result = await safe_fetcher.fetch(
            url=source_url,
            approved_domains=approved_domains,
        )
    except Exception as e:
        enr_result.skipped_reason = "fetch_error"
        enr_result.trace["error"] = "fetch_exception"
        return enr_result

    # 6. 检查FetchResult — error_code非空时fail closed
    if fetch_result.error_code is not None:
        enr_result.skipped_reason = fetch_result.error_code
        enr_result.trace["fetch_error"] = fetch_result.error_code
        return enr_result

    if fetch_result.status != 200:
        enr_result.skipped_reason = f"http_{fetch_result.status}"
        return enr_result

    body = fetch_result.body

    # 7. 解析日期
    extraction = extract_publish_time(body, source_url, approved_domain, reference_time)

    enr_result.publish_time = extraction.publish_time
    enr_result.evidence_level = extraction.evidence_level
    enr_result.extraction_method = extraction.extraction_method
    enr_result.enriched = extraction.publish_time is not None
    # trace 不得含完整正文/Cookie/凭据/完整敏感URL
    enr_result.trace = {
        "domain": extraction.domain,
        "evidence_level": extraction.evidence_level,
        "extraction_method": extraction.extraction_method,
        "candidates_found": extraction.candidates_found,
        "conflict": extraction.conflict,
        "failure_reason": extraction.failure_reason,
    }
    if not enr_result.enriched and extraction.failure_reason:
        enr_result.skipped_reason = extraction.failure_reason

    return enr_result
