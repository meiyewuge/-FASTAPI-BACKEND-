"""Trusted-proxy aware client-IP resolution for rate limiting (R2 P1-4).

AUTH_TRUSTED_PROXIES is a comma-separated list of exact IPs and/or CIDR networks
(IPv4 or IPv6). X-Forwarded-For is honored ONLY when the direct peer is inside one
of those networks; the right-most forwarded hop that is not itself a trusted proxy
is taken as the real client. Invalid config raises ValueError so startup can fail
closed. Pair with Uvicorn `--forwarded-allow-ips` restricted to the same proxies.
"""
from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import List, Optional, Union

Network = Union[IPv4Network, IPv6Network]


def parse_trusted_proxies(raw: Optional[str]) -> List[Network]:
    """Parse exact IPs and/or CIDRs into networks. Raises ValueError on any invalid
    token. An exact IP becomes a /32 (v4) or /128 (v6)."""
    nets: List[Network] = []
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        nets.append(ip_network(tok, strict=False))
    return nets


def ip_in_networks(nets: List[Network], value: str) -> bool:
    try:
        ip = ip_address(value)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def client_key(peer: str, forwarded_for: Optional[str], raw_trusted: Optional[str]) -> str:
    """Compute the rate-limit key. On invalid trusted-proxy config, fail closed to
    the peer (never trust a forwarded header)."""
    try:
        nets = parse_trusted_proxies(raw_trusted)
    except ValueError:
        return peer
    if nets and ip_in_networks(nets, peer) and forwarded_for:
        hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
        for ip in reversed(hops):          # right-to-left: strip trusted proxy hops
            if not ip_in_networks(nets, ip):
                return ip
    return peer
