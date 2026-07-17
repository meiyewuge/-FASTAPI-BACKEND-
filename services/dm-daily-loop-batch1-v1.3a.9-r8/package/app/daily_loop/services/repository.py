#!/usr/bin/env python3
"""
DM Daily Loop V1.1 — Dual-Database Repository

AUTH库: 21张业务表 (business.db)
Vault库: 2张加密表 (vault_v0.db) — 物理独立,结构性零系统访问

关键修复:
- 跨店隔离: 所有查询带store_id,组合键(store_id, resource_id)
- Journal: 删除complete_journal_step的UPDATE,改为追加attempt+重放终态
- B5: 接入vendor/dm_customer_holdings V0.1.2真实包
"""

from __future__ import annotations

import sqlite3
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime, timezone

from app.daily_loop.models import (
    StoreMember, CustomerProfile, Appointment, DailyCustomerTask,
    TaskExecution, ServiceFeedback, ConsumptionEvent, CustomerSignal,
    EmployeeDailyStatus, StoreDailySummary, ServiceScript, PlatformCopy,
    CopyReview, CopyUsageFeedback, PrivateTargetedMessage,
    KnowledgeCandidateProjection, OperationJournal, OperationJournalStep,
    IdentityVault, VaultAccessLog, AuditLog,
)

# Import V0.1.2 vendor
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / 'vendor'))
from dm_customer_holdings.store import HoldingsStore
from dm_customer_holdings.contract import CONTRACT_VERSION as HOLDINGS_VERSION


class AuthRepository:
    """AUTH业务库 — 21张表,所有操作强制store_id隔离"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self, ddl_path: str = None):
        if ddl_path is None:
            ddl_path = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
        with open(ddl_path) as f:
            self.conn.executescript(f.read())

    # ═══════════════════════════════════════════════════════
    # StoreMember (G1-G4)
    # ═══════════════════════════════════════════════════════
    def insert_member(self, m: StoreMember):
        self.conn.execute(
            "INSERT INTO dl_store_member (member_id,store_id,auth_user_id,role,display_alias,status,invited_by,invited_at) VALUES (?,?,?,?,?,?,?,?)",
            (m.member_id, m.store_id, m.auth_user_id, m.role, m.display_alias, m.status, m.invited_by, m.invited_at))
        self.conn.commit()

    def get_member(self, member_id: str, store_id: str) -> Optional[StoreMember]:
        """跨店隔离: 必须同时匹配member_id和store_id"""
        row = self.conn.execute(
            "SELECT * FROM dl_store_member WHERE member_id=? AND store_id=?",
            (member_id, store_id)).fetchone()
        if not row: return None
        return StoreMember(**dict(row))

    def list_members(self, store_id: str, status_filter: str = None) -> List[StoreMember]:
        if status_filter:
            rows = self.conn.execute(
                "SELECT * FROM dl_store_member WHERE store_id=? AND status=? ORDER BY display_alias",
                (store_id, status_filter)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM dl_store_member WHERE store_id=? ORDER BY display_alias",
                (store_id,)).fetchall()
        return [StoreMember(**dict(r)) for r in rows]

    def update_member_status(self, member_id: str, store_id: str, target_status: str, audit_reason: str):
        """G4: 角色与状态迁移(强审计)"""
        m = self.get_member(member_id, store_id)
        if not m:
            raise ValueError(f"E-SCOPE: member not found in store {store_id}")
        if not m.can_transition(target_status):
            raise ValueError(f"E-STATE: {m.status} is terminal, cannot transition to {target_status}")
        self.conn.execute(
            "UPDATE dl_store_member SET status=?, updated_at=? WHERE member_id=? AND store_id=?",
            (target_status, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), member_id, store_id))
        self.conn.execute(
            "INSERT INTO dl_audit_log (audit_id,store_id,member_id,action_type,resource_type,resource_id,detail_json) VALUES (?,?,?,?,?,?,?)",
            (f"aud_{member_id}_{int(time.time())}", store_id, member_id, 'role_transition',
             'store_member', member_id, json.dumps({'target_status': target_status, 'reason': audit_reason})))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # CustomerProfile (A1/A2)
    # ═══════════════════════════════════════════════════════
    def insert_customer(self, c: CustomerProfile):
        self.conn.execute(
            "INSERT INTO dl_customer_profile (customer_id,store_id,display_name,stage,contact_auth,contact_auth_updated_at,assigned_member_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (c.customer_id, c.store_id, c.display_name, c.stage, c.contact_auth,
             c.contact_auth_updated_at, c.assigned_member_id, c.created_at, c.updated_at))
        self.conn.commit()

    def get_customer(self, customer_id: str, store_id: str) -> Optional[CustomerProfile]:
        row = self.conn.execute(
            "SELECT * FROM dl_customer_profile WHERE customer_id=? AND store_id=?",
            (customer_id, store_id)).fetchone()
        return CustomerProfile(**dict(row)) if row else None

    def update_contact_auth(self, customer_id: str, store_id: str, new_auth: str, initiated_by: str = None):
        """B6: 授权状态变更,denied/withdrawn硬短路"""
        from app.daily_loop.models import utcnow_iso
        self.conn.execute(
            "UPDATE dl_customer_profile SET contact_auth=?, contact_auth_updated_at=? WHERE customer_id=? AND store_id=?",
            (new_auth, utcnow_iso(), customer_id, store_id))
        # Audit log: use initiated_by if provided, else skip member_id FK
        if initiated_by:
            self.conn.execute(
                "INSERT INTO dl_audit_log (audit_id,store_id,member_id,action_type,resource_type,resource_id,detail_json) VALUES (?,?,?,?,?,?,?)",
                (f"aud_auth_{uuid.uuid4().hex[:8]}", store_id, initiated_by, 'auth_change',
                 'customer_profile', customer_id, json.dumps({'new_auth': new_auth})))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # Appointment (A3-A6)
    # ═══════════════════════════════════════════════════════
    def insert_appointment(self, a: Appointment):
        self.conn.execute(
            "INSERT INTO dl_appointment (appointment_id,store_id,customer_id,member_id,scheduled_date,scheduled_time,duration_min,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (a.appointment_id, a.store_id, a.customer_id, a.member_id, a.scheduled_date,
             a.scheduled_time, a.duration_min, a.status, a.created_at))
        self.conn.commit()

    def get_appointment(self, appointment_id: str, store_id: str) -> Optional[Appointment]:
        row = self.conn.execute(
            "SELECT * FROM dl_appointment WHERE appointment_id=? AND store_id=?",
            (appointment_id, store_id)).fetchone()
        return Appointment(**dict(row)) if row else None

    def list_appointments_by_date(self, store_id: str, date: str) -> List[Appointment]:
        rows = self.conn.execute(
            "SELECT * FROM dl_appointment WHERE store_id=? AND scheduled_date=? ORDER BY scheduled_time",
            (store_id, date)).fetchall()
        return [Appointment(**dict(r)) for r in rows]

    def list_appointments(self, store_id: str, date: str = None) -> List[Appointment]:
        """跨店隔离: 只返回指定门店的预约"""
        if date:
            return self.list_appointments_by_date(store_id, date)
        rows = self.conn.execute(
            "SELECT * FROM dl_appointment WHERE store_id=? ORDER BY scheduled_date, scheduled_time",
            (store_id,)).fetchall()
        return [Appointment(**dict(r)) for r in rows]

    def transition_appointment(self, appointment_id: str, store_id: str, target_status: str, member_id: str):
        a = self.get_appointment(appointment_id, store_id)
        if not a:
            raise ValueError(f"E-SCOPE: appointment not found in store {store_id}")
        if not a.can_transition(target_status):
            raise ValueError(f"E-STATE: {a.status} cannot transition to {target_status}")
        self.conn.execute(
            "INSERT INTO dl_appointment_transition (transition_id,appointment_id,store_id,from_status,to_status,transitioned_by) VALUES (?,?,?,?,?,?)",
            (f"atr_{appointment_id}_{int(time.time())}", appointment_id, store_id, a.status, target_status, member_id))
        self.conn.execute(
            "UPDATE dl_appointment SET status=? WHERE appointment_id=? AND store_id=?",
            (target_status, appointment_id, store_id))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # DailyCustomerTask (B1/B2/C1-C3)
    # ═══════════════════════════════════════════════════════
    def insert_task(self, t: DailyCustomerTask):
        self.conn.execute(
            "INSERT INTO dl_daily_customer_task (task_id,store_id,customer_id,assigned_member_id,task_date,status,priority,scenario_type,batch_id,frozen_at,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.task_id, t.store_id, t.customer_id, t.assigned_member_id, t.task_date,
             t.status, t.priority, t.scenario_type, t.batch_id, t.frozen_at,
             t.idempotency_key, t.created_at, t.updated_at))
        self.conn.commit()

    def get_task(self, task_id: str, store_id: str) -> Optional[DailyCustomerTask]:
        row = self.conn.execute(
            "SELECT * FROM dl_daily_customer_task WHERE task_id=? AND store_id=?",
            (task_id, store_id)).fetchone()
        return DailyCustomerTask(**dict(row)) if row else None

    def list_tasks_by_member(self, store_id: str, member_id: str, task_date: str) -> List[DailyCustomerTask]:
        rows = self.conn.execute(
            "SELECT * FROM dl_daily_customer_task WHERE store_id=? AND assigned_member_id=? AND task_date=? ORDER BY task_id",
            (store_id, member_id, task_date)).fetchall()
        return [DailyCustomerTask(**dict(r)) for r in rows]

    def list_tasks_by_store(self, store_id: str, task_date: str) -> List[DailyCustomerTask]:
        rows = self.conn.execute(
            "SELECT * FROM dl_daily_customer_task WHERE store_id=? AND task_date=? ORDER BY assigned_member_id,task_id",
            (store_id, task_date)).fetchall()
        return [DailyCustomerTask(**dict(r)) for r in rows]

    def list_tasks(self, store_id: str, task_date: str = None, member_id: str = None) -> List[DailyCustomerTask]:
        """跨店隔离: 只返回指定门店的任务"""
        if member_id and task_date:
            return self.list_tasks_by_member(store_id, member_id, task_date)
        if task_date:
            return self.list_tasks_by_store(store_id, task_date)
        rows = self.conn.execute(
            "SELECT * FROM dl_daily_customer_task WHERE store_id=? ORDER BY task_date,task_id",
            (store_id,)).fetchall()
        return [DailyCustomerTask(**dict(r)) for r in rows]

    def update_task_status(self, task_id: str, store_id: str, new_status: str):
        """更新任务状态(受frozen约束)"""
        task = self.get_task(task_id, store_id)
        if not task:
            raise ValueError(f"E-SCOPE: task not found in store {store_id}")
        if task.frozen:
            raise ValueError("E-STATE: task is frozen, cannot modify")
        self.conn.execute(
            "UPDATE dl_daily_customer_task SET status=? WHERE task_id=? AND store_id=?",
            (new_status, task_id, store_id))
        self.conn.commit()

    def freeze_task(self, task_id: str, store_id: str):
        """F1冻结窗: 标记frozen_at,之后不可修改"""
        from app.daily_loop.models import utcnow_iso
        self.conn.execute(
            "UPDATE dl_daily_customer_task SET frozen_at=? WHERE task_id=? AND store_id=?",
            (utcnow_iso(), task_id, store_id))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # ServiceFeedback (B4)
    # ═══════════════════════════════════════════════════════
    def insert_feedback(self, f: ServiceFeedback):
        self.conn.execute(
            "INSERT INTO dl_service_feedback (feedback_id,store_id,task_id,member_id,feedback_items_json,feedback_items_count,data_gap_flags_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (f.feedback_id, f.store_id, f.task_id, f.member_id,
             json.dumps(f.feedback_items), len(f.feedback_items),
             json.dumps(f.data_gap_flags) if hasattr(f, 'data_gap_flags') else None, f.created_at))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # ConsumptionEvent (B5) — 委托给V0.1.2 HoldingsStore
    # ═══════════════════════════════════════════════════════
    def insert_consumption_record(self, c: ConsumptionEvent):
        """在AUTH库记录消耗事件元数据(不含余额,余额由V0.1.2管理)"""
        self.conn.execute(
            "INSERT INTO dl_consumption_event (event_id,store_id,customer_id,member_id,item_id,quantity,task_id,idempotency_key,upstream_contract,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (c.event_id, c.store_id, c.customer_id, c.member_id, c.item_id, c.quantity,
             c.task_id, c.idempotency_key, c.upstream_contract, c.created_at))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # EmployeeDailyStatus (C7)
    # ═══════════════════════════════════════════════════════
    def insert_employee_status(self, e: EmployeeDailyStatus):
        self.conn.execute(
            "INSERT INTO dl_employee_daily_status (status_id,store_id,member_id,status_date,daily_status,note,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (e.status_id, e.store_id, e.member_id, e.status_date, e.daily_status, e.note,
             e.idempotency_key, e.created_at))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # StoreDailySummary (C5/F2)
    # ═══════════════════════════════════════════════════════
    def upsert_daily_summary(self, s: StoreDailySummary):
        self.conn.execute(
            "INSERT OR REPLACE INTO dl_store_daily_summary (summary_id,store_id,summary_date,total_tasks,completed_tasks,skipped_tasks,total_consumption,total_feedback,auto_generated,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s.summary_id, s.store_id, s.summary_date, s.total_tasks, s.completed_tasks,
             s.skipped_tasks, s.total_consumption, s.total_feedback, s.auto_generated, s.created_at))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # OperationJournal — 追加attempt,不UPDATE
    # ═══════════════════════════════════════════════════════
    def create_journal(self, j: OperationJournal):
        self.conn.execute(
            "INSERT INTO dl_operation_journal (journal_id,store_id,operation_type,resource_id,status,initiated_by,idempotency_key,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (j.journal_id, j.store_id, j.operation_type, j.resource_id,
             j.status, j.initiated_by, j.idempotency_key, j.created_at, j.completed_at))
        self.conn.commit()

    def append_journal_step(self, step: OperationJournalStep):
        """追加步骤,不UPDATE已有步骤(append-only由TRIGGER强制)
        UNIQUE(journal_id, step_name, attempt_number)防止同一attempt重复写入"""
        self.conn.execute(
            "INSERT INTO dl_operation_journal_step (step_id,journal_id,step_order,step_name,attempt_number,step_status,step_result,error_code,error_message,idempotency_key,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (step.step_id, step.journal_id, step.step_order, step.step_name,
             step.attempt_number, step.step_status, step.step_result, step.error_code,
             step.error_message, step.idempotency_key, step.created_at, step.completed_at))
        self.conn.commit()

    def replay_journal_terminal_status(self, journal_id: str, store_id: str) -> str:
        """重放步骤确定终态(不依赖UPDATE头表)
        规则: 取每个step_order的最新attempt,按重放逻辑确定终态"""
        journal = self.conn.execute(
            "SELECT * FROM dl_operation_journal WHERE journal_id=? AND store_id=?",
            (journal_id, store_id)).fetchone()
        if not journal:
            raise ValueError(f"E-SCOPE: journal {journal_id} not found in store {store_id}")
        steps = self.conn.execute(
            "SELECT * FROM dl_operation_journal_step WHERE journal_id=? ORDER BY step_order, attempt_number",
            (journal_id,)).fetchall()
        if not steps:
            return 'pending'
        # 按step_order分组,取每个order的最新attempt
        latest = {}
        for s in steps:
            order = s['step_order']
            if order not in latest or s['attempt_number'] > latest[order]['attempt_number']:
                latest[order] = s
        statuses = [latest[k]['step_status'] for k in sorted(latest.keys())]
        # 重放逻辑
        if all(s == 'completed' for s in statuses):
            return 'completed'
        if any(s == 'compensated' for s in statuses):
            return 'partial_failed'
        if any(s == 'manual_review' for s in statuses):
            return 'manual_review'
        if any(s == 'failed' for s in statuses):
            return 'partial_failed'
        return 'pending'

    # ═══════════════════════════════════════════════════════
    # AuditLog
    # ═══════════════════════════════════════════════════════
    def insert_audit(self, a: AuditLog):
        self.conn.execute(
            "INSERT INTO dl_audit_log (audit_id,store_id,member_id,action_type,resource_type,resource_id,detail_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (a.audit_id, a.store_id, a.member_id, a.action_type, a.resource_type,
             a.resource_id, a.detail_json, a.created_at))
        self.conn.commit()

    # ═══════════════════════════════════════════════════════
    # ServiceScript / PlatformCopy / CopyReview / CopyUsageFeedback / PrivateTargetedMessage / KnowledgeCandidateProjection
    # ═══════════════════════════════════════════════════════
    def insert_service_script(self, s: ServiceScript):
        self.conn.execute(
            "INSERT INTO dl_service_script (script_id,store_id,task_id,member_id,customer_id,scene_type,today_goal,recommended_opening,professional_questions,professional_explanation,emotional_value_phrases,recommended_phrases,prohibited_phrases,script_data_json,next_action,stop_condition,evidence_refs,rights_status,risk_level,enhanced,human_editable,auto_send,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.script_id, s.store_id, s.task_id, s.member_id, s.customer_id, s.scene_type,
             s.today_goal, s.recommended_opening, s.professional_questions, s.professional_explanation,
             s.emotional_value_phrases, s.recommended_phrases, s.prohibited_phrases, None,
             s.next_action, s.stop_condition, s.evidence_refs, s.rights_status, s.risk_level,
             s.enhanced, s.human_editable, s.auto_send, s.idempotency_key, s.created_at))
        self.conn.commit()

    def insert_platform_copy(self, c: PlatformCopy):
        self.conn.execute(
            "INSERT INTO dl_platform_copy (copy_id,store_id,platform,content_brief,content_json,copy_data_json,status,enhanced,human_editable,auto_send,compliance_status,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c.copy_id, c.store_id, c.platform, c.content_brief, c.content_json,
             None, 'draft', c.enhanced, c.human_editable, c.auto_send, c.compliance_status,
             c.idempotency_key, c.created_at))
        self.conn.commit()

    def insert_copy_review(self, r: CopyReview):
        self.conn.execute(
            "INSERT INTO dl_copy_review (review_id,copy_id,store_id,reviewer_member_id,decision,review_result,review_note,comments,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r.review_id, r.copy_id, r.store_id, r.reviewer_member_id,
             r.decision, r.review_result, r.review_note, r.comments, r.idempotency_key, r.created_at))
        self.conn.commit()

    def insert_copy_feedback(self, f: CopyUsageFeedback):
        self.conn.execute(
            "INSERT INTO dl_copy_usage_feedback (feedback_id,copy_id,store_id,member_id,feedback_type,evidence_status,feedback_data,evidence_data_json,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f.feedback_id, f.copy_id, f.store_id, f.member_id, f.feedback_type,
             f.evidence_status, f.feedback_data, None, f.idempotency_key, f.created_at))
        self.conn.commit()

    def insert_targeted_message(self, m: PrivateTargetedMessage):
        """安全写入口: denied/withdrawn不可落库"""
        if m.consent_status in ('denied', 'withdrawn'):
            raise ValueError(f'E-CONSENT: consent_status={m.consent_status} blocks write')
        self.conn.execute(
            "INSERT INTO dl_private_targeted_message (message_id,store_id,customer_id,member_id,message_content,consent_status,frequency_count,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (m.message_id, m.store_id, m.customer_id, m.member_id, m.message_content,
             m.consent_status, m.frequency_count, m.created_at))
        self.conn.commit()

    def insert_projection(self, k: KnowledgeCandidateProjection):
        """安全写入口: F3 fail-closed — pii_scanned必须True, sample_size>=5"""
        err = k.validate_fail_closed()
        if err:
            raise ValueError(f'E-SCHEMA: {err}')
        self.conn.execute(
            "INSERT INTO dl_knowledge_candidate_projection (projection_id,store_id,projection_type,aggregated_data,pii_scanned,sample_size,source_event_hashes,projection_rule_version,allowlist_policy_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (k.projection_id, k.store_id, k.projection_type, k.aggregated_data, k.pii_scanned,
             k.sample_size, k.source_event_hashes, k.projection_rule_version,
             k.allowlist_policy_version, k.created_at))
        self.conn.commit()

    def close(self):
        self.conn.close()


# VaultRepository moved to vault_repository.py (single authoritative entry)
