"""real_transport.py — 真实TCP/TLS Transport，IP固定、无二次DNS、fail-closed。

V2.0: PUBLIC_PEER_CAPTURE — 使用aiohttp 3.13.5公开socket_factory API替换
      私有连接池peer提取(V1.2 Method1: resp.connection.transport, Method2: session._connector._conns)。

      改动:
      - 新增 _PeerCaptureContext: 每次请求独立捕获上下文
      - socket_factory只创建到approved_ip的socket
      - 连接后通过socket.getpeername()获取真实peer
      - 禁止跨请求复用socket引用
      - peer缺失→ERR_PEER_IP_UNAVAILABLE (fail-closed)
      - 删除所有_connector/_conns/resp.connection私有属性访问

遵守TransportProtocol接口，被SafeTransport注入使用。

核心安全契约(15条)：
1. 实际TCP连接只连接ResolutionTicket批准IP
2. 不允许连接库对hostname再次DNS解析
3. HTTPS: SNI=原hostname, 证书链正常验证, hostname正常验证, 禁止verify=False
4. 连接后读取实际peer IP，交由现有逻辑复核
5. Host请求头使用原始hostname，不使用IP
6. 禁止自动重定向
7. 禁止环境代理
8. connect/read/total timeout分别遵守5/10/15秒
9. Content-Length超限时正文读取量=0
10. 无Content-Length时分块读取，最多512KB+1
11. gzip保持压缩字节交给现有SafeTransport有界解压
12. 不记录正文、query、userinfo、Cookie、Authorization
13. 固定无凭据User-Agent
14. 响应头仅提取必要字段
15. socket、stream、TLS异常全部fail-closed并关闭资源
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp.abc import AbstractResolver

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────

_RT_USER_AGENT = "WuYouSearchRouter/1.0"


# ── 单IP解析器 ────────────────────────────────────────


class _SingleIPResolver(AbstractResolver):
    """只返回一个预批准IP的单次解析器 — 禁止二次DNS。

    安全语义：
    - 只允许解析原始hostname（构造时指定）
    - 解析结果只有构造时指定的approved_ip
    - 任何对其他hostname的解析请求立即拒绝
    """

    def __init__(self, hostname: str, approved_ip: str) -> None:
        self._hostname = hostname.lower()
        self._approved_ip = approved_ip
        self._resolve_log: list[dict[str, Any]] = []

    @property
    def resolve_log(self) -> list[dict[str, Any]]:
        """审计：所有resolve调用记录。"""
        return list(self._resolve_log)

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[dict[str, Any]]:
        self._resolve_log.append({
            "host": host,
            "port": port,
            "family": int(family),
            "timestamp": time.monotonic(),
        })
        if host.lower() != self._hostname:
            raise RuntimeError(
                f"二次DNS拒绝: 请求解析'{host}'≠批准'{self._hostname}'"
            )
        resolved_family = socket.AF_INET6 if ":" in self._approved_ip else socket.AF_INET
        return [{
            "hostname": host,
            "host": self._approved_ip,
            "port": port,
            "family": int(resolved_family),
            "proto": 0,
            "flags": 0,
        }]

    async def close(self) -> None:
        pass


# ── Peer捕获上下文 (V2.0 PUBLIC API) ────────────────


class _PeerCaptureContext:
    """每次raw_fetch请求独立的peer捕获上下文。

    使用aiohttp 3.13.5公开socket_factory API：
    - socket_factory在连接创建时被aiohttp调用
    - 只允许创建到approved_ip对应地址的socket
    - 连接完成后通过socket.getpeername()获取真实peer
    - 每个上下文只服务一次请求，禁止跨请求复用

    安全契约：
    - socket_factory检查目标地址是否匹配approved_ip
    - 不匹配→拒绝创建socket→连接失败(fail-closed)
    - peer缺失→ERR_PEER_IP_UNAVAILABLE
    - getpeername异常→ERR_PEER_IP_UNAVAILABLE
    """

    def __init__(self, approved_ip: str) -> None:
        self._approved_ip = approved_ip
        self._captured_socket: socket.socket | None = None
        self._socket_created = False
        self._peer_ip: str | None = None
        self._peer_capture_log: list[dict[str, Any]] = []

    @property
    def peer_ip(self) -> str | None:
        """已捕获的peer IP，未捕获返回None。"""
        return self._peer_ip

    @property
    def capture_log(self) -> list[dict[str, Any]]:
        """peer捕获审计日志。"""
        return list(self._peer_capture_log)

    def socket_factory(
        self,
        addr_info: tuple,
    ) -> socket.socket:
        """aiohttp公开API: 创建socket并捕获引用。

        addr_info格式: (family, type, proto, canonname, sockaddr)
        sockaddr: IPv4=(host, port), IPv6=(host, port, flow, scope)

        安全检查:
        - 验证sockaddr中的host匹配approved_ip
        - 不匹配→OSError(fail-closed)
        - 二次调用→OSError(每请求只允许一个socket)
        """
        if self._socket_created:
            self._peer_capture_log.append({
                "event": "duplicate_socket_factory_call",
                "approved_ip": self._approved_ip,
            })
            raise OSError("socket_factory called more than once — per-request isolation violation")

        family, socktype, proto, canonname, sockaddr = addr_info

        # 提取目标地址
        if len(sockaddr) >= 2:
            target_host = sockaddr[0]
            target_port = sockaddr[1]
        else:
            self._peer_capture_log.append({
                "event": "invalid_sockaddr",
                "sockaddr": str(sockaddr),
            })
            raise OSError(f"Invalid sockaddr format: {sockaddr}")

        # 安全校验：目标IP必须匹配approved_ip
        if target_host != self._approved_ip:
            self._peer_capture_log.append({
                "event": "ip_mismatch_rejected",
                "approved_ip": self._approved_ip,
                "target_host": target_host,
            })
            raise OSError(
                f"socket_factory IP mismatch: target={target_host} ≠ approved={self._approved_ip}"
            )

        # 创建socket
        sock = socket.socket(family, socktype, proto)
        self._captured_socket = sock
        self._socket_created = True

        self._peer_capture_log.append({
            "event": "socket_created",
            "family": family,
            "target_host": target_host,
            "target_port": target_port,
        })

        return sock

    def capture_peer(self) -> str | None:
        """从已捕获的socket提取真实peer IP。

        必须在连接建立后调用。
        返回peer IP字符串，失败返回None。
        """
        if self._captured_socket is None:
            self._peer_capture_log.append({
                "event": "capture_peer_no_socket",
            })
            return None

        try:
            peername = self._captured_socket.getpeername()
            if peername and peername[0]:
                self._peer_ip = peername[0]
                self._peer_capture_log.append({
                    "event": "peer_captured",
                    "peer_ip": self._peer_ip,
                })
                return self._peer_ip
        except (OSError, socket.error) as exc:
            self._peer_capture_log.append({
                "event": "getpeername_failed",
                "error": str(exc),
            })
            return None

        self._peer_capture_log.append({
            "event": "getpeername_empty",
        })
        return None

    def release(self) -> None:
        """释放socket引用（不关闭socket——由aiohttp管理生命周期）。"""
        self._captured_socket = None


# ── RealTransport ─────────────────────────────────────


class RealTransport:
    """真实TCP/TLS Transport — IP固定、无二次DNS、fail-closed。

    遵守TransportProtocol接口，被SafeTransport注入使用。

    V2.0: PUBLIC_PEER_CAPTURE — 使用aiohttp 3.13.5公开socket_factory API。
    不再使用私有连接池属性(_connector/_conns/resp.connection)。
    """

    def __init__(self) -> None:
        self._audit_log: list[dict[str, Any]] = []

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """审计日志（脱敏，不含正文/IP原文/query）。"""
        return list(self._audit_log)

    @staticmethod
    def _make_ssl_context(hostname: str) -> ssl.SSLContext:
        """创建SSL上下文 — 证书链+hostname验证, 禁止verify=False。

        SNI由aiohttp在连接时通过server_hostname参数自动设置。
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    @staticmethod
    def _sanitize_url_for_log(url: str) -> str:
        """日志中只保留scheme://hostname。"""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.hostname}"
        except Exception:
            return "REDACTED"

    @staticmethod
    def _error_result(
        url: str, error_code: str, peer_ip: str = ""
    ) -> dict[str, Any]:
        """构造错误返回dict。"""
        return {
            "status": 0,
            "content_type": "",
            "body": b"",
            "peer_ip": peer_ip,
            "redirect_location": None,
            "content_length": 0,
            "bytes_read": 0,
            "error_code": error_code,
        }

    async def raw_fetch(
        self,
        url: str,
        approved_ip: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_response_bytes: int = 524288,
        user_agent: str = _RT_USER_AGENT,
        trust_env: bool = False,
    ) -> dict[str, Any]:
        """真实TCP/TLS fetch — 连接到approved_ip，无二次DNS。

        V2.0: 使用公开socket_factory API捕获peer，不使用私有连接池属性。
        """

        # ── URL解析 ──
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return self._error_result(url, "ERR_INVALID_URL")
        except Exception:
            return self._error_result(url, "ERR_INVALID_URL")

        scheme = parsed.scheme
        port = parsed.port or (443 if scheme == "https" else 80)

        # 拒绝userinfo
        if parsed.username or parsed.password:
            return self._error_result(url, "ERR_USERINFO_IN_URL")

        # ── 创建单IP解析器 ──
        resolver = _SingleIPResolver(hostname, approved_ip)

        # ── SSL上下文 ──
        ssl_context: ssl.SSLContext | None = None
        if scheme == "https":
            ssl_context = self._make_ssl_context(hostname)

        # ── 创建Peer捕获上下文 (V2.0) ──
        peer_ctx = _PeerCaptureContext(approved_ip)

        peer_ip: str | None = None  # V2.0: filled by peer_ctx after connection
        session: aiohttp.ClientSession | None = None

        try:
            # ── 创建连接器 (V2.0: 使用公开socket_factory) ──
            connector_kwargs: dict[str, Any] = {
                "resolver": resolver,
                "socket_factory": peer_ctx.socket_factory,
            }
            if ssl_context is not None:
                connector_kwargs["ssl"] = ssl_context

            connector = aiohttp.TCPConnector(**connector_kwargs)

            # ── 创建会话 ──
            timeout = aiohttp.ClientTimeout(
                sock_connect=connect_timeout,
                sock_read=read_timeout,
                total=connect_timeout + read_timeout + 1,
            )

            session = aiohttp.ClientSession(
                connector=connector,
                connector_owner=True,  # session关闭时自动关闭connector
                timeout=timeout,
                auto_decompress=False,  # gzip交给SafeTransport
                trust_env=trust_env,
                headers={
                    "User-Agent": user_agent,
                    "Accept-Encoding": "identity",
                },
            )

            # ── 审计: 请求发起 ──
            self._audit_log.append({
                "action": "request_started",
                "url_safe": self._sanitize_url_for_log(url),
            })

            # ── 发起请求 ──
            async with session.get(url, allow_redirects=False) as resp:
                # ── 获取实际peer IP (V2.0: 公开API) ──
                # 通过socket_factory捕获的socket引用，调用公开getpeername()
                peer_ip = peer_ctx.capture_peer()

                if peer_ip is None:
                    self._audit_log.append({
                        "action": "peer_unavailable",
                        "url_safe": self._sanitize_url_for_log(url),
                        "error_code": "ERR_PEER_IP_UNAVAILABLE",
                        "capture_log_entries": len(peer_ctx.capture_log),
                    })
                    return {
                        "status": 0,
                        "content_type": "",
                        "body": b"",
                        "peer_ip": "",
                        "redirect_location": None,
                        "content_length": 0,
                        "bytes_read": 0,
                        "error_code": "ERR_PEER_IP_UNAVAILABLE",
                    }

                # ── 读取响应头 ──
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
                redirect_location = resp.headers.get("Location")

                cl_str = resp.headers.get("Content-Length")
                content_length: int | None = None
                if cl_str is not None:
                    try:
                        content_length = int(cl_str)
                    except ValueError:
                        content_length = None

                # ── Content-Length超限→0字节读取 ──
                if content_length is not None and content_length > max_response_bytes:
                    self._audit_log.append({
                        "action": "content_length_exceeded",
                        "url_safe": self._sanitize_url_for_log(url),
                        "content_length": content_length,
                        "max_bytes": max_response_bytes,
                    })
                    return {
                        "status": status,
                        "content_type": content_type,
                        "body": b"",
                        "peer_ip": peer_ip,
                        "redirect_location": redirect_location,
                        "content_length": content_length,
                        "bytes_read": 0,
                    }

                # ── 分块读取body ──
                body_chunks: list[bytes] = []
                total_read = 0
                limit = max_response_bytes + 1

                async for chunk in resp.content.iter_chunked(8192):
                    total_read += len(chunk)
                    if total_read > limit:
                        excess = total_read - limit
                        body_chunks.append(chunk[:-excess])
                        total_read = limit
                        break
                    body_chunks.append(chunk)

                body = b"".join(body_chunks)
                transport_limit_exceeded = (
                    content_length is None and total_read >= limit
                )

                self._audit_log.append({
                    "action": "fetch_complete",
                    "url_safe": self._sanitize_url_for_log(url),
                    "status": status,
                    "bytes_read": total_read,
                    "resolve_calls": len(resolver.resolve_log),
                    "peer_capture_method": "socket_factory_public_api",
                })

                result: dict[str, Any] = {
                    "status": status,
                    "content_type": content_type,
                    "body": body,
                    "peer_ip": peer_ip,
                    "redirect_location": redirect_location,
                    "content_length": content_length,
                    "bytes_read": total_read,
                }
                if transport_limit_exceeded:
                    result["transport_limit_exceeded"] = True

                return result

        except aiohttp.ClientConnectorCertificateError:
            self._audit_log.append({
                "action": "tls_cert_error",
                "url_safe": self._sanitize_url_for_log(url),
            })
            return self._error_result(url, "ERR_TLS_CERT_VERIFICATION", peer_ip or "")

        except aiohttp.ClientConnectorSSLError:
            self._audit_log.append({
                "action": "tls_hostname_mismatch",
                "url_safe": self._sanitize_url_for_log(url),
            })
            return self._error_result(url, "ERR_TLS_HOSTNAME_MISMATCH", peer_ip or "")

        except asyncio.TimeoutError:
            self._audit_log.append({
                "action": "timeout",
                "url_safe": self._sanitize_url_for_log(url),
            })
            return self._error_result(url, "ERR_TIMEOUT", peer_ip or "")

        except aiohttp.ClientConnectorError:
            self._audit_log.append({
                "action": "connection_error",
                "url_safe": self._sanitize_url_for_log(url),
            })
            return self._error_result(url, "ERR_CONNECTION_FAILED", peer_ip or "")

        except OSError:
            self._audit_log.append({
                "action": "socket_error",
                "url_safe": self._sanitize_url_for_log(url),
            })
            return self._error_result(url, "ERR_SOCKET_ERROR", peer_ip or "")

        except Exception as exc:
            self._audit_log.append({
                "action": "unknown_error",
                "url_safe": self._sanitize_url_for_log(url),
                "exc_type": type(exc).__name__,
            })
            return self._error_result(url, "ERR_UNKNOWN_ERROR", peer_ip or "")

        finally:
            # V2.0: 释放peer捕获上下文的socket引用
            peer_ctx.release()
            if session:
                try:
                    await session.close()
                except Exception:
                    pass
