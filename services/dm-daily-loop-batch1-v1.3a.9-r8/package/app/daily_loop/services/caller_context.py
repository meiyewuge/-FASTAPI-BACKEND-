#!/usr/bin/env python3
"""
CallerContext V1.3A.9 — tamper-evident claims + token生命周期。

关键变更:
1. token包含issued_at/expires_at/token_id/audience
2. MAC覆盖全部claims的规范化序列
3. verify()检查MAC+audience+时间+token_id+查库status=active+store/role一致
4. StoreMember TTL默认300秒, 可测试注入
5. 删除create_platform() — 移到PlatformRecoveryProvider
"""
from __future__ import annotations
from typing import Optional
import sqlite3
import hmac
import os
import hashlib
import uuid
import time


class CallerContext:
    """tamper-evident可信上下文。携带claims + MAC token + 生命周期。"""

    __slots__ = ('_member_id', '_store_id', '_role', '_audience', '_issued_at',
                 '_expires_at', '_token_id', '_token', '_frozen')

    def __init__(self, member_id: str, store_id: str, role: str,
                 audience: str = '', issued_at: float = 0, expires_at: float = 0,
                 token_id: str = '', token: bytes = b''):
        self._member_id = member_id
        self._store_id = store_id
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
            raise AttributeError(f'CallerContext is tamper-evident: cannot modify {name}')
        else:
            object.__setattr__(self, name, value)

    @property
    def member_id(self) -> str: return self._member_id
    @property
    def store_id(self) -> str: return self._store_id
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
    @property
    def is_system(self) -> bool: return self._role == 'system'
    @property
    def can_read_vault(self) -> bool:
        return self._role in ('owner', 'manager') and not self.is_system

    def __repr__(self):
        return (f'CallerContext(member_id={self._member_id!r}, store_id={self._store_id!r}, '
                f'role={self._role!r}, audience={self._audience!r}, token_id={self._token_id!r})')


def _canonical_claims(member_id, store_id, role, audience, issued_at, expires_at, token_id):
    """规范化claims序列用于MAC"""
    return f'{member_id}|{store_id}|{role}|{audience}|{issued_at:.6f}|{expires_at:.6f}|{token_id}'.encode()


class TrustedMemberProvider:
    """从 auth_user_id + target_store_id 解析可信 CallerContext。
    独立签名根，不与platform recovery共享。"""

    _clock = staticmethod(time.time)
    DEFAULT_TTL = 300  # StoreMember默认TTL 300秒
    MAX_TTL = 300  # 业务TTL硬上限, 不可超过
    AUDIENCE = 'dm_vault_business_v1'

    def __init__(self, auth_db_path: str, signing_key: bytes, ttl: float = None):
        self._auth_db_path = auth_db_path
        self._signing_key = signing_key
        self._ttl = min(ttl if ttl is not None else self.DEFAULT_TTL, self.MAX_TTL)

    @classmethod
    def from_env(cls, auth_db_path: str, ttl: float = None, clock=None) -> 'TrustedMemberProvider':
        signing_key = os.environ.get('DM_CALLER_SIGNING_KEY')
        if not signing_key or len(signing_key) < 16 or signing_key.startswith('dev_'):
            import sys
            sys.stderr.write('DM_CALLER_SIGNING_KEY missing, too short, or dev fallback\n')
            raise SystemExit(2)
        provider = cls(auth_db_path, hashlib.scrypt(signing_key.encode(), salt=b'dm_caller_signing', n=16384, r=8, p=1, dklen=32), ttl)
        if clock is not None:
            provider._clock = clock
        return provider

    def create(self, auth_user_id: str, target_store_id: str, ttl_seconds: float = None) -> CallerContext:
        conn = sqlite3.connect(self._auth_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT member_id, store_id, role, status FROM dl_store_member "
            "WHERE auth_user_id=? AND store_id=? AND status='active'",
            (auth_user_id, target_store_id)).fetchone()
        conn.close()
        if not row:
            return CallerContext('', '', '', self.AUDIENCE, 0, 0, '', b'')

        member_id = row['member_id']
        store_id = row['store_id']
        role = row['role']
        now = self._clock()
        issued_at = now
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        ttl = min(ttl, self.MAX_TTL)  # 强制截断
        expires_at = now + ttl
        token_id = uuid.uuid4().hex
        claims = _canonical_claims(member_id, store_id, role, self.AUDIENCE, issued_at, expires_at, token_id)
        token = hmac.new(self._signing_key, claims, hashlib.sha256).digest()
        return CallerContext(member_id, store_id, role, self.AUDIENCE, issued_at, expires_at, token_id, token)

    def create_system(self, service_principal: str, service_secret: str) -> CallerContext:
        expected_secret = os.environ.get('DM_SERVICE_PRINCIPAL_SECRET')
        if not expected_secret or service_principal != 'daily_loop_orchestrator':
            return CallerContext('', '', '', self.AUDIENCE, 0, 0, '', b'')
        if not hmac.compare_digest(service_secret, expected_secret):
            return CallerContext('', '', '', self.AUDIENCE, 0, 0, '', b'')
        now = self._clock()
        issued_at = now
        expires_at = now + self._ttl
        token_id = uuid.uuid4().hex
        claims = _canonical_claims('SYSTEM', '', 'system', self.AUDIENCE, issued_at, expires_at, token_id)
        token = hmac.new(self._signing_key, claims, hashlib.sha256).digest()
        return CallerContext('SYSTEM', '', 'system', self.AUDIENCE, issued_at, expires_at, token_id, token)

    def verify(self, ctx: CallerContext) -> bool:
        """验证Context: MAC + audience + 时间 + token_id + 查库"""
        if not ctx.token or not ctx.token_id:
            return False
        if ctx.audience != self.AUDIENCE:
            return False
        now = self._clock()
        if not (ctx.issued_at <= now < ctx.expires_at):
            return False
        # MAC验证
        claims = _canonical_claims(ctx.member_id, ctx.store_id, ctx.role, ctx.audience,
                                   ctx.issued_at, ctx.expires_at, ctx.token_id)
        expected = hmac.new(self._signing_key, claims, hashlib.sha256).digest()
        if not hmac.compare_digest(ctx.token, expected):
            return False
        # 查库: StoreMember仍存在且status=active + store/role一致
        if ctx.role == 'system':
            return True  # system不查库
        conn = sqlite3.connect(self._auth_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT member_id, store_id, role, status FROM dl_store_member "
            "WHERE member_id=? AND store_id=? AND status='active'",
            (ctx.member_id, ctx.store_id)).fetchone()
        conn.close()
        if not row:
            return False
        if row['role'] != ctx.role:
            return False
        return True

    def authorize(self, action: str, ctx: CallerContext, target_store_id: str = '') -> bool:
        if not self.verify(ctx):
            return False
        if ctx.role in ('staff', 'system'):
            return False
        if action == 'read':
            if not target_store_id or ctx.store_id != target_store_id:
                return False
            return ctx.role in ('owner', 'manager')
        if action == 'write':
            if not target_store_id or ctx.store_id != target_store_id:
                return False
            return ctx.role in ('owner', 'manager')
        if action == 'rotate':
            if not target_store_id or ctx.store_id != target_store_id:
                return False
            return ctx.role == 'owner'
        if action == 'export':
            if not target_store_id or ctx.store_id != target_store_id:
                return False
            return ctx.role == 'owner'
        return False
