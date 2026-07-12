"""RealDNSResolver — 真实DNS解析器，通过socket.getaddrinfo获取全量IP。

契约：
- async resolve(hostname) -> list[str]
- 真实getaddrinfo受5秒超时约束（原子：单次AF_UNSPEC查询，整体5秒）
- 返回全部去重IPv4/IPv6
- 不得只选第一个后再验证
- 空结果、异常、超时 fail-closed（返回空列表，无部分结果）
- 不缓存、不跨请求复用
- 日志只记录hostname和IP数量，不记录完整IP
- 不读取代理环境变量
- SafeTransport负责对全部IP执行安全验证
- safe+unsafe混合结果必须由上层整票拒绝
- 不过滤mapped地址，由Ticket安全校验统一拒绝
"""
from __future__ import annotations

import asyncio
import socket
import time
from typing import Any


_DNS_TIMEOUT = 5.0


class RealDNSResolver:
    """真实DNS解析器 — 全量getaddrinfo + 去重 + 超时保护。

    每次 resolve 调用独立执行DNS查询，不缓存不跨请求复用。
    返回全部IPv4和IPv6结果（去重），不进行安全筛选——
    安全筛选由 SafeTransport + ResolutionTicket 负责。

    Fail-closed原则（V1.1原子化）：
    - 单次AF_UNSPEC+SOCK_STREAM查询，整体5秒超时
    - DNS超时 → 空列表（无部分结果）
    - DNS异常 → 空列表（无部分结果）
    - 空结果 → 空列表
    - 不过滤mapped地址，由ResolutionTicket安全校验统一拒绝
    """

    def __init__(self, timeout: float = _DNS_TIMEOUT) -> None:
        self._timeout = timeout
        self._audit_log: list[dict[str, Any]] = []

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """审计日志（脱敏，不含完整IP）。"""
        return list(self._audit_log)

    async def resolve(self, hostname: str) -> list[str]:
        """DNS解析 — 单次AF_UNSPEC原子查询，返回全部去重IP。

        Args:
            hostname: 待解析的域名

        Returns:
            去重后的IP列表（IPv4在前，IPv6在后），可能为空

        Note:
            单次getaddrinfo(AF_UNSPEC)查询，整体5秒超时。
            超时/异常/空结果均为fail-closed，不返回部分结果。
            不过滤mapped地址，由ResolutionTicket安全校验统一拒绝。
        """
        start = time.monotonic()
        ipv4_set: set[str] = set()
        ipv6_set: set[str] = set()

        try:
            # 原子化：单次AF_UNSPEC查询，整体5秒超时
            results = await asyncio.wait_for(
                asyncio.get_event_loop().getaddrinfo(
                    hostname, None,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                ),
                timeout=self._timeout,
            )

            for r in results:
                family = r[0]
                ip = r[4][0]
                if family == socket.AF_INET:
                    ipv4_set.add(ip)
                elif family == socket.AF_INET6:
                    ipv6_set.add(ip)

            # 去重合并：IPv4在前
            all_ips = list(ipv4_set) + list(ipv6_set)

            elapsed = time.monotonic() - start

            # 审计日志：只记录hostname和IP数量，不记录完整IP
            self._audit_log.append({
                "action": "dns_resolve",
                "hostname": hostname,
                "ipv4_count": len(ipv4_set),
                "ipv6_count": len(ipv6_set),
                "total_count": len(all_ips),
                "getaddrinfo_calls": 1,
                "elapsed_ms": round(elapsed * 1000, 1),
            })

            return all_ips

        except asyncio.TimeoutError:
            # DNS超时 → fail-closed → 空列表（无部分结果）
            elapsed = time.monotonic() - start
            self._audit_log.append({
                "action": "dns_resolve_timeout",
                "hostname": hostname,
                "error": "timeout",
                "elapsed_ms": round(elapsed * 1000, 1),
            })
            return []

        except (socket.gaierror, OSError):
            # DNS异常 → fail-closed → 空列表（无部分结果）
            elapsed = time.monotonic() - start
            self._audit_log.append({
                "action": "dns_resolve_error",
                "hostname": hostname,
                "error": "gaierror_or_oserror",
                "elapsed_ms": round(elapsed * 1000, 1),
            })
            return []

        except Exception:
            # 任何未预期异常 → fail-closed → 空列表
            elapsed = time.monotonic() - start
            self._audit_log.append({
                "action": "dns_resolve_error",
                "hostname": hostname,
                "error": "unexpected",
                "elapsed_ms": round(elapsed * 1000, 1),
            })
            return []
