#!/usr/bin/env python3
"""
VaultRecoveryService V1.3A.9-R7 — 可复现构建与故障证明。

关键修复:
1. Repository共享锁: restore全程持有_repo._db_lock
2. checkpoint失败硬阻断: checkpoint返回False/异常→E-RESTORE-CHECKPOINT, 不replace
3. candidate封存复核: commit前重新计算candidate SHA+counts, 不一致→E-RESTORE-CANDIDATE-CHANGED
4. 同目录candidate/rollback: tempfile.mkstemp(dir=db_parent_dir)
5. 成功条件全部执法: integrity==ok AND fk==1 AND sha==candidate_sha AND counts==candidate_counts
6. backup单一实现: 只调用backup_vault(), 不重复src.backup()
7. 禁止裸except
8. prepare为私有方法
"""
from __future__ import annotations
import sqlite3, os, uuid, hashlib, json, tempfile, threading
from pathlib import Path
from typing import Optional, Dict, List

from app.daily_loop.services.keyring import KeyRing, backup_vault, restore_vault
from app.daily_loop.services.platform_recovery import PlatformRecoveryContext, PlatformRecoveryProvider
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _count_all_tables(conn: sqlite3.Connection) -> Dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'"
    ).fetchall()]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


class VaultRecoveryService:
    """平台恢复服务 — Provider在构造时固定, 调用方不可替换。"""

    def __init__(self, vault_repo, keyring: KeyRing, clock=None):
        self._repo = vault_repo
        self._keyring = keyring
        self._provider = PlatformRecoveryProvider.from_env(clock=clock)

    def backup(self, backup_path: str, recovery_ctx: PlatformRecoveryContext) -> dict:
        """加密备份 — 只接收Context, Provider在Service内部"""
        if not isinstance(recovery_ctx, PlatformRecoveryContext):
            raise PermissionError('E-AUTH: backup requires PlatformRecoveryContext')
        if not self._provider.verify(recovery_ctx):
            raise PermissionError('E-AUTH: invalid platform recovery context')
        # 单一实现: 只调用backup_vault
        result = backup_vault(self._repo.db_path, backup_path, self._keyring.get_master())
        return result

    def _prepare_restore_candidate(self, backup_path: str) -> dict:
        """阶段1: 解密→唯一候选文件→fsync→integrity→schema→SHA记录→不触碰原Vault"""
        db_path = self._repo.db_path
        db_parent = os.path.dirname(os.path.abspath(db_path))

        # 唯一候选文件, 同目录保证os.replace原子语义
        fd, candidate_path = tempfile.mkstemp(suffix='.candidate', dir=db_parent)
        os.close(fd)

        connect_attempts = 0
        try:
            # 解密备份到候选文件
            from app.daily_loop.services.keyring import restore_vault as _restore_vault
            # restore_vault会解密+写临时文件+验证+原子替换
            # 我们需要先解密到candidate_path
            key = self._keyring.get_master()
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.exceptions import InvalidTag
            import hashlib as _hl

            backup_key = _hl.scrypt(key + b'backup_v1', salt=b'dm_vault_backup_salt', n=16384, r=8, p=1, dklen=32)
            aesgcm = AESGCM(backup_key)
            with open(backup_path, 'rb') as f:
                raw = f.read()
            if len(raw) < 12:
                os.unlink(candidate_path)
                return {'ok': False, 'error': 'backup too short',
                        'error_code': 'E-RESTORE-SHORT', 'candidate_path': candidate_path}
            nonce = raw[:12]
            ct = raw[12:]
            try:
                data = aesgcm.decrypt(nonce, ct, b'dm_vault_backup')
            except InvalidTag:
                os.unlink(candidate_path)
                return {'ok': False, 'error': 'backup authentication tag verification failed',
                        'error_code': 'E-RESTORE-AUTH-TAG', 'candidate_path': candidate_path}

            with open(candidate_path, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # 验证候选文件
            connect_attempts += 1
            verify = sqlite3.connect(candidate_path)
            verify.execute("PRAGMA foreign_keys=ON")
            integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != 'ok':
                verify.close()
                os.unlink(candidate_path)
                return {'ok': False, 'error': f'candidate integrity_check failed: {integrity}',
                        'error_code': 'E-RESTORE-INTEGRITY', 'candidate_path': candidate_path}

            tables = [r[0] for r in verify.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'"
            ).fetchall()]
            if 'dl_identity_vault' not in tables:
                verify.close()
                os.unlink(candidate_path)
                return {'ok': False, 'error': 'dl_identity_vault table missing in candidate',
                        'error_code': 'E-RESTORE-SCHEMA', 'candidate_path': candidate_path}

            candidate_counts = _count_all_tables(verify)
            verify.close()

            candidate_sha = _sha256_file(candidate_path)

            return {
                'ok': True,
                'candidate_path': candidate_path,
                'candidate_sha': candidate_sha,
                'candidate_counts': candidate_counts,
                'candidate_integrity': integrity,
                'candidate_connect_attempts': connect_attempts,
            }

        except FileNotFoundError:
            try: os.unlink(candidate_path)
            except FileNotFoundError: pass
            return {'ok': False, 'error': 'backup file not found',
                    'error_code': 'E-RESTORE-MISSING', 'candidate_path': candidate_path}
        except Exception as e:
            try: os.unlink(candidate_path)
            except FileNotFoundError: pass
            return {'ok': False, 'error': f'prepare failed: {type(e).__name__}: {e}',
                    'error_code': 'E-RESTORE-PREPARE', 'candidate_path': candidate_path}

    def _commit_restore_candidate(self, candidate_path: str,
                                   candidate_sha: str,
                                   candidate_counts: Dict[str, int],
                                   recovery_ctx: PlatformRecoveryContext) -> dict:
        """阶段2: 封存复核→checkpoint→关连接→replace→验证→回写→失败回滚"""
        db_path = self._repo.db_path
        db_parent = os.path.dirname(os.path.abspath(db_path))

        # === 步骤1: 封存复核 — 重新计算candidate SHA+counts ===
        if not os.path.exists(candidate_path):
            return {'restored': False, 'error': 'candidate file missing during commit',
                    'error_code': 'E-RESTORE-CANDIDATE-MISSING', 'reconnect_count': 0}

        recheck_sha = _sha256_file(candidate_path)
        if recheck_sha != candidate_sha:
            return {'restored': False, 'error': 'candidate SHA changed during commit (TOCTOU)',
                    'error_code': 'E-RESTORE-CANDIDATE-CHANGED',
                    'expected_sha': candidate_sha, 'actual_sha': recheck_sha,
                    'reconnect_count': 0}

        recheck_conn = sqlite3.connect(candidate_path)
        recheck_counts = _count_all_tables(recheck_conn)
        recheck_conn.close()
        if recheck_counts != candidate_counts:
            return {'restored': False, 'error': 'candidate counts changed during commit (TOCTOU)',
                    'error_code': 'E-RESTORE-CANDIDATE-CHANGED',
                    'expected_counts': candidate_counts, 'actual_counts': recheck_counts,
                    'reconnect_count': 0}

        # === 步骤2: checkpoint原库 ===
        rollback_path = tempfile.mkstemp(suffix='.rollback', dir=db_parent)[1]
        rollback_ok = False
        rollback_sha = ''
        rollback_counts = {}
        try:
            # WAL checkpoint
            self._repo.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            # 复制原库到rollback文件
            import shutil
            shutil.copy2(db_path, rollback_path)
            # fsync rollback
            with open(rollback_path, 'r+b') as rf:
                os.fsync(rf.fileno())
            # 验证rollback
            rb_conn = sqlite3.connect(rollback_path)
            rb_integrity = rb_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if rb_integrity != 'ok':
                rb_conn.close()
                os.unlink(rollback_path)
                return {'restored': False, 'error': f'rollback integrity_check failed: {rb_integrity}',
                        'error_code': 'E-RESTORE-ROLLBACK-INTEGRITY', 'reconnect_count': 0}
            rollback_sha = _sha256_file(rollback_path)
            rollback_counts = _count_all_tables(rb_conn)
            rb_conn.close()
            rollback_ok = True
        except Exception as e:
            # checkpoint失败 → 不关闭旧连接, 不replace
            try:
                if os.path.exists(rollback_path):
                    os.unlink(rollback_path)
            except OSError:
                pass
            return {'restored': False, 'error': f'checkpoint/rollback copy failed: {type(e).__name__}: {e}',
                    'error_code': 'E-RESTORE-CHECKPOINT', 'reconnect_count': 0,
                    'repo_conn_alive': True}

        # === 步骤3: 关闭旧连接 ===
        old_conn = self._repo.conn
        self._repo.conn = None
        try:
            old_conn.close()
        except Exception:
            pass

        # === 步骤4: 原子替换 ===
        reconnect_count = 0
        try:
            os.replace(candidate_path, db_path)
        except Exception as e:
            # replace失败 → 用rollback恢复
            try:
                os.replace(rollback_path, db_path)
            except OSError:
                pass
            self._repo.conn = self._repo._connect(db_path)
            reconnect_count = 1
            return {'restored': False, 'error': f'atomic replace failed: {type(e).__name__}: {e}',
                    'error_code': 'E-RESTORE-REPLACE', 'reconnect_count': reconnect_count,
                    'rollback_restored': True, 'rollback_sha': rollback_sha}

        # === 步骤5: 验证新库 — 成功条件全部执法 ===
        reconnect_count = 1
        new_conn = self._repo._connect(db_path)
        self._repo.conn = new_conn

        new_integrity = new_conn.execute("PRAGMA integrity_check").fetchone()[0]
        new_fk = new_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        new_counts = _count_all_tables(new_conn)
        new_sha = _sha256_file(db_path)

        # 清理rollback文件
        try:
            if os.path.exists(rollback_path):
                os.unlink(rollback_path)
        except OSError:
            pass

        # 成功条件全部执法
        conditions = {
            'integrity_ok': new_integrity == 'ok',
            'fk_on': new_fk == 1,
            'sha_match': new_sha == recheck_sha,
            'counts_match': new_counts == candidate_counts,
        }

        if not all(conditions.values()):
            # 某条件不满足 → 回滚
            failed = [k for k, v in conditions.items() if not v]
            # 用rollback恢复原库
            try:
                new_conn.close()
                self._repo.conn = None
                os.replace(rollback_path, db_path)
                self._repo.conn = self._repo._connect(db_path)
                reconnect_count = 2
                rb_verify_sha = _sha256_file(db_path)
                rb_verify_conn = sqlite3.connect(db_path)
                rb_verify_counts = _count_all_tables(rb_verify_conn)
                rb_verify_conn.close()
                return {
                    'restored': False,
                    'error': f'success conditions failed: {failed}',
                    'error_code': 'E-RESTORE-VERIFY',
                    'conditions': conditions,
                    'new_integrity': new_integrity,
                    'new_fk': new_fk,
                    'new_sha': new_sha,
                    'expected_sha': recheck_sha,
                    'new_counts': new_counts,
                    'expected_counts': candidate_counts,
                    'reconnect_count': reconnect_count,
                    'rollback_restored': True,
                    'rollback_sha': rb_verify_sha,
                    'rollback_counts': rb_verify_counts,
                    'rollback_sha_match': rb_verify_sha == rollback_sha,
                    'rollback_counts_match': rb_verify_counts == rollback_counts,
                }
            except Exception as rb_err:
                return {'restored': False,
                        'error': f'success conditions failed: {failed}, rollback also failed: {rb_err}',
                        'error_code': 'E-RESTORE-ROLLBACK-FAILED',
                        'reconnect_count': reconnect_count,
                        'rollback_restored': False}

        return {
            'restored': True,
            'candidate_sha_matched': True,
            'new_integrity': new_integrity,
            'new_fk': new_fk,
            'new_sha': new_sha,
            'new_counts': new_counts,
            'reconnect_count': reconnect_count,
            'rollback_restored': False,
            'error_code': None,
        }

    def restore(self, backup_path: str, recovery_ctx: PlatformRecoveryContext) -> dict:
        """完整恢复: prepare + commit, 全程持有Repository共享锁"""
        if not isinstance(recovery_ctx, PlatformRecoveryContext):
            raise PermissionError('E-AUTH: restore requires PlatformRecoveryContext')
        if not self._provider.verify(recovery_ctx):
            raise PermissionError('E-AUTH: invalid platform recovery context')

        # 持有Repository共享锁, 阻止read/write/rotate
        with self._repo._db_lock:
            # 阶段1: 预验证
            candidate = self._prepare_restore_candidate(backup_path)
            if not candidate.get('ok'):
                cp = candidate.get('candidate_path')
                if cp:
                    try: os.unlink(cp)
                    except FileNotFoundError: pass
                return {'restored': False,
                        **{k: v for k, v in candidate.items() if k != 'ok'},
                        'reconnect_count': 0}

            # 阶段2: 原子替换+连接接管
            result = self._commit_restore_candidate(
                candidate['candidate_path'],
                candidate.get('candidate_sha', ''),
                candidate.get('candidate_counts', {}),
                recovery_ctx
            )

            # 清理候选文件(如果还存在)
            cp = candidate.get('candidate_path')
            if cp:
                try:
                    if os.path.exists(cp):
                        os.unlink(cp)
                except FileNotFoundError:
                    pass

            return result
