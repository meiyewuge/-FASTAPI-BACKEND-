#!/usr/bin/env python3
"""
test_restore_fault_injection.py — V1.3A.9-R8-R2B-R1A REAL restore fault injection.

Every fault hits a genuine branch of vault_recovery_service via mock.patch keyed
on the ACTUAL database file (not a call-index guess). R2A adds the two exception
faults that R2 missed (post-replace connect exception, post-replace verification
exception) and strengthens T3/T4/T5 so the candidate (backup, 1 row) and the
rollback point (live DB, 2 rows) are provably DIFFERENT — a rollback that restores
the live 2-row state cannot be faked by "backup == live".

Post-replace cases add V-002 to the LIVE DB after backup, so:
  backup candidate = 1 row (V-001)
  rollback point   = 2 rows (V-001 + V-002)

T1  InvalidTag prevalidation                  -> original DB unchanged
T2  missing backup                            -> original DB unchanged
T3  post-replace foreign_keys OFF             -> verify fail -> rollback restores 2-row snapshot
T4  post-replace SHA mismatch                 -> verify fail -> rollback restores 2-row snapshot
T5  post-replace counts mismatch              -> verify fail -> rollback restores 2-row snapshot
T6  checkpoint busy=1                          -> E-RESTORE-CHECKPOINT, conn alive, NOT replaced
T7  rollback replace itself fails              -> E-RESTORE-ROLLBACK-FAILED, not 'restored'
T8  success path                               -> live 2 rows replaced by backup 1 row; rollback deleted after pass
T9  candidate TOCTOU (SHA changed pre-commit)  -> E-RESTORE-CANDIDATE-CHANGED, original unchanged
T10 post-replace _connect exception            -> E-RESTORE-POST-REPLACE, no escape, rollback restores 2 rows, conn alive
T11 post-replace verification exception        -> E-RESTORE-POST-REPLACE, no escape, rollback restores 2 rows, conn alive

R2B-R1A additions — rollback复验硬执法 (phase-based injection via os.replace wrapper):
T12 rollback SHA mismatch                      -> E-RESTORE-ROLLBACK-FAILED, rollback_restored=False, sha_match=False
T13 rollback counts mismatch                   -> E-RESTORE-ROLLBACK-FAILED, rollback_restored=False, counts_match=False
T14 rollback integrity fail                    -> E-RESTORE-ROLLBACK-FAILED, rollback_restored=False, integrity_ok=False
T15 rollback FK off                            -> E-RESTORE-ROLLBACK-FAILED, rollback_restored=False, fk_on=False

T12-T15 inject faults by wrapping os.replace to detect the rollback phase
(src ends with '.rollback' AND dst == db_path). No call-count guessing.
Each test proves the injection point was hit exactly once.
"""
import unittest, os, sys, tempfile, sqlite3, shutil, json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('DM_VAULT_MASTER_KEY', 'test_master_key_at_least_16_chars_long')
os.environ.setdefault('DM_CALLER_SIGNING_KEY', 'test_signing_key_at_least_16_chars')
os.environ.setdefault('DM_SERVICE_PRINCIPAL_SECRET', 'test_service_secret')
os.environ.setdefault('DM_PLATFORM_RECOVERY_SECRET', 'test_platform_secret_different')
os.environ.setdefault('DM_PLATFORM_RECOVERY_SIGNING_KEY', 'test_recovery_signing_key_16chars')

import app.daily_loop.services.vault_recovery_service as vrs
from app.daily_loop.services.repository import AuthRepository
from app.daily_loop.services.vault_repository import VaultRepository
from app.daily_loop.services.caller_context import TrustedMemberProvider
from app.daily_loop.services.platform_recovery import PlatformRecoveryProvider
from app.daily_loop.services.keyring import KeyRing
from app.daily_loop.services.vault_recovery_service import VaultRecoveryService, _sha256_file, _count_all_tables
from app.daily_loop.models import StoreMember

_FAULT_EVIDENCE = []


def tearDownModule():
    path = os.environ.get('DM_FAULT_EVIDENCE_PATH')
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                'report_type': 'RESTORE_FAULT_INJECTION_REPORT',
                'version': 'V1.3A.9-R8-R2B-R1A',
                'total': len(_FAULT_EVIDENCE),
                'passed': sum(1 for e in _FAULT_EVIDENCE if e.get('passed')),
                'tests': _FAULT_EVIDENCE,
            }, f, indent=2, ensure_ascii=False)


class MockClock:
    def __init__(self): self._t = 1000000.0
    def __call__(self): return self._t
    def advance(self, s): self._t += s


def _conn_main_file(conn):
    try:
        for seq, name, file in conn.execute("PRAGMA database_list").fetchall():
            if name == 'main':
                return os.path.abspath(file) if file else ''
    except Exception:
        return ''
    return ''


class RestoreFaultInjectionTests(unittest.TestCase):

    def setUp(self):
        self.clock = MockClock()
        fd, self.auth_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        arepo = AuthRepository(self.auth_path); arepo.init_schema()
        arepo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='owner', display_alias='M-001', status='active'))
        arepo.close()
        fd, self.vpath = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(self.vpath)
        self.kr = KeyRing()
        self.provider = TrustedMemberProvider.from_env(self.auth_path, clock=self.clock)
        self.recovery_provider = PlatformRecoveryProvider.from_env(clock=self.clock)
        self.vrepo = VaultRepository(self.vpath, self.kr, provider=self.provider)
        self.vrepo.init_schema()
        self.recovery_service = VaultRecoveryService(self.vrepo, self.kr, clock=self.clock)
        self.ctx_owner = self.provider.create('U001', 'S001')
        self.ctx_platform = self.recovery_provider.create('platform_admin', os.environ.get('DM_PLATFORM_RECOVERY_SECRET', ''))
        # backup is taken with ONLY V-001 present (candidate = 1 row)
        self.vrepo.insert_vault(vault_id='V-001', subject_type='customer', subject_id='C-001', store_id='S001', plaintext_phone='13800138000', ctx=self.ctx_owner)
        self.backup_path = self.vpath + '.bak'
        self.recovery_service.backup(self.backup_path, self.ctx_platform)
        self.orig_sha = _sha256_file(self.vpath)
        self.orig_counts = _count_all_tables(self.vrepo.conn)
        self.db_parent = os.path.dirname(os.path.abspath(self.vpath))

    def tearDown(self):
        try: self.vrepo.close()
        except Exception: pass
        for p in [self.auth_path, self.vpath, self.backup_path]:
            try:
                if os.path.exists(p): os.unlink(p)
            except OSError: pass
        for f in os.listdir(self.db_parent):
            if f.endswith('.candidate') or f.endswith('.rollback') or f.endswith('.restore_tmp'):
                try: os.unlink(os.path.join(self.db_parent, f))
                except OSError: pass

    # --- helpers -----------------------------------------------------------

    def _add_live_v002_and_checkpoint(self):
        """After backup (1 row), add V-002 to the LIVE DB so the rollback point
        (2 rows) is provably different from the backup candidate (1 row).
        Checkpoint so the main file reflects 2 rows and its SHA is stable."""
        self.vrepo.insert_vault(vault_id='V-002', subject_type='customer', subject_id='C-002',
                                store_id='S001', plaintext_phone='13800138002', ctx=self.ctx_owner)
        self.vrepo.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return _sha256_file(self.vpath), self._fresh_rows()

    def _fresh_rows(self):
        fresh = sqlite3.connect(self.vpath)
        try:
            return fresh.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
        finally:
            fresh.close()

    def _no_rollback_left(self):
        return not any(f.endswith('.rollback') for f in os.listdir(self.db_parent))

    def _rec(self, test, patch_target, result, before_sha, before_rows, extra=None):
        after_sha = _sha256_file(self.vpath) if os.path.exists(self.vpath) else None
        after_rows = self._fresh_rows() if os.path.exists(self.vpath) else None
        ev = {
            'test': test,
            'patch_target': patch_target,
            'observed_error_code': result.get('error_code'),
            'restored': result.get('restored'),
            'before_sha': before_sha,
            'after_sha': after_sha,
            'before_rows': before_rows,
            'after_rows': after_rows,
            'rollback_restored': result.get('rollback_restored'),
            'rollback_sha': result.get('rollback_sha'),
            'rollback_sha_match': result.get('rollback_sha_match'),
            'rollback_counts': result.get('rollback_counts'),
            'rollback_counts_match': result.get('rollback_counts_match'),
            'repo_conn_alive': result.get('repo_conn_alive'),
            'exception_escaped': result.get('exception_escaped', False),
            'reconnect_count': result.get('reconnect_count'),
            'passed': True,
        }
        if extra: ev.update(extra)
        _FAULT_EVIDENCE.append(ev)

    def _assert_original_intact(self):
        self.assertEqual(_sha256_file(self.vpath), self.orig_sha, 'original DB SHA changed')
        self.assertEqual(self._fresh_rows(), 1, 'original DB row count changed')

    def _assert_rolled_back(self, result, expected_rows):
        """Prove the service rolled the live DB back to the rollback POINT
        (not the backup candidate), reconnected, and the connection is live."""
        self.assertFalse(result.get('exception_escaped', True), f'exception escaped: {result}')
        self.assertTrue(result.get('rollback_restored'), f'rollback not restored: {result}')
        self.assertTrue(result.get('rollback_sha_match'), 'rolled-back DB != rollback snapshot SHA')
        self.assertTrue(result.get('rollback_counts_match'), 'rolled-back DB counts != snapshot')
        self.assertTrue(result.get('repo_conn_alive'), 'repo conn not alive after rollback')
        self.assertEqual(self._fresh_rows(), expected_rows, 'row count wrong after rollback')
        # connection is actually queryable and shows the rolled-back (live) state
        self.assertIsNotNone(self.vrepo.conn, 'repo.conn is None after rollback')
        self.assertEqual(self.vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0],
                         expected_rows, 'repo.conn reports wrong rows after rollback')

    # --- tests -------------------------------------------------------------

    def test_T1_invalid_tag_prevalidation(self):
        before_sha, before_rows = self.orig_sha, 1
        with open(self.backup_path, 'r+b') as f:
            f.seek(-1, 2); f.write(b'\x00')
        result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-AUTH-TAG')
        self._assert_original_intact()
        self._rec('T1_invalid_tag', 'backup byte corruption (prevalidation)', result, before_sha, before_rows)

    def test_T2_missing_backup_file(self):
        before_sha, before_rows = self.orig_sha, 1
        result = self.recovery_service.restore('/nonexistent/backup.bak', self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-MISSING')
        self._assert_original_intact()
        self._rec('T2_missing_backup', 'nonexistent backup path', result, before_sha, before_rows)

    def test_T3_post_replace_fk_off_rollback(self):
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        real_connect = self.vrepo._connect
        seen = {'post_replace': False}
        def fk_off_connect(path):
            conn = real_connect(path)
            if os.path.abspath(path) == os.path.abspath(self.vpath) and not seen['post_replace']:
                seen['post_replace'] = True
                conn.execute("PRAGMA foreign_keys=OFF")
            return conn
        with patch.object(self.vrepo, '_connect', side_effect=fk_off_connect):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'), f'unexpected: {result}')
        self.assertEqual(result.get('error_code'), 'E-RESTORE-VERIFY')
        self.assertFalse(result['conditions']['fk_on'])
        self._assert_rolled_back(result, expected_rows=2)
        self._rec('T3_post_replace_fk_off', 'VaultRepository._connect (post-replace FK=OFF); candidate=1 row, rollback=2 rows',
                  result, before_sha, before_rows,
                  {'failed_conditions': [k for k, v in result['conditions'].items() if not v]})

    def test_T4_post_replace_sha_mismatch_rollback(self):
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        real_sha = vrs._sha256_file
        state = {'db_hits': 0}
        def bad_sha(path):
            if os.path.abspath(path) == os.path.abspath(self.vpath):
                state['db_hits'] += 1
                if state['db_hits'] == 1:
                    return 'deadbeef' * 8
            return real_sha(path)
        with patch.object(vrs, '_sha256_file', side_effect=bad_sha):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-VERIFY')
        self.assertFalse(result['conditions']['sha_match'])
        self._assert_rolled_back(result, expected_rows=2)
        self._rec('T4_post_replace_sha_mismatch', 'vault_recovery_service._sha256_file (post-replace new_sha); candidate=1 row, rollback=2 rows',
                  result, before_sha, before_rows,
                  {'failed_conditions': [k for k, v in result['conditions'].items() if not v]})

    def test_T5_post_replace_counts_mismatch_rollback(self):
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        real_counts = vrs._count_all_tables
        state = {'injected': False}
        def bad_counts(conn):
            if _conn_main_file(conn) == os.path.abspath(self.vpath) and not state['injected']:
                state['injected'] = True
                return {'__injected_table__': 999}
            return real_counts(conn)
        with patch.object(vrs, '_count_all_tables', side_effect=bad_counts):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-VERIFY')
        self.assertFalse(result['conditions']['counts_match'])
        self._assert_rolled_back(result, expected_rows=2)
        self._rec('T5_post_replace_counts_mismatch', 'vault_recovery_service._count_all_tables (post-replace new_counts); candidate=1 row, rollback=2 rows',
                  result, before_sha, before_rows,
                  {'failed_conditions': [k for k, v in result['conditions'].items() if not v]})

    def test_T6_checkpoint_busy_hard_block(self):
        before_sha, before_rows = self.orig_sha, 1
        real_conn = self.vrepo.conn
        class FakeCP:
            def fetchone(self_): return (1, 5, 0)
        class BusyConn:
            def __init__(self, real): self._real = real
            def execute(self, sql, *a):
                if 'wal_checkpoint' in str(sql).lower():
                    return FakeCP()
                return self._real.execute(sql, *a)
            def close(self): self._real.close()
            def commit(self): self._real.commit()
            def rollback(self): self._real.rollback()
            @property
            def row_factory(self): return self._real.row_factory
            @row_factory.setter
            def row_factory(self, v): self._real.row_factory = v
        self.vrepo.conn = BusyConn(real_conn)
        result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.vrepo.conn = real_conn
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-CHECKPOINT')
        self.assertEqual(result.get('checkpoint_busy'), 1)
        self.assertTrue(result.get('repo_conn_alive'))
        self.assertEqual(self.vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0], 1)
        self._assert_original_intact()
        self._rec('T6_checkpoint_busy', 'repo.conn PRAGMA wal_checkpoint -> busy=1', result, before_sha, before_rows,
                  {'checkpoint_busy': result.get('checkpoint_busy')})

    def test_T7_rollback_replace_failure(self):
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        real_connect = self.vrepo._connect
        seen = {'post_replace': False}
        def fk_off_connect(path):
            conn = real_connect(path)
            if os.path.abspath(path) == os.path.abspath(self.vpath) and not seen['post_replace']:
                seen['post_replace'] = True
                conn.execute("PRAGMA foreign_keys=OFF")
            return conn
        real_replace = vrs.os.replace
        calls = {'n': 0}
        def replace_side(src, dst):
            calls['n'] += 1
            if calls['n'] == 1:
                return real_replace(src, dst)
            raise OSError('simulated rollback replace failure')
        with patch.object(self.vrepo, '_connect', side_effect=fk_off_connect), \
             patch.object(vrs.os, 'replace', side_effect=replace_side):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-ROLLBACK-FAILED')
        self.assertFalse(result.get('rollback_restored'))
        self.assertFalse(result.get('exception_escaped', True))
        try: self.vrepo.conn = self.vrepo._connect(self.vpath)
        except Exception: pass
        self._rec('T7_rollback_replace_failure', 'os.replace (2nd call rollback->db raises) + FK off', result, before_sha, before_rows)

    def test_T8_success_rollback_deleted_after_pass(self):
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        self.assertEqual(before_rows, 2, 'live should have 2 rows before restore')
        result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertTrue(result.get('restored'))
        self.assertEqual(result.get('reconnect_count'), 1)
        self.assertIsNone(result.get('cleanup_error'))
        self.assertFalse(result.get('rollback_restored'))
        self.assertTrue(self._no_rollback_left(), 'rollback file should be removed after success')
        # live 2-row DB replaced by 1-row backup candidate -> proves real replacement
        self.assertEqual(self._fresh_rows(), 1, 'restored DB should match 1-row backup')
        self._rec('T8_success_rollback_deleted_after_pass', 'none (success path); live 2 rows -> backup 1 row', result, before_sha, before_rows,
                  {'no_rollback_left': True})

    def test_T9_candidate_toctou(self):
        before_sha, before_rows = self.orig_sha, 1
        candidate = self.recovery_service._prepare_restore_candidate(self.backup_path)
        self.assertTrue(candidate.get('ok'))
        cpath = candidate['candidate_path']
        fd, other = tempfile.mkstemp(suffix='.db'); os.close(fd)
        oc = sqlite3.connect(other); oc.execute("PRAGMA foreign_keys=ON")
        ddl = Path(__file__).parent.parent / 'app' / 'daily_loop' / 'migrations' / 'vault_001_initial.sql'
        with open(ddl) as f: oc.executescript(f.read())
        oc.execute("INSERT INTO dl_identity_vault (vault_id,subject_type,subject_id,store_id,encrypted_phone,encrypted_name,encrypted_id_card,key_version) VALUES (?,?,?,?,?,?,?,?)",
                   ('V-X', 'customer', 'C-X', 'S001', 'e', 'n', None, 'v1'))
        oc.commit(); oc.close()
        shutil.copy2(other, cpath); os.unlink(other)
        result = self.recovery_service._commit_restore_candidate(
            cpath, candidate['candidate_sha'], candidate['candidate_counts'], self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-CANDIDATE-CHANGED')
        self._assert_original_intact()
        self._rec('T9_candidate_toctou', 'candidate file swapped after prepare (pre-commit)', result, before_sha, before_rows)
        try:
            if os.path.exists(cpath): os.unlink(cpath)
        except OSError: pass

    def test_T10_post_replace_connect_exception(self):
        """R2A P0: post-replace _connect raises -> unified rollback, no escape,
        repo.conn stays alive, live 2 rows restored."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        self.assertEqual(before_rows, 2)
        real_connect = self.vrepo._connect
        seen = {'post_replace': False}
        def raising_connect(path):
            if os.path.abspath(path) == os.path.abspath(self.vpath) and not seen['post_replace']:
                seen['post_replace'] = True
                raise sqlite3.OperationalError('INJECTED_POST_REPLACE_CONNECT_FAILURE')
            return real_connect(path)
        escaped = False
        try:
            with patch.object(self.vrepo, '_connect', side_effect=raising_connect):
                result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        except Exception:
            escaped = True
            raise
        self.assertFalse(escaped, 'exception escaped restore()')
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-POST-REPLACE')
        self._assert_rolled_back(result, expected_rows=2)
        self._rec('T10_post_replace_connect_exception',
                  'VaultRepository._connect raises OperationalError at first post-replace connect; candidate=1 row, rollback=2 rows',
                  result, before_sha, before_rows,
                  {'injected_stage': 'post_replace_connect'})

    def test_T11_post_replace_verify_exception(self):
        """R2A P0: reconnect succeeds but a post-replace verification query raises
        -> unified rollback, no escape, conn alive, live 2 rows restored."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        self.assertEqual(before_rows, 2)
        real_counts = vrs._count_all_tables
        state = {'db_hits': 0}
        def raising_counts(conn):
            if _conn_main_file(conn) == os.path.abspath(self.vpath):
                state['db_hits'] += 1
                if state['db_hits'] == 1:
                    raise sqlite3.OperationalError('INJECTED_POST_REPLACE_VERIFY_FAILURE')
            return real_counts(conn)
        escaped = False
        try:
            with patch.object(vrs, '_count_all_tables', side_effect=raising_counts):
                result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        except Exception:
            escaped = True
            raise
        self.assertFalse(escaped, 'exception escaped restore()')
        self.assertFalse(result.get('restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-POST-REPLACE')
        self._assert_rolled_back(result, expected_rows=2)
        self._rec('T11_post_replace_verify_exception',
                  'vault_recovery_service._count_all_tables raises during post-replace verify; candidate=1 row, rollback=2 rows',
                  result, before_sha, before_rows,
                  {'injected_stage': 'post_replace_verify'})

    # === R2B-R1A: rollback复验硬执法 (T12-T15) ===
    # Phase-based injection: wrap os.replace to detect rollback phase.
    # When src ends with '.rollback' AND dst == db_path → phase['rollback_replaced'] = True.
    # No call-count guessing. Each test proves the injection point was hit exactly once.
    #
    # Flow in _rollback_to_point():
    #   1. os.replace(rollback_path, db_path)     ← sets phase['rollback_replaced']=True
    #   2. clean WAL/SHM
    #   3. _connect(db_path)                      ← rollback reconnect
    #   4. _sha256_file(db_path)                  ← rb_verify_sha
    #   5. conn.execute("PRAGMA integrity_check") ← rb_integrity
    #   6. conn.execute("PRAGMA foreign_keys")    ← rb_fk
    #   7. _count_all_tables(conn)                ← rb_verify_counts
    #
    # Trigger: FK off on post-replace _connect (before rollback_replaced) → step5 fails
    # Inject: fault on rollback verification (after rollback_replaced)

    def _make_rollback_phase_wrapper(self):
        """Wrap os.replace to set phase['rollback_replaced']=True when
        src ends with '.rollback' AND dst == db_path. Returns (phase, wrapped_replace)."""
        phase = {'rollback_replaced': False}
        real_replace = vrs.os.replace
        def wrapped_replace(src, dst):
            result = real_replace(src, dst)
            if str(src).endswith('.rollback') and os.path.abspath(dst) == os.path.abspath(self.vpath):
                phase['rollback_replaced'] = True
            return result
        return phase, wrapped_replace

    def _fk_off_pre_rollback_connect(self, real_connect, phase):
        """Return _connect wrapper: FK off for db_path when NOT in rollback phase."""
        def connect(path):
            conn = real_connect(path)
            if os.path.abspath(path) == os.path.abspath(self.vpath) and not phase['rollback_replaced']:
                conn.execute("PRAGMA foreign_keys=OFF")
            return conn
        return connect

    def test_T12_rollback_sha_mismatch(self):
        """R2B-R1A: rollback SHA mismatch — rb_verify_sha != rollback_sha.
        Phase: os.replace wrapper sets rollback_replaced=True; _sha256_file
        returns wrong value only when phase['rollback_replaced'] is True."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        phase, wrapped_replace = self._make_rollback_phase_wrapper()
        real_connect = self.vrepo._connect
        fk_off_connect = self._fk_off_pre_rollback_connect(real_connect, phase)
        real_sha = vrs._sha256_file
        inject_count = {'n': 0}
        def bad_sha(path):
            if os.path.abspath(path) == os.path.abspath(self.vpath) and phase['rollback_replaced']:
                inject_count['n'] += 1
                return 'deadbeef' * 8
            return real_sha(path)
        with patch.object(vrs.os, 'replace', side_effect=wrapped_replace), \
             patch.object(self.vrepo, '_connect', side_effect=fk_off_connect), \
             patch.object(vrs, '_sha256_file', side_effect=bad_sha):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertFalse(result.get('rollback_restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-ROLLBACK-FAILED')
        self.assertTrue(result.get('repo_conn_alive'))
        self.assertTrue(phase['rollback_replaced'], 'rollback phase was never entered')
        self.assertEqual(inject_count['n'], 1, f'SHA fault injected {inject_count["n"]} times, expected 1')
        rb_cond = result.get('rollback_conditions', {})
        self.assertFalse(rb_cond.get('sha_match'))
        self.assertIn('sha_match', result.get('rollback_failed', []))
        self.assertTrue(rb_cond.get('counts_match'))
        self.assertTrue(rb_cond.get('integrity_ok'))
        self.assertTrue(rb_cond.get('fk_on'))
        self.assertEqual(self._fresh_rows(), 2)
        self._rec('T12_rollback_sha_mismatch',
                  'os.replace wrapper detects rollback phase; vrs._sha256_file returns wrong when phase[rollback_replaced]=True',
                  result, before_sha, before_rows,
                  {'rollback_conditions': rb_cond,
                   'rollback_failed': result.get('rollback_failed'),
                   'rollback_integrity': result.get('rollback_integrity'),
                   'rollback_fk': result.get('rollback_fk'),
                   'phase_rollback_replaced': phase['rollback_replaced'],
                   'inject_hits': inject_count['n']})

    def test_T13_rollback_counts_mismatch(self):
        """R2B-R1A: rollback counts mismatch — rb_verify_counts != rollback_counts.
        Phase: os.replace wrapper; _count_all_tables returns wrong when
        phase['rollback_replaced'] is True and conn's main file == db_path."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        phase, wrapped_replace = self._make_rollback_phase_wrapper()
        real_connect = self.vrepo._connect
        fk_off_connect = self._fk_off_pre_rollback_connect(real_connect, phase)
        real_counts = vrs._count_all_tables
        inject_count = {'n': 0}
        def bad_counts(conn):
            if _conn_main_file(conn) == os.path.abspath(self.vpath) and phase['rollback_replaced']:
                inject_count['n'] += 1
                return {'__injected_table__': 999}
            return real_counts(conn)
        with patch.object(vrs.os, 'replace', side_effect=wrapped_replace), \
             patch.object(self.vrepo, '_connect', side_effect=fk_off_connect), \
             patch.object(vrs, '_count_all_tables', side_effect=bad_counts):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertFalse(result.get('rollback_restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-ROLLBACK-FAILED')
        self.assertTrue(result.get('repo_conn_alive'))
        self.assertTrue(phase['rollback_replaced'], 'rollback phase was never entered')
        self.assertEqual(inject_count['n'], 1, f'counts fault injected {inject_count["n"]} times, expected 1')
        rb_cond = result.get('rollback_conditions', {})
        self.assertFalse(rb_cond.get('counts_match'))
        self.assertIn('counts_match', result.get('rollback_failed', []))
        self.assertTrue(rb_cond.get('sha_match'))
        self.assertTrue(rb_cond.get('integrity_ok'))
        self.assertTrue(rb_cond.get('fk_on'))
        self.assertEqual(self._fresh_rows(), 2)
        self._rec('T13_rollback_counts_mismatch',
                  'os.replace wrapper detects rollback phase; vrs._count_all_tables returns wrong when phase[rollback_replaced]=True',
                  result, before_sha, before_rows,
                  {'rollback_conditions': rb_cond,
                   'rollback_failed': result.get('rollback_failed'),
                   'rollback_integrity': result.get('rollback_integrity'),
                   'rollback_fk': result.get('rollback_fk'),
                   'phase_rollback_replaced': phase['rollback_replaced'],
                   'inject_hits': inject_count['n']})

    def test_T14_rollback_integrity_fail(self):
        """R2B-R1A: rollback integrity != ok — rb_integrity returns 'corrupt'.
        Phase: os.replace wrapper; _connect returns BadIntegrityConn when
        phase['rollback_replaced'] is True and path == db_path."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        phase, wrapped_replace = self._make_rollback_phase_wrapper()
        real_connect = self.vrepo._connect
        inject_count = {'n': 0}

        class _BadRow:
            def fetchone(self): return ['corrupt']

        class BadIntegrityConn:
            """Wrapper that intercepts PRAGMA integrity_check, delegates everything else."""
            def __init__(self, real):
                self._real = real
            def execute(self, sql, *a, **kw):
                if 'integrity_check' in str(sql).lower():
                    return _BadRow()
                return self._real.execute(sql, *a, **kw)
            def close(self): self._real.close()
            @property
            def row_factory(self): return self._real.row_factory
            @row_factory.setter
            def row_factory(self, v): self._real.row_factory = v

        def phase_aware_connect(path):
            conn = real_connect(path)
            if os.path.abspath(path) == os.path.abspath(self.vpath):
                if not phase['rollback_replaced']:
                    # Post-replace phase: FK off to trigger step5 failure
                    conn.execute("PRAGMA foreign_keys=OFF")
                else:
                    # Rollback phase: return BadIntegrityConn
                    inject_count['n'] += 1
                    return BadIntegrityConn(conn)
            return conn
        with patch.object(vrs.os, 'replace', side_effect=wrapped_replace), \
             patch.object(self.vrepo, '_connect', side_effect=phase_aware_connect):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertFalse(result.get('rollback_restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-ROLLBACK-FAILED')
        self.assertTrue(result.get('repo_conn_alive'))
        self.assertTrue(phase['rollback_replaced'], 'rollback phase was never entered')
        self.assertEqual(inject_count['n'], 1, f'integrity fault injected {inject_count["n"]} times, expected 1')
        rb_cond = result.get('rollback_conditions', {})
        self.assertFalse(rb_cond.get('integrity_ok'))
        self.assertIn('integrity_ok', result.get('rollback_failed', []))
        self.assertTrue(rb_cond.get('sha_match'))
        self.assertTrue(rb_cond.get('counts_match'))
        self.assertTrue(rb_cond.get('fk_on'))
        self.assertEqual(self._fresh_rows(), 2)
        self._rec('T14_rollback_integrity_fail',
                  'os.replace wrapper detects rollback phase; _connect returns BadIntegrityConn when phase[rollback_replaced]=True',
                  result, before_sha, before_rows,
                  {'rollback_conditions': rb_cond,
                   'rollback_failed': result.get('rollback_failed'),
                   'rollback_integrity': result.get('rollback_integrity'),
                   'rollback_fk': result.get('rollback_fk'),
                   'phase_rollback_replaced': phase['rollback_replaced'],
                   'inject_hits': inject_count['n']})

    def test_T15_rollback_fk_off(self):
        """R2B-R1B: rollback FK off — rb_fk != 1 on rollback reconnect.
        Phase: os.replace wrapper; _connect sets FK off for db_path in both
        phases (post-replace trigger + rollback FK fail). inject_count counts
        FK-off injections inside the rollback phase; asserted == 1.
        No call-count ('Nth call') guessing."""
        before_sha, before_rows = self._add_live_v002_and_checkpoint()
        phase, wrapped_replace = self._make_rollback_phase_wrapper()
        real_connect = self.vrepo._connect
        inject_count = {'n': 0}
        def fk_off_counted(path):
            conn = real_connect(path)
            if os.path.abspath(path) == os.path.abspath(self.vpath):
                conn.execute("PRAGMA foreign_keys=OFF")
                if phase['rollback_replaced']:
                    inject_count['n'] += 1
            return conn
        with patch.object(vrs.os, 'replace', side_effect=wrapped_replace), \
             patch.object(self.vrepo, '_connect', side_effect=fk_off_counted):
            result = self.recovery_service.restore(self.backup_path, self.ctx_platform)
        self.assertFalse(result.get('restored'))
        self.assertFalse(result.get('rollback_restored'))
        self.assertEqual(result.get('error_code'), 'E-RESTORE-ROLLBACK-FAILED')
        self.assertTrue(result.get('repo_conn_alive'))
        self.assertTrue(phase['rollback_replaced'], 'rollback phase was never entered')
        self.assertEqual(inject_count['n'], 1, f'FK-off fault injected {inject_count["n"]} times in rollback phase, expected 1')
        rb_cond = result.get('rollback_conditions', {})
        self.assertFalse(rb_cond.get('fk_on'))
        self.assertIn('fk_on', result.get('rollback_failed', []))
        self.assertTrue(rb_cond.get('sha_match'))
        self.assertTrue(rb_cond.get('counts_match'))
        self.assertTrue(rb_cond.get('integrity_ok'))
        self.assertEqual(self._fresh_rows(), 2)
        self._rec('T15_rollback_fk_off',
                  'os.replace wrapper detects rollback phase; _connect FK off for db_path (both phases); inject_count counts rollback-phase FK-off injections',
                  result, before_sha, before_rows,
                  {'rollback_conditions': rb_cond,
                   'rollback_failed': result.get('rollback_failed'),
                   'rollback_integrity': result.get('rollback_integrity'),
                   'rollback_fk': result.get('rollback_fk'),
                   'phase_rollback_replaced': phase['rollback_replaced'],
                   'inject_hits': inject_count['n']})


if __name__ == '__main__':
    unittest.main()
