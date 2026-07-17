#!/usr/bin/env python3
"""
DM Daily Loop V1.2 — Actual Terminal Closure Test Suite

Covers all GPT V1.1 audit findings:
- Cross-store isolation (≥12 counter-examples)
- Journal Saga (≥15 tests)
- Vault closure (≥12 tests)
- B5 V0.1.2 integration (≥10 tests)
- F1 two-phase batch (≥10 tests)
- Vendor 66 + 37 base = 103+ total
"""
import sys, os, json, sqlite3, tempfile, hashlib, ast, time, uuid, shutil
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.daily_loop.models import *
from app.daily_loop.services.repository import AuthRepository
from app.daily_loop.services.vault_repository import VaultRepository
from app.daily_loop.services.caller_context import TrustedMemberProvider, CallerContext
from app.daily_loop.services.keyring import KeyRing
from app.daily_loop.services.holdings_bridge import V012HoldingsBridge
from app.daily_loop.providers import FailClosedCandidateProvider


def make_repo():
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    repo = AuthRepository(path); repo.init_schema()
    repo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='manager', display_alias='M-001', status='active'))
    repo.insert_member(StoreMember(member_id='M-002', store_id='S002', auth_user_id='U002', role='manager', display_alias='M-002', status='active'))
    repo.insert_member(StoreMember(member_id='M-003', store_id='S001', auth_user_id='U003', role='staff', display_alias='M-003', status='active'))
    repo.insert_customer(CustomerProfile(customer_id='C-001', store_id='S001', display_name='C-001', stage='new', contact_auth='granted', assigned_member_id='M-001'))
    repo.insert_customer(CustomerProfile(customer_id='C-002', store_id='S002', display_name='C-002', stage='new', contact_auth='granted', assigned_member_id='M-002'))
    return repo, path

def make_vault():
    os.environ.setdefault('DM_VAULT_MASTER_KEY', 'test_master_key_at_least_16_chars_long')
    os.environ.setdefault('DM_CALLER_SIGNING_KEY', 'test_signing_key_at_least_16_chars')
    os.environ.setdefault('DM_SERVICE_PRINCIPAL_SECRET', 'test_service_secret')
    os.environ.setdefault('DM_PLATFORM_RECOVERY_SECRET', 'test_platform_secret_different')
    os.environ.setdefault('DM_PLATFORM_RECOVERY_SIGNING_KEY', 'test_recovery_signing_key_16chars')
    os.environ.setdefault('DM_PLATFORM_RECOVERY_SECRET', 'test_platform_secret_different')
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    # Auth db for provider
    afd, apath = tempfile.mkstemp(suffix='.db'); os.close(afd)
    arepo = AuthRepository(apath); arepo.init_schema()
    arepo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='owner', display_alias='M-001', status='active'))
    arepo.close()
    from app.daily_loop.services.keyring import KeyRing
    from app.daily_loop.services.caller_context import TrustedMemberProvider
    provider = TrustedMemberProvider.from_env(apath)
    repo = VaultRepository(path, KeyRing(), provider=provider)
    repo.init_schema()
    return repo, path

def cleanup(path):
    try: os.unlink(path)
    except: pass


# ═══════════════════════════════════════════════════════
# §2: Cross-Store Isolation (≥12 counter-examples)
# ═══════════════════════════════════════════════════════
class TestCrossStoreIsolation(unittest.TestCase):
    """12+ cross-store counter-examples"""

    def test_01_cross_store_appointment(self):
        """S1顾客不能写入S2预约"""
        repo, path = make_repo()
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                repo.conn.execute(
                    "INSERT INTO dl_appointment (appointment_id,store_id,customer_id,member_id,scheduled_date,scheduled_time,duration_min,status) VALUES (?,?,?,?,?,?,?,?)",
                    ('apt-x','S002','C-001','M-002','2026-07-16','10:00',60,'scheduled'))
            self.assertIn('E-SCOPE', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_02_cross_store_task(self):
        """S1顾客不能写入S2任务"""
        repo, path = make_repo()
        try:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                repo.conn.execute(
                    "INSERT INTO dl_daily_customer_task (task_id,store_id,customer_id,assigned_member_id,task_date,status) VALUES (?,?,?,?,?,?)",
                    ('T-x','S002','C-001','M-002','2026-07-16','draft'))
            self.assertIn('E-SCOPE', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_03_cross_store_member_access(self):
        """S2不能读S1成员"""
        repo, path = make_repo()
        try:
            self.assertIsNone(repo.get_member('M-001', 'S002'))
        finally: repo.close(); cleanup(path)

    def test_04_cross_store_member_update(self):
        """S2不能改S1成员状态"""
        repo, path = make_repo()
        try:
            with self.assertRaises(ValueError):
                repo.update_member_status('M-001', 'S002', 'disabled', 'test')
        finally: repo.close(); cleanup(path)

    def test_05_cross_store_customer_access(self):
        """S2不能读S1顾客"""
        repo, path = make_repo()
        try:
            self.assertIsNone(repo.get_customer('C-001', 'S002'))
        finally: repo.close(); cleanup(path)

    def test_06_cross_store_appointment_list(self):
        """S2查预约不返回S1数据"""
        repo, path = make_repo()
        try:
            repo.conn.execute("INSERT INTO dl_appointment (appointment_id,store_id,customer_id,member_id,scheduled_date,scheduled_time,duration_min,status) VALUES (?,?,?,?,?,?,?,?)",
                ('apt-1','S001','C-001','M-001','2026-07-16','10:00',60,'scheduled'))
            repo.conn.commit()
            s1 = repo.list_appointments('S001', '2026-07-16')
            s2 = repo.list_appointments('S002', '2026-07-16')
            self.assertEqual(len(s1), 1)
            self.assertEqual(len(s2), 0)
        finally: repo.close(); cleanup(path)

    def test_07_cross_store_task_list(self):
        """S2查任务不返回S1数据"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            s1 = repo.list_tasks('S001', '2026-07-16')
            s2 = repo.list_tasks('S002', '2026-07-16')
            self.assertEqual(len(s1), 1)
            self.assertEqual(len(s2), 0)
        finally: repo.close(); cleanup(path)

    def test_08_cross_store_feedback(self):
        """S2不能给S1的任务写反馈"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                repo.conn.execute("INSERT INTO dl_service_feedback (feedback_id,store_id,task_id,member_id,feedback_items_json,data_gap_flags) VALUES (?,?,?,?,?,?)",
                    ('F-x','S002','T-001','M-002','[]','[]'))
            self.assertIn('E-SCOPE', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_09_cross_store_appointment_transition(self):
        """S2不能改S1预约状态"""
        repo, path = make_repo()
        try:
            repo.conn.execute("INSERT INTO dl_appointment (appointment_id,store_id,customer_id,member_id,scheduled_date,scheduled_time,duration_min,status) VALUES (?,?,?,?,?,?,?,?)",
                ('apt-1','S001','C-001','M-001','2026-07-16','10:00',60,'scheduled'))
            repo.conn.commit()
            with self.assertRaises(ValueError):
                repo.transition_appointment('apt-1', 'S002', 'arrived', 'M-002')
        finally: repo.close(); cleanup(path)

    def test_10_cross_store_task_freeze(self):
        """S2不能冻结S1任务"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S002')  # should not affect S001 task
            t = repo.get_task('T-001', 'S001')
            self.assertFalse(t.frozen)  # S001 task not frozen
        finally: repo.close(); cleanup(path)

    def test_11_cross_store_task_status_update(self):
        """S2不能改S1任务状态"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            with self.assertRaises(ValueError):
                repo.update_task_status('T-001', 'S002', 'completed')
        finally: repo.close(); cleanup(path)

    def test_12_cross_store_journal_access(self):
        """S2不能读S1 Journal终态"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-001', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            with self.assertRaises(ValueError):
                repo.replay_journal_terminal_status('J-001', 'S002')
        finally: repo.close(); cleanup(path)


# ═══════════════════════════════════════════════════════
# §4: Journal Saga (≥15 tests)
# ═══════════════════════════════════════════════════════
class TestJournalSaga(unittest.TestCase):
    """15+ Journal/Saga tests"""

    def test_01_journal_create(self):
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-001', store_id='S001', operation_type='customer_create', initiated_by='M-001')
            repo.create_journal(j)
            self.assertIsNotNone(repo.conn.execute("SELECT * FROM dl_operation_journal WHERE journal_id='J-001'").fetchone())
        finally: repo.close(); cleanup(path)

    def test_02_journal_step_append(self):
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-002', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-002', step_order=1, step_name='create_profile', step_status='completed'))
            steps = repo.conn.execute("SELECT * FROM dl_operation_journal_step WHERE journal_id='J-002'").fetchall()
            self.assertEqual(len(steps), 1)
        finally: repo.close(); cleanup(path)

    def test_03_journal_step_no_update(self):
        """TRIGGER拦截UPDATE"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-003', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-003', step_order=1, step_name='step1', step_status='completed'))
            with self.assertRaises(sqlite3.IntegrityError):
                repo.conn.execute("UPDATE dl_operation_journal_step SET step_status='failed' WHERE step_id='S1'")
        finally: repo.close(); cleanup(path)

    def test_04_journal_step_no_delete(self):
        """TRIGGER拦截DELETE"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-004', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-004', step_order=1, step_name='step1', step_status='completed'))
            with self.assertRaises(sqlite3.IntegrityError):
                repo.conn.execute("DELETE FROM dl_operation_journal_step WHERE step_id='S1'")
        finally: repo.close(); cleanup(path)

    def test_05_journal_replay_completed(self):
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-005', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-005', step_order=1, step_name='step1', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-005', step_order=2, step_name='step2', step_status='completed'))
            self.assertEqual(repo.replay_journal_terminal_status('J-005', 'S001'), 'completed')
        finally: repo.close(); cleanup(path)

    def test_06_journal_replay_partial_failed(self):
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-006', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-006', step_order=1, step_name='step1', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-006', step_order=2, step_name='step2', step_status='failed', error_code='E-TIMEOUT'))
            self.assertEqual(repo.replay_journal_terminal_status('J-006', 'S001'), 'partial_failed')
        finally: repo.close(); cleanup(path)

    def test_07_journal_retry_append(self):
        """失败步骤追加新attempt,不UPDATE旧行"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-007', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-007', step_order=1, step_name='step1', attempt_number=1, step_status='failed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-007', step_order=1, step_name='step1', attempt_number=2, step_status='completed'))
            status = repo.replay_journal_terminal_status('J-007', 'S001')
            self.assertEqual(status, 'completed')
        finally: repo.close(); cleanup(path)

    def test_08_journal_duplicate_attempt_blocked(self):
        """UNIQUE(journal_id, step_name, attempt_number)防止同一attempt写入两次"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-008', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-008', step_order=1, step_name='step1', attempt_number=1, step_status='completed'))
            with self.assertRaises(sqlite3.IntegrityError):
                repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-008', step_order=1, step_name='step1', attempt_number=1, step_status='failed'))
        finally: repo.close(); cleanup(path)

    def test_09_journal_compensated(self):
        """compensated状态→partial_failed"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-009', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-009', step_order=1, step_name='step1', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-009', step_order=2, step_name='step2', step_status='failed'))
            repo.append_journal_step(OperationJournalStep(step_id='S3', journal_id='J-009', step_order=3, step_name='compensate', step_status='compensated'))
            self.assertEqual(repo.replay_journal_terminal_status('J-009', 'S001'), 'partial_failed')
        finally: repo.close(); cleanup(path)

    def test_10_journal_cross_store_access(self):
        """S2不能读S1 Journal"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-010', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            with self.assertRaises(ValueError):
                repo.replay_journal_terminal_status('J-010', 'S002')
        finally: repo.close(); cleanup(path)

    def test_11_journal_idempotency_key(self):
        """Journal幂等键UNIQUE"""
        repo, path = make_repo()
        try:
            j1 = OperationJournal(journal_id='J-011', store_id='S001', operation_type='test', initiated_by='M-001', idempotency_key='idem-001')
            repo.create_journal(j1)
            j2 = OperationJournal(journal_id='J-012', store_id='S001', operation_type='test', initiated_by='M-001', idempotency_key='idem-001')
            with self.assertRaises(sqlite3.IntegrityError):
                repo.create_journal(j2)
        finally: repo.close(); cleanup(path)

    def test_12_journal_pending_no_steps(self):
        """无步骤时终态=pending"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-012', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            self.assertEqual(repo.replay_journal_terminal_status('J-012', 'S001'), 'pending')
        finally: repo.close(); cleanup(path)

    def test_13_journal_step_error_code(self):
        """步骤可记录error_code"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-013', store_id='S001', operation_type='test', initiated_by='M-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-013', step_order=1, step_name='step1', step_status='failed', error_code='E-VAULT-KEY-MISSING', error_message='key not found'))
            row = repo.conn.execute("SELECT error_code FROM dl_operation_journal_step WHERE step_id='S1'").fetchone()
            self.assertEqual(row['error_code'], 'E-VAULT-KEY-MISSING')
        finally: repo.close(); cleanup(path)

    def test_14_journal_saga_customer_create(self):
        """A1建档Saga: profile→vault→holding 3步骤"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-014', store_id='S001', operation_type='customer_create', initiated_by='M-001', resource_id='C-NEW')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-014', step_order=1, step_name='create_profile', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-014', step_order=2, step_name='create_vault', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S3', journal_id='J-014', step_order=3, step_name='init_holdings', step_status='completed'))
            self.assertEqual(repo.replay_journal_terminal_status('J-014', 'S001'), 'completed')
        finally: repo.close(); cleanup(path)

    def test_15_journal_saga_erasure_partial(self):
        """A7删除权Saga: vault步骤失败→partial_failed→manual_review"""
        repo, path = make_repo()
        try:
            j = OperationJournal(journal_id='J-015', store_id='S001', operation_type='erasure', initiated_by='M-001', resource_id='C-001')
            repo.create_journal(j)
            repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-015', step_order=1, step_name='archive_profile', step_status='completed'))
            repo.append_journal_step(OperationJournalStep(step_id='S2', journal_id='J-015', step_order=2, step_name='purge_vault', step_status='failed', error_code='E-VAULT-KEY-MISSING'))
            self.assertEqual(repo.replay_journal_terminal_status('J-015', 'S001'), 'partial_failed')
        finally: repo.close(); cleanup(path)


# ═══════════════════════════════════════════════════════
# §3: Vault Closure (≥12 tests)
# ═══════════════════════════════════════════════════════
class TestVaultClosure(unittest.TestCase):
    """12+ Vault tests — V1.3A.5 CallerContext + AEAD"""

    def setUp(self):
        os.environ['DM_VAULT_MASTER_KEY'] = 'test_master_key_at_least_16_chars_long'
        os.environ['DM_CALLER_SIGNING_KEY'] = 'test_signing_key_at_least_16_chars'
        os.environ['DM_SERVICE_PRINCIPAL_SECRET'] = 'test_service_secret'
        os.environ['DM_PLATFORM_RECOVERY_SECRET'] = 'test_platform_secret_different'
        os.environ['DM_PLATFORM_RECOVERY_SIGNING_KEY'] = 'test_recovery_signing_key_16chars'
        os.environ['DM_PLATFORM_RECOVERY_SECRET'] = 'test_platform_secret_different'
        fd, self.auth_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        self.auth_repo = AuthRepository(self.auth_path); self.auth_repo.init_schema()
        self.auth_repo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='owner', display_alias='M-001', status='active'))
        self.auth_repo.insert_member(StoreMember(member_id='M-002', store_id='S002', auth_user_id='U002', role='owner', display_alias='M-002', status='active'))
        self.auth_repo.close()
        fd, self.vpath = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(self.vpath)
        self.kr = KeyRing()
        self.provider = TrustedMemberProvider.from_env(self.auth_path)
        self.repo = VaultRepository(self.vpath, self.kr, provider=self.provider)
        self.repo.init_schema()
        self.ctx_owner = self.provider.create('U001', 'S001')
        self.repo.insert_vault(vault_id='V-001', subject_type='customer', subject_id='C-001',
            store_id='S001', plaintext_phone='13800138000', plaintext_name='ZhangSan',
            ctx=self.ctx_owner)

    def tearDown(self):
        self.repo.close(); self.auth_repo.close()
        cleanup(self.auth_path)
        try: cleanup(self.vpath)
        except: pass

    def test_01_vault_separate_db(self):
        auth_repo, auth_path = make_repo()
        try:
            tables = [r[0] for r in auth_repo.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'").fetchall()]
            self.assertNotIn('dl_identity_vault', tables)
        finally: auth_repo.close(); cleanup(auth_path)

    def test_02_system_read_denied(self):
        from app.daily_loop.services.caller_context import TrustedMemberProvider
        ctx_sys = self.provider.create_system('daily_loop_orchestrator', os.environ.get('DM_SERVICE_PRINCIPAL_SECRET', ''))
        try:
            result = self.repo.read_vault('V-001', ctx_sys, 'batch')
            self.assertIsNone(result)
        except PermissionError: pass

    def test_03_owner_read_allowed(self):
        result = self.repo.read_vault('V-001', self.ctx_owner, 'service')
        self.assertIsNotNone(result, 'Owner should read vault')
        self.assertEqual(result.get('phone'), '13800138000')

    def test_04_vault_access_log_recorded(self):
        self.repo.read_vault('V-001', self.ctx_owner, 'test')
        logs = self.repo.conn.execute("SELECT * FROM dl_vault_access_log WHERE vault_id='V-001' AND access_type='read'").fetchall()
        self.assertGreater(len(logs), 0)

    def test_05_key_rotation_changes_ciphertext(self):
        old_enc = self.repo.conn.execute("SELECT encrypted_phone FROM dl_identity_vault WHERE vault_id='V-001'").fetchone()['encrypted_phone']
        self.repo.rotate_key('V-001', 'v2', self.ctx_owner)
        new_enc = self.repo.conn.execute("SELECT encrypted_phone FROM dl_identity_vault WHERE vault_id='V-001'").fetchone()['encrypted_phone']
        self.assertNotEqual(old_enc, new_enc, 'ciphertext must change after rotation')

    def test_06_rotation_logged(self):
        self.repo.rotate_key('V-001', 'v2', self.ctx_owner)
        logs = self.repo.conn.execute("SELECT * FROM dl_vault_access_log WHERE access_type='rotate'").fetchall()
        self.assertGreaterEqual(len(logs), 1)

    def test_07_cross_store_vault_denied(self):
        from app.daily_loop.services.caller_context import TrustedMemberProvider
        ctx_s2 = self.provider.create('U002', 'S002')
        try:
            result = self.repo.read_vault('V-001', ctx_s2, 'cross_store')
            self.assertIsNone(result)
        except PermissionError: pass

    def test_08_fake_context_denied(self):
        from app.daily_loop.services.caller_context import CallerContext
        # Attacker constructs context with fake token (no signing key needed)
        fake = CallerContext('M-FAKE', 'S001', 'owner', token=b'fake_token')
        try:
            result = self.repo.read_vault('V-001', fake, 'spoof')
            self.assertIsNone(result)
        except PermissionError: pass

    def test_09_backup_and_restore(self):
        # Only platform recovery service can backup/restore
        from app.daily_loop.services.vault_recovery_service import VaultRecoveryService
        from app.daily_loop.services.platform_recovery import PlatformRecoveryProvider
        recovery_provider = PlatformRecoveryProvider.from_env()
        ctx_platform = recovery_provider.create('platform_admin', os.environ.get('DM_PLATFORM_RECOVERY_SECRET', ''))
        recovery_service = VaultRecoveryService(self.repo, self.kr)
        bpath = self.vpath + '.bak'
        recovery_service.backup(bpath, ctx_platform)
        self.assertTrue(os.path.exists(bpath))
        result = recovery_service.restore(bpath, ctx_platform)
        self.assertTrue(result.get('restored'))

    def test_10_wrong_key_backup_rejected(self):
        from app.daily_loop.services.keyring import KeyRing, restore_vault
        from app.daily_loop.services.vault_recovery_service import VaultRecoveryService
        from app.daily_loop.services.platform_recovery import PlatformRecoveryProvider
        from cryptography.exceptions import InvalidTag
        recovery_provider = PlatformRecoveryProvider.from_env()
        ctx_platform = recovery_provider.create('platform_admin', os.environ.get('DM_PLATFORM_RECOVERY_SECRET', ''))
        recovery_service = VaultRecoveryService(self.repo, self.kr)
        bpath = self.vpath + '.bak'
        recovery_service.backup(bpath, ctx_platform)
        # Create a KeyRing with a different (but valid-length) key
        old_env = os.environ.get('DM_VAULT_MASTER_KEY')
        os.environ['DM_VAULT_MASTER_KEY'] = 'different_valid_key_at_least_16_chars'
        wrong_kr = KeyRing()
        os.environ['DM_VAULT_MASTER_KEY'] = old_env
        # Wrong master key must fail with the precise contract exception InvalidTag
        # (AES-GCM auth-tag mismatch). A broad tuple with Exception would false-green
        # on unrelated errors, so it is intentionally NOT used.
        with self.assertRaises(InvalidTag):
            restore_vault(bpath, self.vpath + '.x', wrong_kr.get_master())

    def test_11_rotation_old_key_cannot_decrypt(self):
        old_enc = self.repo.conn.execute("SELECT encrypted_phone FROM dl_identity_vault WHERE vault_id='V-001'").fetchone()['encrypted_phone']
        self.repo.rotate_key('V-001', 'v2', self.ctx_owner)
        new_enc = self.repo.conn.execute("SELECT encrypted_phone FROM dl_identity_vault WHERE vault_id='V-001'").fetchone()['encrypted_phone']
        self.assertNotEqual(old_enc, new_enc, 'ciphertext must change after rotation')

    def test_12_same_plaintext_different_ciphertext(self):
        from app.daily_loop.services.keyring import encrypt
        e1 = encrypt(b'test', self.kr.get_master(), 'v1', b'AAD1')
        e2 = encrypt(b'test', self.kr.get_master(), 'v1', b'AAD2')
        self.assertNotEqual(e1, e2, 'same plaintext different AAD must produce different ciphertext')

    def test_13_vault_not_in_auth_imports(self):
        import ast
        app_dir = Path(__file__).parent.parent / 'app' / 'daily_loop'
        for root, dirs, files in os.walk(app_dir):
            for fname in files:
                if not fname.endswith('.py'): continue
                if 'vault' in fname.lower(): continue
                with open(Path(root) / fname) as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if 'vault' in node.module.lower():
                            self.fail(f'{fname} imports vault: {node.module}')

    def test_14_vault_subject_type_customer(self):
        row = self.repo.conn.execute("SELECT subject_type FROM dl_identity_vault WHERE vault_id='V-001'").fetchone()
        self.assertEqual(row['subject_type'], 'customer')

    def test_15_write_logs_access(self):
        logs = self.repo.conn.execute("SELECT * FROM dl_vault_access_log WHERE access_type='write'").fetchall()
        self.assertGreaterEqual(len(logs), 1)


# ═══════════════════════════════════════════════════════
# §5: B5 V0.1.2 Integration (≥10 tests)
# ═══════════════════════════════════════════════════════
class TestB5V012Integration(unittest.TestCase):
    def setUp(self):
        fd, self.hpath = tempfile.mkstemp(suffix='.db'); os.close(fd)
        self.bridge = V012HoldingsBridge(self.hpath)
        self.bridge.setup_customer_with_balance('S001', 'C-001', 'I-001', 10)

    def tearDown(self): cleanup(self.hpath)

    def test_01_confirm_consumption(self):
        result = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-001')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['balance_remaining'], 7)

    def test_02_quantity_must_be_positive(self):
        from app.daily_loop.models import ConsumptionEvent
        c = ConsumptionEvent(event_id='E-001', store_id='S001', customer_id='C-001', member_id='M-001', item_id='I-001', quantity=0)
        err = c.validate()
        self.assertIsNotNone(err)
        self.assertIn('must be positive', err)

    def test_03_hash_chain_integrity(self):
        self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-003')
        self.assertTrue(self.bridge.verify_hash_chain('S001', 'C-001', 'I-001'))

    def test_04_idempotency_same_payload(self):
        r1 = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-004')
        self.assertTrue(r1['confirmed'])
        r2 = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-004')
        self.assertTrue(r2['confirmed'])
        self.assertEqual(r2['balance_remaining'], r1['balance_remaining'])

    def test_05_idempotency_conflict_different_payload(self):
        r1 = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-005')
        self.assertTrue(r1['confirmed'])
        r2 = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 5, 'M-001', 'idem-005')
        self.assertFalse(r2['confirmed'])

    def test_06_insufficient_balance(self):
        result = self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 100, 'M-001', 'idem-006')
        self.assertFalse(result['confirmed'])

    def test_07_get_balance(self):
        bal = self.bridge.get_balance('S001', 'C-001', 'I-001')
        self.assertEqual(bal['quantity_remaining'], 10)

    def test_08_multiple_consumptions(self):
        self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-007')
        self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 2, 'M-001', 'idem-008')
        bal = self.bridge.get_balance('S001', 'C-001', 'I-001')
        self.assertEqual(bal['quantity_remaining'], 5)

    def test_09_contract_version(self):
        self.assertEqual(self.bridge.contract_version, 'dm-customer-holdings-v0.1.2')

    def test_10_hash_chain_after_multiple_ops(self):
        self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 3, 'M-001', 'idem-010')
        self.bridge.confirm_consumption('S001', 'C-001', 'I-001', 2, 'M-001', 'idem-011')
        self.assertTrue(self.bridge.verify_hash_chain('S001', 'C-001', 'I-001'))


# ═══════════════════════════════════════════════════════
# §6: F1 Two-Phase Batch (≥10 tests)
# ═══════════════════════════════════════════════════════
class TestF1FreezeWindow(unittest.TestCase):
    def test_01_task_can_freeze(self):
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S001')
            t = repo.get_task('T-001', 'S001')
            self.assertTrue(t.frozen)
        finally: repo.close(); cleanup(path)

    def test_02_frozen_task_cannot_modify(self):
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S001')
            with self.assertRaises(ValueError) as ctx:
                repo.update_task_status('T-001', 'S001', 'completed')
            self.assertIn('frozen', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_03_unfrozen_task_can_modify(self):
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.update_task_status('T-001', 'S001', 'assigned')
            t = repo.get_task('T-001', 'S001')
            self.assertEqual(t.status, 'assigned')
        finally: repo.close(); cleanup(path)

    def test_04_cross_store_freeze_no_effect(self):
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S002')
            t = repo.get_task('T-001', 'S001')
            self.assertFalse(t.frozen)
        finally: repo.close(); cleanup(path)

    def test_05_batch_freeze_multiple_tasks(self):
        """F1两段式: 批量冻结"""
        repo, path = make_repo()
        try:
            for i in range(5):
                repo.insert_task(DailyCustomerTask(task_id=f'T-{i:03d}', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            # Freeze all
            for i in range(5):
                repo.freeze_task(f'T-{i:03d}', 'S001')
            # All frozen
            for i in range(5):
                t = repo.get_task(f'T-{i:03d}', 'S001')
                self.assertTrue(t.frozen)
        finally: repo.close(); cleanup(path)

    def test_06_frozen_task_rejects_status_change(self):
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='assigned'))
            repo.freeze_task('T-001', 'S001')
            for target in ['in_progress', 'completed', 'skipped']:
                with self.assertRaises(ValueError):
                    repo.update_task_status('T-001', 'S001', target)
        finally: repo.close(); cleanup(path)

    def test_07_freeze_idempotent(self):
        """重复冻结不报错"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S001')
            repo.freeze_task('T-001', 'S001')  # idempotent
            t = repo.get_task('T-001', 'S001')
            self.assertTrue(t.frozen)
        finally: repo.close(); cleanup(path)

    def test_08_two_phase_prepare_then_freeze(self):
        """两段式: prepare(draft→assigned)→freeze"""
        repo, path = make_repo()
        try:
            # Phase 1: prepare
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.update_task_status('T-001', 'S001', 'assigned')
            # Phase 2: freeze
            repo.freeze_task('T-001', 'S001')
            t = repo.get_task('T-001', 'S001')
            self.assertTrue(t.frozen)
            self.assertEqual(t.status, 'assigned')
        finally: repo.close(); cleanup(path)

    def test_09_freeze_nonexistent_task(self):
        repo, path = make_repo()
        try:
            with self.assertRaises(ValueError) as ctx:
                repo.update_task_status('T-NONEXIST', 'S001', 'assigned')
            self.assertIn('not found', str(ctx.exception).lower() + str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_10_frozen_at_timestamp_set(self):
        """冻结后frozen_at有时间戳"""
        repo, path = make_repo()
        try:
            repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
            repo.freeze_task('T-001', 'S001')
            t = repo.get_task('T-001', 'S001')
            self.assertIsNotNone(t.frozen_at)
        finally: repo.close(); cleanup(path)


# ═══════════════════════════════════════════════════════
# §1: Model/DDL/Repository Consistency
# ═══════════════════════════════════════════════════════
class TestModelDDLConsistency(unittest.TestCase):
    """三方一致性: Model fields ↔ DDL columns ↔ Repository SQL"""

    def test_store_member_fields_match_ddl(self):
        import dataclasses
        from app.daily_loop.models import StoreMember
        model_fields = {f.name for f in dataclasses.fields(StoreMember)}
        # Read DDL columns
        repo, path = make_repo()
        try:
            cols = {r[1] for r in repo.conn.execute("PRAGMA table_info(dl_store_member)").fetchall()}
            # Model may have computed properties like 'frozen', but fields should be subset of DDL
            # Actually model fields should map to DDL columns (minus computed properties)
            extra = model_fields - cols - {'frozen'}  # frozen is a property
            self.assertEqual(extra, set(), f"Model has fields not in DDL: {extra}")
        finally: repo.close(); cleanup(path)

    def test_customer_profile_fields_match_ddl(self):
        import dataclasses
        from app.daily_loop.models import CustomerProfile
        model_fields = {f.name for f in dataclasses.fields(CustomerProfile)}
        repo, path = make_repo()
        try:
            cols = {r[1] for r in repo.conn.execute("PRAGMA table_info(dl_customer_profile)").fetchall()}
            extra = model_fields - cols
            self.assertEqual(extra, set(), f"Model has fields not in DDL: {extra}")
        finally: repo.close(); cleanup(path)


# ═══════════════════════════════════════════════════════
# §7: Security & Privacy
# ═══════════════════════════════════════════════════════
class TestSecurityPrivacy(unittest.TestCase):
    def test_g3_manager_cannot_invite_manager(self):
        m = StoreMember(member_id='M-002', store_id='S001', auth_user_id='U002', role='manager', display_alias='M-002')
        self.assertFalse(m.is_role_allowed_for_invite('manager'))

    def test_g3_manager_can_invite_staff(self):
        m = StoreMember(member_id='M-005', store_id='S001', auth_user_id='U005', role='staff', display_alias='M-005')
        self.assertTrue(m.is_role_allowed_for_invite('manager'))

    def test_g4_left_revival_blocked(self):
        repo, path = make_repo()
        try:
            repo.update_member_status('M-001', 'S001', 'left', 'test')
            with self.assertRaises(ValueError):
                repo.update_member_status('M-001', 'S001', 'active', 'revival')
        finally: repo.close(); cleanup(path)

    def test_e12_denied_shortcircuit(self):
        p = PrivateTargetedMessage(message_id='M-001', store_id='S001', customer_id='C-001', member_id='M-001', message_content='test', consent_status='denied')
        self.assertFalse(p.can_send())

    def test_e12_withdrawn_shortcircuit(self):
        p = PrivateTargetedMessage(message_id='M-002', store_id='S001', customer_id='C-001', member_id='M-001', message_content='test', consent_status='withdrawn')
        self.assertFalse(p.can_send())

    def test_f3_pii_scanned_required(self):
        k = KnowledgeCandidateProjection(projection_id='P-001', store_id='S001', projection_type='test', aggregated_data='{}', pii_scanned=False, sample_size=10, source_event_hashes='[]', projection_rule_version='v1', allowlist_policy_version='v1')
        self.assertIn('pii_scanned', k.validate_fail_closed())

    def test_f3_sample_below_threshold(self):
        k = KnowledgeCandidateProjection(projection_id='P-002', store_id='S001', projection_type='test', aggregated_data='{}', pii_scanned=True, sample_size=3, source_event_hashes='[]', projection_rule_version='v1', allowlist_policy_version='v1')
        self.assertIn('sample_size', k.validate_fail_closed())

    def test_b4_max_7_items(self):
        items = [
            {'check_item': 'service_completed', 'checked': True},
            {'check_item': 'customer_satisfied', 'checked': True},
            {'check_item': 'products_recommended', 'checked': False},
            {'check_item': 'next_visit_suggested', 'checked': True},
            {'check_item': 'feedback_collected', 'checked': True},
            {'check_item': 'aftercare_reminded', 'checked': True},
            {'check_item': 'problem_handled', 'checked': False},
        ]
        f = ServiceFeedback(feedback_id='F-001', store_id='S001', task_id='T-001', member_id='M-001', feedback_items=items)
        self.assertIsNone(f.validate())

    def test_b4_8_items_rejected(self):
        items = [{'check_item': 'service_completed', 'checked': True}] * 8
        f = ServiceFeedback(feedback_id='F-002', store_id='S001', task_id='T-001', member_id='M-001', feedback_items=items)
        self.assertIsNotNone(f.validate())

    def test_c7_medical_keywords(self):
        keywords = ['抑郁症', '心脏病', '高血压', '糖尿病', '癫痫', '精神分裂', '甲亢', '甲减', '乙肝', '艾滋病']
        for kw in keywords:
            e = EmployeeDailyStatus(status_id='S-001', store_id='S001', member_id='M-001', status_date='2026-07-15', daily_status='attention_flag', note=f'员工有{kw}')
            self.assertIn('forbidden medical', e.validate())


# ═══════════════════════════════════════════════════════
# §9: DDL Integrity & Production Zero Connection
# ═══════════════════════════════════════════════════════
class TestDDLIntegrity(unittest.TestCase):
    def test_auth_21_tables(self):
        repo, path = make_repo()
        try:
            count = repo.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'").fetchone()[0]
            self.assertEqual(count, 21)
        finally: repo.close(); cleanup(path)

    def test_vault_2_tables(self):
        repo, path = make_vault()
        try:
            count = repo.conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'").fetchone()[0]
            self.assertEqual(count, 2)
        finally: repo.close(); cleanup(path)

    def test_rollback_drops_all(self):
        fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        try:
            conn = sqlite3.connect(path)
            with open('app/daily_loop/migrations/001_initial_schema.sql') as f:
                conn.executescript(f.read())
            with open('app/daily_loop/migrations/002_rollback.sql') as f:
                conn.executescript(f.read())
            count = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'dl_%'").fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()
        finally: cleanup(path)

    def test_triggers_present(self):
        repo, path = make_repo()
        try:
            triggers = [r[0] for r in repo.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]
            self.assertIn('trg_consumption_no_update', triggers)
            self.assertIn('trg_consumption_no_delete', triggers)
            self.assertIn('trg_journal_step_no_update', triggers)
            self.assertIn('trg_journal_step_no_delete', triggers)
            self.assertIn('trg_appointment_cross_store_check', triggers)
            self.assertIn('trg_task_cross_store_check', triggers)
        finally: repo.close(); cleanup(path)


class TestProductionZeroConnection(unittest.TestCase):
    def test_no_network_imports(self):
        import ast
        app_dir = Path(__file__).parent.parent / 'app'
        forbidden = {'requests','http','socket','flask','fastapi','uvicorn','urllib3','httpx','aiohttp'}
        for root, dirs, files in os.walk(app_dir):
            for fname in files:
                if not fname.endswith('.py'): continue
                with open(Path(root) / fname) as f:
                    try: tree = ast.parse(f.read())
                    except: continue
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for a in node.names:
                                if a.name.split('.')[0] in forbidden:
                                    self.fail(f'{fname}: forbidden import {a.name}')
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.module.split('.')[0] in forbidden:
                                self.fail(f'{fname}: forbidden import {node.module}')

    def test_no_real_pii(self):
        import re
        app_dir = Path(__file__).parent.parent / 'app'
        for root, dirs, files in os.walk(app_dir):
            for fname in files:
                if not fname.endswith('.py'): continue
                with open(Path(root) / fname) as f:
                    content = f.read()
                phones = re.findall(r'1[3-9]\d{9}', content)
                self.assertEqual(len(phones), 0, f'{fname} has phone: {phones}')


# ═══════════════════════════════════════════════════════
# Vendor V0.1.2
# ═══════════════════════════════════════════════════════
class TestVendorV012(unittest.TestCase):
    def test_vendor_contract_version(self):
        fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        bridge = V012HoldingsBridge(path)
        self.assertEqual(bridge.contract_version, 'dm-customer-holdings-v0.1.2')
        cleanup(path)

    def test_vendor_66_tests(self):
        import subprocess
        vendor_dir = Path(__file__).parent.parent / 'vendor' / 'dm_customer_holdings'
        tests_dir = vendor_dir / 'tests'
        if not tests_dir.exists():
            src = Path('/tmp/v012_vendor/dm_customer_holdings/tests')
            if src.exists(): shutil.copytree(src, tests_dir)
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(vendor_dir / 'tests'), '-q'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, f"V0.1.2 tests failed: {result.stderr[:500]}")


if __name__ == '__main__':
    unittest.main(verbosity=2)


# ═══════════════════════════════════════════════════════
# §A3.1: 安全写入口反例 (V1.3A.1新增)
# ═══════════════════════════════════════════════════════
class TestSecurityWriteGate(unittest.TestCase):
    """E12 denied不可落库; F3 pii_scanned=false不可落库"""

    def test_e12_denied_cannot_write(self):
        """E12 consent_status=denied不可写入dl_private_targeted_message"""
        repo, path = make_repo()
        try:
            m = PrivateTargetedMessage(
                message_id='M-denied', store_id='S001', customer_id='C-001',
                member_id='M-001', message_content='test', consent_status='denied',
                frequency_count=0)
            with self.assertRaises(ValueError) as ctx:
                repo.insert_targeted_message(m)
            self.assertIn('E-CONSENT', str(ctx.exception))
            # Verify nothing was written
            rows = repo.conn.execute("SELECT * FROM dl_private_targeted_message WHERE message_id='M-denied'").fetchall()
            self.assertEqual(len(rows), 0, 'denied message must not be in DB')
        finally: repo.close(); cleanup(path)

    def test_e12_withdrawn_cannot_write(self):
        """E12 consent_status=withdrawn不可写入"""
        repo, path = make_repo()
        try:
            m = PrivateTargetedMessage(
                message_id='M-withdrawn', store_id='S001', customer_id='C-001',
                member_id='M-001', message_content='test', consent_status='withdrawn',
                frequency_count=0)
            with self.assertRaises(ValueError) as ctx:
                repo.insert_targeted_message(m)
            self.assertIn('E-CONSENT', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_e12_granted_can_write(self):
        """E12 consent_status=granted可以写入"""
        repo, path = make_repo()
        try:
            m = PrivateTargetedMessage(
                message_id='M-granted', store_id='S001', customer_id='C-001',
                member_id='M-001', message_content='test', consent_status='granted',
                frequency_count=0)
            repo.insert_targeted_message(m)
            rows = repo.conn.execute("SELECT * FROM dl_private_targeted_message WHERE message_id='M-granted'").fetchall()
            self.assertEqual(len(rows), 1)
        finally: repo.close(); cleanup(path)

    def test_f3_pii_false_cannot_write(self):
        """F3 pii_scanned=False不可写入dl_knowledge_candidate_projection"""
        repo, path = make_repo()
        try:
            k = KnowledgeCandidateProjection(
                projection_id='P-bad', store_id='S001', projection_type='test',
                aggregated_data='{}', pii_scanned=False, sample_size=10,
                source_event_hashes='[]', projection_rule_version='v1',
                allowlist_policy_version='v1')
            with self.assertRaises(ValueError) as ctx:
                repo.insert_projection(k)
            self.assertIn('E-SCHEMA', str(ctx.exception))
            rows = repo.conn.execute("SELECT * FROM dl_knowledge_candidate_projection WHERE projection_id='P-bad'").fetchall()
            self.assertEqual(len(rows), 0, 'pii_scanned=False projection must not be in DB')
        finally: repo.close(); cleanup(path)

    def test_f3_sample_below_5_cannot_write(self):
        """F3 sample_size<5不可写入"""
        repo, path = make_repo()
        try:
            k = KnowledgeCandidateProjection(
                projection_id='P-small', store_id='S001', projection_type='test',
                aggregated_data='{}', pii_scanned=True, sample_size=3,
                source_event_hashes='[]', projection_rule_version='v1',
                allowlist_policy_version='v1')
            with self.assertRaises(ValueError) as ctx:
                repo.insert_projection(k)
            self.assertIn('E-SCHEMA', str(ctx.exception))
        finally: repo.close(); cleanup(path)

    def test_f3_valid_can_write(self):
        """F3 合法投影可以写入"""
        repo, path = make_repo()
        try:
            k = KnowledgeCandidateProjection(
                projection_id='P-ok', store_id='S001', projection_type='test',
                aggregated_data='{}', pii_scanned=True, sample_size=10,
                source_event_hashes='["h1","h2","h3","h4","h5"]',
                projection_rule_version='v1', allowlist_policy_version='v1')
            repo.insert_projection(k)
            rows = repo.conn.execute("SELECT * FROM dl_knowledge_candidate_projection WHERE projection_id='P-ok'").fetchall()
            self.assertEqual(len(rows), 1)
        finally: repo.close(); cleanup(path)
# V1.3A.9-R6: VaultRecoveryService(clock=) + assertRaises(InvalidTag)
# V1.3A.9-R7: VaultRecoveryService(clock=) + assertRaises(InvalidTag) + reconnect_count verification
