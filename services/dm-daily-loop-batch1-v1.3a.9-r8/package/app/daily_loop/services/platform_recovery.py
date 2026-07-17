#!/usr/bin/env python3
"""
PlatformRecoveryProvider — 独立签名根, 独立audience, 短TTL。

与TrustedMemberProvider完全隔离:
- 独立DM_PLATFORM_RECOVERY_SIGNING_KEY
- 独立audience: dm_vault_recovery_v1
- 最大TTL 60秒
- StoreMember signing key不能生成或验证platform Context
- platform signing key不能验证StoreMember token
"""
from __future__ import annotations
import os, hmac, hashlib, uuid, time
from typing import Optional


class PlatformRecoveryContext:
    """平台恢复上下文 — 独立于业务身份"""

    __slots__ = ('_principal', '_role', '_audience', '_issued_at',
                 '_expires_at', '_token_id', '_token', '_frozen')

    def __init__(self, principal: str, role: str, audience: str,
                 issued_at: float, expires_at: float, token_id: str, token: bytes):
        self._principal = principal
        self._role = role
        self._audience = audience
        self._issued_at = issued_at
        self._expires_at = expires_at
        self._token_id = token_id
        self._token = token
        self._frozen = True

    def __setattr__(self, name, value):
        if name == '_frozen':
            object.__setattr__(self, name, value)
        elif hasattr(self, '_frozen') and self._frozen:
            raise AttributeError(f'PlatformRecoveryContext is tamper-evident: cannot modify {name}')
        else:
            object.__setattr__(self, name, value)

    @property
    def principal(self) -> str: return self._principal
    @property
    def role(self) -> str: return self._role
    @property
    def audience(self) -> str: return self._audience
    @property
    def issued_at(self) -> float: return self._issued_at
    @property
    def expires_at(self) -> float: return self._expires_at
    @property
    def token_id(self) -> str: return self._token_id
    @property
    def token(self) -> bytes: return self._token


def _canonical_recovery_claims(principal, role, audience, issued_at, expires_at, token_id):
    return f'{principal}|{role}|{audience}|{issued_at:.6f}|{expires_at:.6f}|{token_id}'.encode()


class PlatformRecoveryProvider:
    """平台恢复身份Provider — 独立签名根"""

    _clock = staticmethod(time.time)
    MAX_TTL = 60  # 最大TTL 60秒
    AUDIENCE = 'dm_vault_recovery_v1'

    def __init__(self, signing_key: bytes, ttl: float = None):
        self._signing_key = signing_key
        self._ttl = min(ttl if ttl is not None else self.MAX_TTL, self.MAX_TTL)

    @classmethod
    def from_env(cls, ttl: float = None, clock=None) -> 'PlatformRecoveryProvider':
        signing_key = os.environ.get('DM_PLATFORM_RECOVERY_SIGNING_KEY')
        if not signing_key or len(signing_key) < 16 or signing_key.startswith('dev_'):
            import sys
            sys.stderr.write('DM_PLATFORM_RECOVERY_SIGNING_KEY missing, too short, or dev fallback\n')
            raise SystemExit(2)
        provider = cls(hashlib.scrypt(signing_key.encode(), salt=b'dm_platform_recovery_signing',
                                  n=16384, r=8, p=1, dklen=32), ttl)
        if clock is not None:
            provider._clock = clock
        return provider

    def create(self, principal: str, secret: str) -> PlatformRecoveryContext:
        expected_secret = os.environ.get('DM_PLATFORM_RECOVERY_SECRET')
        if not expected_secret or principal != 'platform_admin':
            return PlatformRecoveryContext('', '', self.AUDIENCE, 0, 0, '', b'')
        if not hmac.compare_digest(secret, expected_secret):
            return PlatformRecoveryContext('', '', self.AUDIENCE, 0, 0, '', b'')
        now = self._clock()
        issued_at = now
        expires_at = now + self._ttl
        token_id = uuid.uuid4().hex
        claims = _canonical_recovery_claims(principal, 'platform_admin', self.AUDIENCE,
                                             issued_at, expires_at, token_id)
        token = hmac.new(self._signing_key, claims, hashlib.sha256).digest()
        return PlatformRecoveryContext(principal, 'platform_admin', self.AUDIENCE,
                                        issued_at, expires_at, token_id, token)

    def verify(self, ctx: PlatformRecoveryContext) -> bool:
        if not ctx.token or not ctx.token_id:
            return False
        if ctx.audience != self.AUDIENCE:
            return False
        now = self._clock()
        if not (ctx.issued_at <= now < ctx.expires_at):
            return False
        claims = _canonical_recovery_claims(ctx.principal, ctx.role, ctx.audience,
                                            ctx.issued_at, ctx.expires_at, ctx.token_id)
        expected = hmac.new(self._signing_key, claims, hashlib.sha256).digest()
        return hmac.compare_digest(ctx.token, expected)
