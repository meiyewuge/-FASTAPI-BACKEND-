#!/usr/bin/env python3
"""
离线 KeyRing + 标准AES-GCM AEAD。

使用 cryptography 库的 AESGCM。
- 96-bit随机nonce
- AAD包含vault_id/store_id/subject_id/key_version
- 密钥从环境变量注入，源码零密钥，缺密钥exit 2
"""
from __future__ import annotations
import os, hashlib, hmac, sqlite3, struct
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyRing:
    """AES-GCM密钥环 — 每个版本一个256位密钥"""

    def __init__(self):
        master = os.environ.get('DM_VAULT_MASTER_KEY')
        if not master or len(master) < 16 or master.startswith('dev_'):
            import sys
            sys.stderr.write('DM_VAULT_MASTER_KEY missing, too short, or dev fallback\n')
            raise SystemExit(2)
        self._master = hashlib.scrypt(master.encode(), salt=b'dm_vault_keyring', n=16384, r=8, p=1, dklen=32)

    def get_master(self) -> bytes:
        return self._master

    def get_key(self, key_version: str) -> bytes:
        """派生版本密钥"""
        return hashlib.scrypt(
            self._master + key_version.encode(),
            salt=b'dm_vault_version_salt',
            n=16384, r=8, p=1, dklen=32
        )

    def encrypt_field(self, plaintext: str, key_version: str, aad) -> str:
        """AES-GCM加密字段 — 返回hex(nonce + ciphertext + tag)"""
        key = self.get_key(key_version)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 96-bit nonce
        aad_bytes = aad if isinstance(aad, bytes) else aad.encode('utf-8')
        ct = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), aad_bytes)
        return (nonce + ct).hex()

    def decrypt_field(self, encrypted_hex: str, key_version: str, aad) -> str:
        """AES-GCM解密 — 验证标签"""
        key = self.get_key(key_version)
        aesgcm = AESGCM(key)
        raw = bytes.fromhex(encrypted_hex)
        nonce = raw[:12]
        ct = raw[12:]
        decrypt_aad = aad if isinstance(aad, bytes) else aad.encode('utf-8')
        pt = aesgcm.decrypt(nonce, ct, decrypt_aad)
        return pt.decode('utf-8')


def encrypt(plaintext: bytes, master: bytes, key_version: str, aad: bytes) -> str:
    """模块级加密函数 — 用于truth gate"""
    key = hashlib.scrypt(master + key_version.encode(), salt=b'dm_vault_version_salt', n=16384, r=8, p=1, dklen=32)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return (nonce + ct).hex()


def decrypt(encrypted_hex: str, master: bytes, key_version: str, aad: bytes) -> bytes:
    """模块级解密函数"""
    key = hashlib.scrypt(master + key_version.encode(), salt=b'dm_vault_version_salt', n=16384, r=8, p=1, dklen=32)
    aesgcm = AESGCM(key)
    raw = bytes.fromhex(encrypted_hex)
    nonce = raw[:12]
    ct = raw[12:]
    return aesgcm.decrypt(nonce, ct, aad)


def backup_vault(vault_db_path: str, backup_path: str, master: bytes) -> dict:
    """使用SQLite backup API做一致快照"""
    src = sqlite3.connect(vault_db_path)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src.close()
    # 加密备份文件
    key = hashlib.scrypt(master + b'backup_v1', salt=b'dm_vault_backup_salt', n=16384, r=8, p=1, dklen=32)
    aesgcm = AESGCM(key)
    with open(backup_path, 'rb') as f:
        data = f.read()
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, data, b'dm_vault_backup')
    with open(backup_path, 'wb') as f:
        f.write(nonce + ct)
    return {'backed_up': True, 'backup_path': backup_path, 'size': len(data)}


def restore_vault(backup_path: str, vault_db_path: str, master: bytes) -> dict:
    """从加密备份恢复 — 完整性校验+schema验证"""
    key = hashlib.scrypt(master + b'backup_v1', salt=b'dm_vault_backup_salt', n=16384, r=8, p=1, dklen=32)
    aesgcm = AESGCM(key)
    with open(backup_path, 'rb') as f:
        raw = f.read()
    nonce = raw[:12]
    ct = raw[12:]
    data = aesgcm.decrypt(nonce, ct, b'dm_vault_backup')
    # 写到临时文件
    tmp_path = vault_db_path + '.restore_tmp'
    with open(tmp_path, 'wb') as f:
        f.write(data)
    # 验证恢复的数据库
    verify = sqlite3.connect(tmp_path)
    integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != 'ok':
        verify.close()
        os.unlink(tmp_path)
        raise ValueError(f'integrity_check failed: {integrity}')
    tables = [r[0] for r in verify.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'"
    ).fetchall()]
    if 'dl_identity_vault' not in tables:
        verify.close()
        os.unlink(tmp_path)
        raise ValueError('dl_identity_vault table missing after restore')
    row_count = verify.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
    verify.close()
    # 原子替换
    os.replace(tmp_path, vault_db_path)
    return {'restored': True, 'size': len(data), 'tables_verified': len(tables), 'vault_rows': row_count}
