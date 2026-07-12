"""标准Robots.txt安全提供者 — fail-closed语义。

通过SafeTransport.fetch_robots()获取robots.txt，
使用urllib.robotparser.RobotFileParser做标准语义解析。
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from search_router.enrichers.safe_transport import SafeTransport

logger = logging.getLogger(__name__)

ROBOTS_USER_AGENT = "WuYouSearchRouter"
ROBOTS_MAX_BYTES = 65536  # 64KB


class RobotsDecision(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RobotsCheckResult:
    decision: RobotsDecision
    reason: str
    trace: dict[str, Any] = field(default_factory=dict)


class StandardRobotsProvider:
    """标准Robots提供者 — 完整fail-closed语义。

    实现RobotsProviderProtocol (get_robots) 向后兼容。
    同时提供check_robots()返回结构化决策。
    """

    def __init__(
        self,
        safe_fetcher: SafeTransport,
        approved_domains: set[str] | None = None,
    ) -> None:
        self._safe_fetcher = safe_fetcher
        self._approved_domains = approved_domains or set()
        self._audit_log: list[dict[str, Any]] = []

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    async def get_robots(self, scheme: str, hostname: str) -> tuple[int, str, str]:
        """RobotsProviderProtocol兼容接口。

        返回(status, content_type, body)。
        不可用情况返回(0, "", "")，使evaluate_robots_result判定为fetch_failed→allowed=False。
        """
        result = await self.check_robots(scheme, hostname)

        if result.decision == RobotsDecision.UNAVAILABLE:
            self._audit_log.append({"hostname": hostname, "decision": "unavailable", "reason": result.reason})
            return (0, "", "")

        if result.decision == RobotsDecision.DENY:
            # 返回一个robots文本让evaluate_robots_result正确解析为disallow
            self._audit_log.append({"hostname": hostname, "decision": "deny", "reason": result.reason})
            return (200, "text/plain", result.trace.get("robots_body", "User-agent: *\nDisallow: /"))

        # ALLOW — 分两种情况
        self._audit_log.append({"hostname": hostname, "decision": "allow", "reason": result.reason})
        if "robots_body" in result.trace:
            return (200, "text/plain", result.trace["robots_body"])
        # 404/410 default allow
        status_code = result.trace.get("http_status", 404)
        return (status_code, "", "")

    async def check_robots(
        self,
        scheme: str,
        hostname: str,
        path: str = "/",
    ) -> RobotsCheckResult:
        """完整robots决策 — fail-closed语义。"""
        robots_url = f"{scheme}://{hostname}/robots.txt"
        trace: dict[str, Any] = {"url_safe": f"{scheme}://{hostname}/robots.txt"}

        # 1. 通过SafeTransport.fetch_robots()获取
        fetch_result = await self._safe_fetcher.fetch_robots(robots_url, self._approved_domains)

        # 2. 传输层错误 → unavailable
        if fetch_result.error_code:
            # 排除http_404和http_410 — 这些是正常的"robots不存在"
            if fetch_result.error_code == "http_404":
                return RobotsCheckResult(
                    decision=RobotsDecision.ALLOW,
                    reason="http_404_default_allow",
                    trace={**trace, "http_status": 404},
                )
            if fetch_result.error_code == "http_410":
                return RobotsCheckResult(
                    decision=RobotsDecision.ALLOW,
                    reason="http_410_default_allow",
                    trace={**trace, "http_status": 410},
                )
            # 401/403 → unavailable
            if fetch_result.error_code in ("http_401", "http_403"):
                return RobotsCheckResult(
                    decision=RobotsDecision.UNAVAILABLE,
                    reason=f"http_{fetch_result.error_code}_unavailable",
                    trace=trace,
                )
            # 其他错误 → unavailable
            return RobotsCheckResult(
                decision=RobotsDecision.UNAVAILABLE,
                reason=fetch_result.error_code,
                trace=trace,
            )

        status = fetch_result.status
        ct = fetch_result.content_type
        body = fetch_result.body

        # 3. HTTP状态码判定
        # 5xx → unavailable
        if 500 <= status < 600:
            return RobotsCheckResult(
                decision=RobotsDecision.UNAVAILABLE,
                reason="server_error",
                trace={**trace, "http_status": status},
            )

        # 401/403 → unavailable
        if status in (401, 403):
            return RobotsCheckResult(
                decision=RobotsDecision.UNAVAILABLE,
                reason=f"http_{status}_unavailable",
                trace={**trace, "http_status": status},
            )

        # 404/410 → default allow
        if status in (404, 410):
            return RobotsCheckResult(
                decision=RobotsDecision.ALLOW,
                reason=f"http_{status}_default_allow",
                trace={**trace, "http_status": status},
            )

        # 其他4xx → unavailable（不同于evaluate_robots_result的旧逻辑）
        if 400 <= status < 500:
            return RobotsCheckResult(
                decision=RobotsDecision.UNAVAILABLE,
                reason=f"http_{status}_unavailable",
                trace={**trace, "http_status": status},
            )

        # 2xx → 解析robots文本
        if 200 <= status < 300:
            ct_lower = (ct or "").lower()

            # 内容类型检查：仅接受text/*
            if ct_lower and not ct_lower.startswith("text/"):
                return RobotsCheckResult(
                    decision=RobotsDecision.UNAVAILABLE,
                    reason="non_text_content_type",
                    trace={**trace, "http_status": status, "content_type": ct},
                )

            # 空content-type也允许（某些服务器不返回ct）

            # 检查是否为HTML错误页
            body_stripped = body.strip()[:200].lower()
            if body_stripped.startswith("<!doctype html") or body_stripped.startswith("<html"):
                return RobotsCheckResult(
                    decision=RobotsDecision.UNAVAILABLE,
                    reason="html_error_page",
                    trace={**trace, "http_status": status},
                )

            # Body大小检查（64KB）
            if len(body.encode("utf-8")) > ROBOTS_MAX_BYTES:
                return RobotsCheckResult(
                    decision=RobotsDecision.UNAVAILABLE,
                    reason="body_exceeds_64kb",
                    trace={**trace, "http_status": status},
                )

            # 标准robots解析
            from urllib.robotparser import RobotFileParser
            rp = RobotFileParser()
            try:
                rp.parse(body.splitlines())
                allowed = rp.can_fetch(ROBOTS_USER_AGENT, path)
                if not allowed:
                    return RobotsCheckResult(
                        decision=RobotsDecision.DENY,
                        reason="disallow_rule",
                        trace={**trace, "http_status": status, "robots_body": body},
                    )
                return RobotsCheckResult(
                    decision=RobotsDecision.ALLOW,
                    reason="allowed_by_robots",
                    trace={**trace, "http_status": status, "robots_body": body},
                )
            except Exception:
                return RobotsCheckResult(
                    decision=RobotsDecision.UNAVAILABLE,
                    reason="parse_error",
                    trace={**trace, "http_status": status},
                )

        # 3xx → 不应该到这里（重定向在SafeTransport内部处理）
        # 其他状态 → unavailable
        return RobotsCheckResult(
            decision=RobotsDecision.UNAVAILABLE,
            reason=f"unexpected_status_{status}",
            trace={**trace, "http_status": status},
        )
