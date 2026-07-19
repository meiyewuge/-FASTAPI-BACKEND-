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

    def _rollback_to_point(self, db_path: str, rollback_path: str,
                           rollback_sha: str, rollback_counts: Dict[str, int],
                           reason: str, error_code: str,
                           reconnect_count: int, extra: Optional[dict] = None) -> dict:
        """R2a P0 + R2b: 统一的 post-replace 回滚流程 —— 条件为假与异常两类失败共用同一
        事务，避免两套回滚代码漂移。恢复 rollback point → 清理 sidecar → 重连 Repository →
        复验 rollback SHA/counts/integrity/FK → R2b: 4条件全部为真才 rollback_restored=True。
        **永不裸抛异常**，回滚成功时绝不留下 repo.conn=None。"""
        result = {'restored': False, 'error': reason, 'error_code': error_code,
                  'exception_escaped': False}
        if extra:
            result.update(extra)
        # 关闭任何部分创建的新连接
        try:
            if self._repo.conn is not None:
                self._repo.conn.close()
        except Exception:
            pass
        self._repo.conn = None
        # 用 rollback point 恢复原库
        try:
            os.replace(rollback_path, db_path)
        except OSError as rb_err:
            result['error'] = f'{reason}; rollback replace failed: {type(rb_err).__name__}: {rb_err}'
            result['error_code'] = 'E-RESTORE-ROLLBACK-FAILED'
            result['rollback_restored'] = False
            result['repo_conn_alive'] = False
            result['reconnect_count'] = reconnect_count
            return result
        # R2b: 清理 failed new DB 残留的 WAL/SHM sidecar 文件，防止 WAL replay 修改恢复后的
        # rollback point。只清理 db_path 的 sidecar（db_path + '-wal' / db_path + '-shm'），
        # 不使用通配符，不会影响同目录下其他 DB 的 sidecar 文件。
        # 时机：os.replace(rollback→db) 之后、_connect(db) 之前。
        for ext in ('-wal', '-shm'):
            sidecar = db_path + ext
            try:
                if os.path.exists(sidecar):
                    os.unlink(sidecar)
            except OSError:
                pass
        # 重连 Repository
        try:
            self._repo.conn = self._repo._connect(db_path)
            reconnect_count += 1
        except Exception as rc_err:
            result['error'] = f'{reason}; rolled back but reconnect failed: {type(rc_err).__name__}: {rc_err}'
            result['error_code'] = 'E-RESTORE-ROLLBACK-FAILED'
            result['rollback_restored'] = False
            result['repo_conn_alive'] = False
            result['reconnect_count'] = reconnect_count
            return result
        # 验证 rollback point 已恢复且连接可查询
        try:
            rb_verify_sha = _sha256_file(db_path)
            rb_integrity = self._repo.conn.execute("PRAGMA integrity_check").fetchone()[0]
            rb_fk = self._repo.conn.execute("PRAGMA foreign_keys").fetchone()[0]
            rb_verify_counts = _count_all_tables(self._repo.conn)
        except Exception as v_err:
            result['error'] = f'{reason}; rolled back but verify failed: {type(v_err).__name__}: {v_err}'
            result['error_code'] = 'E-RESTORE-ROLLBACK-FAILED'
            result['rollback_restored'] = False
            result['repo_conn_alive'] = False
            result['reconnect_count'] = reconnect_count
            return result
        # R2b: rollback 复验硬执法 —— 4条件全部为真才 rollback_restored=True
        rollback_conditions = {
            'sha_match': rb_verify_sha == rollback_sha,
            'counts_match': rb_verify_counts == rollback_counts,
            'integrity_ok': rb_integrity == 'ok',
            'fk_on': rb_fk == 1,
        }
        rollback_failed = [k for k, v in rollback_conditions.items() if not v]
        result['reconnect_count'] = reconnect_count
        result['rollback_sha'] = rb_verify_sha
        result['rollback_counts'] = rb_verify_counts
        result['rollback_sha_match'] = rollback_conditions['sha_match']
        result['rollback_counts_match'] = rollback_conditions['counts_match']
        result['rollback_integrity'] = rb_integrity
        result['rollback_fk'] = rb_fk
        result['rollback_conditions'] = rollback_conditions
        result['rollback_failed'] = rollback_failed
        if all(rollback_conditions.values()):
            result['rollback_restored'] = True
            result['repo_conn_alive'] = True
        else:
            result['rollback_restored'] = False
            result['repo_conn_alive'] = True
            result['error_code'] = 'E-RESTORE-ROLLBACK-FAILED'
            result['error'] = f'{reason}; rollback verification failed: {rollback_failed}'
        return result

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
        _rb_fd, rollback_path = tempfile.mkstemp(suffix='.rollback', dir=db_parent)
        os.close(_rb_fd)  # S0-1: close mkstemp fd explicitly (no leaked descriptor)
        rollback_ok = False
        rollback_sha = ''
        rollback_counts = {}
        try:
            # WAL checkpoint — S0-2: read (busy, log, checkpointed); busy!=0 hard-blocks
            # BEFORE closing/replacing. Empty/None/exception -> fail-closed. (0,0,0) is
            # valid (no busy readers, nothing to checkpoint) and must NOT be a failure.
            _cp_row = self._repo.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if _cp_row is None or len(_cp_row) < 1:
                raise RuntimeError('wal_checkpoint returned no/empty result')
            _cp_busy = _cp_row[0]
            if _cp_busy != 0:
                try:
                    if os.path.exists(rollback_path): os.unlink(rollback_path)
                except OSError:
                    pass
                return {'restored': False,
                        'error': f'wal_checkpoint busy={_cp_busy}; aborted before close/replace',
                        'error_code': 'E-RESTORE-CHECKPOINT', 'reconnect_count': 0,
                        'repo_conn_alive': True, 'checkpoint_busy': _cp_busy}
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
            # R2a 2.2: candidate 的第一次 replace 失败发生在触碰原库之前。按 os.replace
            # 原子语义原库应仍在原处。**不无条件声称 rollback_restored=True**；重新连接并
            # 复验原库，报告 original_untouched；无法验证则 fail-closed。
            try:
                self._repo.conn = self._repo._connect(db_path)
                reconnect_count = 1
                orig_sha = _sha256_file(db_path)
                orig_integrity = self._repo.conn.execute("PRAGMA integrity_check").fetchone()[0]
                orig_counts = _count_all_tables(self._repo.conn)
                original_untouched = (orig_sha == rollback_sha
                                      and orig_integrity == 'ok'
                                      and orig_counts == rollback_counts)
                try:
                    if os.path.exists(rollback_path):
                        os.unlink(rollback_path)
                except OSError:
                    pass
                return {'restored': False,
                        'error': f'atomic replace failed: {type(e).__name__}: {e}',
                        'error_code': 'E-RESTORE-REPLACE',
                        'reconnect_count': reconnect_count,
                        'rollback_restored': False,
                        'original_untouched': original_untouched,
                        'repo_conn_alive': True,
                        'orig_sha': orig_sha,
                        'orig_integrity': orig_integrity,
                        'exception_escaped': False}
            except Exception as verr:
                # fail-closed: 原库无法验证
                self._repo.conn = None
                return {'restored': False,
                        'error': f'atomic replace failed and original re-verify failed: '
                                 f'{type(e).__name__}: {e}; {type(verr).__name__}: {verr}',
                        'error_code': 'E-RESTORE-REPLACE',
                        'reconnect_count': reconnect_count,
                        'rollback_restored': False,
                        'original_untouched': False,
                        'repo_conn_alive': False,
                        'exception_escaped': False}

        # === 步骤5: 验证新库 — R2a P0: 连接/验证/条件判定全部纳入统一异常回滚保护 ===
        # 从 os.replace(candidate) 成功开始，_connect / integrity / fk / counts / sha /
        # 条件计算中任一抛异常或返回失败，都必须进入 _rollback_to_point 同一回滚流程。
        # 异常不得裸抛，绝不留下 repo.conn=None。
        # S0-1: rollback 文件在全部条件通过前始终保留，仅成功路径删除。
        reconnect_count = 0
        try:
            new_conn = self._repo._connect(db_path)
            self._repo.conn = new_conn
            reconnect_count = 1

            new_integrity = new_conn.execute("PRAGMA integrity_check").fetchone()[0]
            new_fk = new_conn.execute("PRAGMA foreign_keys").fetchone()[0]
            new_counts = _count_all_tables(new_conn)
            new_sha = _sha256_file(db_path)

            conditions = {
                'integrity_ok': new_integrity == 'ok',
                'fk_on': new_fk == 1,
                'sha_match': new_sha == recheck_sha,
                'counts_match': new_counts == candidate_counts,
            }

            if not all(conditions.values()):
                failed = [k for k, v in conditions.items() if not v]
                return self._rollback_to_point(
                    db_path, rollback_path, rollback_sha, rollback_counts,
                    reason=f'success conditions failed: {failed}',
                    error_code='E-RESTORE-VERIFY',
                    reconnect_count=reconnect_count,
                    extra={
                        'conditions': conditions,
                        'new_integrity': new_integrity,
                        'new_fk': new_fk,
                        'new_sha': new_sha,
                        'expected_sha': recheck_sha,
                        'new_counts': new_counts,
                        'expected_counts': candidate_counts,
                    })
        except Exception as e:
            # post-replace 连接或验证本身抛异常 → 统一回滚，绝不逃逸
            return self._rollback_to_point(
                db_path, rollback_path, rollback_sha, rollback_counts,
                reason=f'post-replace exception during {type(e).__name__}: {e}',
                error_code='E-RESTORE-POST-REPLACE',
                reconnect_count=reconnect_count,
                extra={'exception_type': type(e).__name__})

        # S0-1: all conditions passed — NOW delete rollback. A delete failure is a
        # controlled cleanup error; it never turns success into failure, nor hides
        # a failure as success.
        cleanup_error = None
        try:
            if os.path.exists(rollback_path):
                os.unlink(rollback_path)
        except OSError as ce:
            cleanup_error = f'{type(ce).__name__}: {ce}'
        return {
            'restored': True,
            'candidate_sha_matched': True,
            'new_integrity': new_integrity,
            'new_fk': new_fk,
            'new_sha': new_sha,
            'new_counts': new_counts,
            'reconnect_count': reconnect_count,
            'rollback_restored': False,
            'cleanup_error': cleanup_error,
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
