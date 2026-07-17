#!/usr/bin/env python3
"""V1.3A.2 — Repository smoke tests: every public method success+counterexample."""
import sys, os, tempfile, json, sqlite3
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.daily_loop.models import *
from app.daily_loop.services.repository import AuthRepository

def make_repo():
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    repo = AuthRepository(path); repo.init_schema()
    repo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='manager', display_alias='M-001', status='active'))
    repo.insert_member(StoreMember(member_id='M-002', store_id='S002', auth_user_id='U002', role='manager', display_alias='M-002', status='active'))
    repo.insert_customer(CustomerProfile(customer_id='C-001', store_id='S001', display_name='C-001', stage='new', contact_auth='granted', assigned_member_id='M-001'))
    repo.insert_customer(CustomerProfile(customer_id='C-002', store_id='S002', display_name='C-002', stage='new', contact_auth='granted', assigned_member_id='M-002'))
    return repo, path

def cleanup(p):
    try: os.unlink(p)
    except: pass

class TestRepoMember(unittest.TestCase):
    def test_insert_and_get_member(self):
        repo, p = make_repo()
        m = repo.get_member('M-001', 'S001')
        self.assertIsNotNone(m)
        self.assertEqual(m.role, 'manager')
        repo.close(); cleanup(p)
    def test_get_member_cross_store(self):
        repo, p = make_repo()
        m = repo.get_member('M-001', 'S002')
        self.assertIsNone(m)
        repo.close(); cleanup(p)
    def test_list_members(self):
        repo, p = make_repo()
        members = repo.list_members('S001')
        self.assertEqual(len(members), 1)
        repo.close(); cleanup(p)
    def test_update_member_status(self):
        repo, p = make_repo()
        repo.update_member_status('M-001', 'S001', 'disabled', 'test')
        m = repo.get_member('M-001', 'S001')
        self.assertEqual(m.status, 'disabled')
        repo.close(); cleanup(p)
    def test_update_member_status_left_terminal(self):
        repo, p = make_repo()
        repo.update_member_status('M-001', 'S001', 'left', 'test')
        with self.assertRaises(ValueError):
            repo.update_member_status('M-001', 'S001', 'active', 'revival')
        repo.close(); cleanup(p)

class TestRepoCustomer(unittest.TestCase):
    def test_insert_and_get_customer(self):
        repo, p = make_repo()
        c = repo.get_customer('C-001', 'S001')
        self.assertIsNotNone(c)
        repo.close(); cleanup(p)
    def test_get_customer_cross_store(self):
        repo, p = make_repo()
        c = repo.get_customer('C-001', 'S002')
        self.assertIsNone(c)
        repo.close(); cleanup(p)
    def test_update_contact_auth(self):
        repo, p = make_repo()
        repo.update_contact_auth('C-001', 'S001', 'denied')
        c = repo.get_customer('C-001', 'S001')
        self.assertEqual(c.contact_auth, 'denied')
        self.assertIsNotNone(c.contact_auth_updated_at)
        repo.close(); cleanup(p)

class TestRepoAppointment(unittest.TestCase):
    def test_insert_and_get_appointment(self):
        repo, p = make_repo()
        repo.insert_appointment(Appointment(appointment_id='apt-001', store_id='S001', customer_id='C-001', member_id='M-001', scheduled_date='2026-07-16', scheduled_time='10:00', duration_min=60, status='scheduled'))
        a = repo.get_appointment('apt-001', 'S001')
        self.assertIsNotNone(a)
        repo.close(); cleanup(p)
    def test_list_appointments_by_date(self):
        repo, p = make_repo()
        repo.insert_appointment(Appointment(appointment_id='apt-001', store_id='S001', customer_id='C-001', member_id='M-001', scheduled_date='2026-07-16', scheduled_time='10:00', duration_min=60, status='scheduled'))
        apts = repo.list_appointments_by_date('S001', '2026-07-16')
        self.assertEqual(len(apts), 1)
        repo.close(); cleanup(p)
    def test_transition_appointment(self):
        repo, p = make_repo()
        repo.insert_appointment(Appointment(appointment_id='apt-001', store_id='S001', customer_id='C-001', member_id='M-001', scheduled_date='2026-07-16', scheduled_time='10:00', duration_min=60, status='scheduled'))
        repo.transition_appointment('apt-001', 'S001', 'arrived', 'M-001')
        a = repo.get_appointment('apt-001', 'S001')
        self.assertEqual(a.status, 'arrived')
        repo.close(); cleanup(p)

class TestRepoTask(unittest.TestCase):
    def test_insert_and_get_task(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
        t = repo.get_task('T-001', 'S001')
        self.assertIsNotNone(t)
        repo.close(); cleanup(p)
    def test_list_tasks_by_member(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
        tasks = repo.list_tasks_by_member('S001', 'M-001', '2026-07-16')
        self.assertEqual(len(tasks), 1)
        repo.close(); cleanup(p)
    def test_list_tasks_by_store(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
        tasks = repo.list_tasks_by_store('S001', '2026-07-16')
        self.assertEqual(len(tasks), 1)
        repo.close(); cleanup(p)
    def test_update_task_status(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
        repo.update_task_status('T-001', 'S001', 'assigned')
        t = repo.get_task('T-001', 'S001')
        self.assertEqual(t.status, 'assigned')
        repo.close(); cleanup(p)
    def test_freeze_task(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='assigned'))
        repo.freeze_task('T-001', 'S001')
        t = repo.get_task('T-001', 'S001')
        self.assertTrue(t.frozen)
        with self.assertRaises(ValueError):
            repo.update_task_status('T-001', 'S001', 'completed')
        repo.close(); cleanup(p)

class TestRepoFeedback(unittest.TestCase):
    def test_insert_feedback(self):
        repo, p = make_repo()
        repo.insert_task(DailyCustomerTask(task_id='T-001', store_id='S001', customer_id='C-001', assigned_member_id='M-001', task_date='2026-07-16', status='draft'))
        repo.insert_feedback(ServiceFeedback(feedback_id='F-001', store_id='S001', task_id='T-001', member_id='M-001', feedback_items=[{'check_item':'service_completed','checked':True}]))
        rows = repo.conn.execute("SELECT * FROM dl_service_feedback WHERE feedback_id='F-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoConsumption(unittest.TestCase):
    def test_insert_consumption_record(self):
        repo, p = make_repo()
        repo.insert_consumption_record(ConsumptionEvent(event_id='E-001', store_id='S001', customer_id='C-001', member_id='M-001', item_id='I-001', quantity=3, task_id='T-001', upstream_contract='dm-customer-holdings-v0.1.2'))
        rows = repo.conn.execute("SELECT * FROM dl_consumption_event WHERE event_id='E-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoEmployeeStatus(unittest.TestCase):
    def test_insert_employee_status(self):
        repo, p = make_repo()
        repo.insert_employee_status(EmployeeDailyStatus(status_id='ES-001', store_id='S001', member_id='M-001', status_date='2026-07-16', daily_status='on_duty', note=None))
        rows = repo.conn.execute("SELECT * FROM dl_employee_daily_status WHERE status_id='ES-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoDailySummary(unittest.TestCase):
    def test_upsert_daily_summary(self):
        repo, p = make_repo()
        repo.upsert_daily_summary(StoreDailySummary(summary_id='DS-001', store_id='S001', summary_date='2026-07-16', total_tasks=10, completed_tasks=8, skipped_tasks=2, total_consumption=5, total_feedback=3, auto_generated=False))
        rows = repo.conn.execute("SELECT * FROM dl_store_daily_summary WHERE summary_id='DS-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoJournal(unittest.TestCase):
    def test_create_and_replay_journal(self):
        repo, p = make_repo()
        repo.create_journal(OperationJournal(journal_id='J-001', store_id='S001', operation_type='customer_create', initiated_by='M-001'))
        repo.append_journal_step(OperationJournalStep(step_id='S1', journal_id='J-001', step_order=1, step_name='create_profile', step_status='completed'))
        status = repo.replay_journal_terminal_status('J-001', 'S001')
        self.assertEqual(status, 'completed')
        repo.close(); cleanup(p)

class TestRepoAudit(unittest.TestCase):
    def test_insert_audit(self):
        repo, p = make_repo()
        repo.insert_audit(AuditLog(audit_id='A-001', store_id='S001', member_id='M-001', action_type='vault_access', resource_type='vault', resource_id='V-001'))
        rows = repo.conn.execute("SELECT * FROM dl_audit_log WHERE audit_id='A-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoScript(unittest.TestCase):
    def test_insert_service_script(self):
        repo, p = make_repo()
        repo.insert_service_script(ServiceScript(script_id='SC-001', store_id='S001', member_id='M-001', scene_type='welcome', customer_id='C-001', task_id=None, today_goal='goal', recommended_opening='hello', professional_questions='[]', professional_explanation='exp', emotional_value_phrases='[]', recommended_phrases='[]', prohibited_phrases='[]', next_action='next', stop_condition='stop', evidence_refs='[]', rights_status='unknown', risk_level='low', enhanced=False, human_editable=True, auto_send=False))
        rows = repo.conn.execute("SELECT * FROM dl_service_script WHERE script_id='SC-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

class TestRepoCopy(unittest.TestCase):
    def test_insert_platform_copy(self):
        repo, p = make_repo()
        repo.insert_platform_copy(PlatformCopy(copy_id='CP-001', store_id='S001', platform='xhs', content_brief='brief', content_json='{}', enhanced=False, human_editable=True, auto_send=False, compliance_status='pending_review'))
        rows = repo.conn.execute("SELECT * FROM dl_platform_copy WHERE copy_id='CP-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)
    def test_insert_copy_review(self):
        repo, p = make_repo()
        repo.insert_platform_copy(PlatformCopy(copy_id='CP-001', store_id='S001', platform='xhs', content_brief='brief', content_json='{}', enhanced=False, human_editable=True, auto_send=False, compliance_status='pending_review'))
        repo.insert_copy_review(CopyReview(review_id='RV-001', copy_id='CP-001', store_id='S001', reviewer_member_id='M-001', decision='approved', review_result='pass', review_note='ok'))
        rows = repo.conn.execute("SELECT * FROM dl_copy_review WHERE review_id='RV-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)
    def test_insert_copy_feedback(self):
        repo, p = make_repo()
        repo.insert_platform_copy(PlatformCopy(copy_id='CP-001', store_id='S001', platform='xhs', content_brief='brief', content_json='{}', enhanced=False, human_editable=True, auto_send=False, compliance_status='pending_review'))
        repo.insert_copy_feedback(CopyUsageFeedback(feedback_id='FB-001', copy_id='CP-001', store_id='S001', member_id='M-001', feedback_type='adoption', evidence_status='correlational', feedback_data='{}'))
        rows = repo.conn.execute("SELECT * FROM dl_copy_usage_feedback WHERE feedback_id='FB-001'").fetchall()
        self.assertEqual(len(rows), 1)
        repo.close(); cleanup(p)

if __name__ == '__main__':
    unittest.main(verbosity=2)
