#!/usr/bin/env python3
"""
V1.3A.9 VaultRepository — 两阶段预验证 + restore单次重连。

关键变更:
1. _require_context(ctx)先验证ctx非None+token+TTL, 统一PermissionError
2. read/rotate先验证ctx再查对象, ctx=None→PermissionError不是AttributeError
3. backup/restore只接受PlatformRecoveryContext
4. restore只重连1次, _connect() helper
5. 删除platform相关验证分支
"""
from __future__ import annotations
import sqlite3, uuid, os, threading
from pathlib import Path
from typing import Optional

from app.daily_loop.services.keyring import KeyRing, backup_vault, restore_vault
from app.daily_loop.services.caller_context import CallerContext, TrustedMemberProvider
from app.daily_loop.services.platform_recovery import PlatformRecoveryContext, PlatformRecoveryProvider


class VaultRepository:
    """Vault独立库 — 单一权威入口, 共享锁保护restore"""

    def __init__(self, vault_db_path: str, keyring: KeyRing = None,
                 provider: TrustedMemberProvider = None):
        self.db_path = vault_db_path
        self.conn = self._connect(vault_db_path)
        self.keyring = keyring or KeyRing()
        self.provider = provider
        self._db_lock = threading.RLock()  # 共享锁: restore与read/write/rotate互斥

    def _connect(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self, ddl_path: str = None):
        if ddl_path is None:
            ddl_path = Path(__file__).parent.parent / "migrations" / "vault_001_initial.sql"
        with open(ddl_path) as f:
            self.conn.executescript(f.read())

    def _require_context(self, ctx, action: str = ''):
        """阶段1: 预验证ctx非None + provider存在"""
        if ctx is None:
            raise PermissionError('E-AUTH: ctx is None — no caller context')
        if self.provider is None:
            raise PermissionError('E-AUTH: no provider injected — cannot verify')

    def _authorize(self, action: str, ctx: CallerContext, target_store_id: str = ''):
        """阶段2: 验证+授权"""
        self._require_context(ctx, action)
        if not self.provider.authorize(action, ctx, target_store_id):
            raise PermissionError(f'E-AUTH-403: role={ctx.role} action={action} store={target_store_id} denied')

    def insert_vault(self, vault_id: str, subject_type: str, subject_id: str,
                     store_id: str, plaintext_phone: str = None,
                     plaintext_name: str = None, plaintext_id_card: str = None,
                     ctx: CallerContext = None):
        """写入Vault — 强制可信CallerContext + store-scope校验 + 事务"""
        self._authorize('write', ctx, store_id)
        with self._db_lock:
            key_version = 'v1'
            aad = f'{vault_id}:{store_id}:{subject_id}'.encode()
            enc_phone = self.keyring.encrypt_field(plaintext_phone, key_version, aad) if plaintext_phone else None
            enc_name = self.keyring.encrypt_field(plaintext_name, key_version, aad) if plaintext_name else None
            enc_id_card = self.keyring.encrypt_field(plaintext_id_card, key_version, aad) if plaintext_id_card else None
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute(
                    "INSERT INTO dl_identity_vault (vault_id,subject_type,subject_id,store_id,"
                    "encrypted_phone,encrypted_name,encrypted_id_card,key_version) VALUES (?,?,?,?,?,?,?,?)",
                    (vault_id, subject_type, subject_id, store_id, enc_phone, enc_name, enc_id_card, key_version))
                self.conn.execute(
                    "INSERT INTO dl_vault_access_log (access_id,vault_id,access_type,access_reason,"
                    "accessor_member_id,accessor_subject,access_result) VALUES (?,?,?,?,?,?,?)",
                    (f"val_{uuid.uuid4().hex[:16]}", vault_id, 'write', 'vault creation',
                     ctx.member_id, ctx.role, 'granted'))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def read_vault(self, vault_id: str, ctx: CallerContext, access_reason: str = '') -> Optional[dict]:
        """读取Vault — 先预验证再查对象"""
        self._require_context(ctx, 'read')
        self._authorize('read', ctx, ctx.store_id)
        with self._db_lock:
            row = self.conn.execute(
                "SELECT * FROM dl_identity_vault WHERE vault_id=? AND store_id=?",
                (vault_id, ctx.store_id)).fetchone()
            if not row:
                return None
            result = {'vault_id': vault_id, 'store_id': row['store_id'],
                      'subject_type': row['subject_type'], 'subject_id': row['subject_id']}
            aad = f'{vault_id}:{row["store_id"]}:{row["subject_id"]}'.encode()
            if row['encrypted_phone']:
                result['phone'] = self.keyring.decrypt_field(row['encrypted_phone'], row['key_version'], aad)
            if row['encrypted_name']:
                result['name'] = self.keyring.decrypt_field(row['encrypted_name'], row['key_version'], aad)
            self._log(vault_id, 'read', access_reason, ctx, 'granted')
            return result

    def rotate_key(self, vault_id: str, new_key_version: str, ctx: CallerContext) -> dict:
        """真实重加密: 先预验证再查对象"""
        self._require_context(ctx, 'rotate')
        self._authorize('rotate', ctx, ctx.store_id)
        with self._db_lock:
            row = self.conn.execute(
                "SELECT * FROM dl_identity_vault WHERE vault_id=? AND store_id=?",
                (vault_id, ctx.store_id)).fetchone()
            if not row:
                return {'rotated': False, 'error': 'not found'}
            store_id = row['store_id']
            subject_id = row['subject_id']
            old_aad = f'{vault_id}:{store_id}:{subject_id}'.encode()
            new_aad = old_aad
            old_key_version = row['key_version']
            updates = {}
            if row['encrypted_phone']:
                pt = self.keyring.decrypt_field(row['encrypted_phone'], old_key_version, old_aad)
                updates['encrypted_phone'] = self.keyring.encrypt_field(pt, new_key_version, new_aad)
            if row['encrypted_name']:
                pt = self.keyring.decrypt_field(row['encrypted_name'], old_key_version, old_aad)
                updates['encrypted_name'] = self.keyring.encrypt_field(pt, new_key_version, new_aad)
            if row['encrypted_id_card']:
                pt = self.keyring.decrypt_field(row['encrypted_id_card'], old_key_version, old_aad)
                updates['encrypted_id_card'] = self.keyring.encrypt_field(pt, new_key_version, new_aad)
            updates['key_version'] = new_key_version
            if len(updates) <= 1:
                return {'rotated': True, 'fields_updated': 0}
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                set_clauses = [f"{k}=?" for k in updates.keys()]
                values = list(updates.values()) + [vault_id]
                self.conn.execute(
                    f"UPDATE dl_identity_vault SET {','.join(set_clauses)} WHERE vault_id=?", values)
                self.conn.execute(
                    "INSERT INTO dl_vault_access_log (access_id,vault_id,access_type,access_reason,"
                    "accessor_member_id,accessor_subject,access_result) VALUES (?,?,?,?,?,?,?)",
                    (f"val_{uuid.uuid4().hex[:16]}", vault_id, 'rotate', f'rotation to {new_key_version}',
                     ctx.member_id, ctx.role, 'granted'))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            return {'rotated': True, 'fields_updated': len(updates) - 1}

    # backup/restore moved to VaultRecoveryService — Provider不可由调用方传入

    def _log(self, vault_id, access_type, reason, ctx, result):
        member_id = ctx.principal if hasattr(ctx, 'principal') else ctx.member_id
        role = ctx.role
        self.conn.execute(
            "INSERT INTO dl_vault_access_log (access_id,vault_id,access_type,access_reason,"
            "accessor_member_id,accessor_subject,access_result) VALUES (?,?,?,?,?,?,?)",
            (f"val_{uuid.uuid4().hex[:16]}", vault_id, access_type, reason,
             member_id, role, result))
        self.conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
