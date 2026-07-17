#!/usr/bin/env python3
"""
DM Daily Loop Batch 1 — Domain Models
16 domain objects as pure Python dataclasses.
No ORM dependency. SQLite via stdlib sqlite3.

upstream: dm-daily-contracts-v0.0.4.1 (FROZEN)
upstream: dm-customer-holdings-v0.1.2 (FROZEN)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List
import json


def utcnow_iso() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ═══════════════════════════════════════════════════════
# 1. StoreMember (G1-G4 身份根)
# ═══════════════════════════════════════════════════════
@dataclass
class StoreMember:
    member_id: str
    store_id: str
    auth_user_id: str
    role: str  # owner/manager/staff
    display_alias: str
    status: str = 'invited'  # invited/active/disabled/left
    invited_by: Optional[str] = None
    invited_at: str = field(default_factory=utcnow_iso)
    activated_at: Optional[str] = None
    disabled_at: Optional[str] = None
    left_at: Optional[str] = None
    audit_reason: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    # G4 状态机: 禁止自行提权/同级提权/跨店/left复活
    VALID_TRANSITIONS = {
        'invited': {'active', 'disabled'},
        'active': {'disabled', 'left'},
        'disabled': {'active'},
        'left': set(),  # 终态
    }

    def can_transition(self, target: str) -> bool:
        return target in self.VALID_TRANSITIONS.get(self.status, set())

    def is_role_allowed_for_invite(self, caller_role: str) -> bool:
        """G3: manager只能邀请staff, owner可邀请manager/staff"""
        if caller_role == 'owner':
            return self.role in ('manager', 'staff')
        if caller_role == 'manager':
            return self.role == 'staff'
        return False


# ═══════════════════════════════════════════════════════
# 2. CustomerProfile (A1/A2)
# ═══════════════════════════════════════════════════════
@dataclass
class CustomerProfile:
    customer_id: str
    store_id: str
    display_name: str  # 假名
    stage: str = 'new'  # new/active/dormant/lost/won_back
    contact_auth: str = 'unknown'  # unknown/granted/denied/withdrawn
    contact_auth_updated_at: str = field(default_factory=utcnow_iso)
    assigned_member_id: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    def can_contact(self) -> bool:
        """denied和withdrawn均硬短路"""
        return self.contact_auth == 'granted'


# ═══════════════════════════════════════════════════════
# 3. Appointment (A3-A6)
# ═══════════════════════════════════════════════════════
@dataclass
class Appointment:
    appointment_id: str
    store_id: str
    customer_id: str
    member_id: Optional[str] = None
    scheduled_date: str = ''
    scheduled_time: Optional[str] = None
    duration_min: int = 60
    status: str = 'scheduled'  # scheduled/rescheduled/cancelled/arrived/no_show/completed
    source: str = 'manual'
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    VALID_TRANSITIONS = {
        'scheduled': {'rescheduled', 'cancelled', 'arrived'},
        'rescheduled': {'rescheduled', 'cancelled', 'arrived'},
        'arrived': {'completed', 'no_show'},
        'completed': set(),
        'no_show': set(),
        'cancelled': set(),
    }

    def can_transition(self, target: str) -> bool:
        return target in self.VALID_TRANSITIONS.get(self.status, set())


# ═══════════════════════════════════════════════════════
# 4. DailyCustomerTask (B1/B2/C1-C3)
# ═══════════════════════════════════════════════════════
@dataclass
class DailyCustomerTask:
    task_id: str
    store_id: str
    customer_id: str
    task_date: str
    assigned_member_id: Optional[str] = None
    status: str = 'draft'  # draft/reviewed/assigned/in_progress/completed/skipped
    priority: int = 5
    scenario_type: Optional[str] = None
    batch_id: Optional[str] = None
    frozen_at: Optional[str] = None
    @property
    def frozen(self) -> bool:
        return self.frozen_at is not None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)

    VALID_TRANSITIONS = {
        'draft': {'reviewed'},
        'reviewed': {'assigned'},
        'assigned': {'in_progress', 'skipped'},
        'in_progress': {'completed', 'skipped'},
        'completed': set(),
        'skipped': set(),
    }

    def can_transition(self, target: str) -> bool:
        return target in self.VALID_TRANSITIONS.get(self.status, set())


# ═══════════════════════════════════════════════════════
# 5. TaskExecution (B3)
# ═══════════════════════════════════════════════════════
@dataclass
class TaskExecution:
    execution_id: str
    task_id: str
    member_id: str
    started_at: str = field(default_factory=utcnow_iso)
    completed_at: Optional[str] = None
    idempotency_key: Optional[str] = None


# ═══════════════════════════════════════════════════════
# 6. ServiceFeedback (B4 — 最多7项打钩)
# ═══════════════════════════════════════════════════════
@dataclass
class ServiceFeedback:
    feedback_id: str
    store_id: str
    task_id: str
    member_id: str
    feedback_items: List[dict] = field(default_factory=list)  # [{check_item, checked}]
    data_gap_flags: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    MAX_ITEMS = 7
    VALID_CHECK_ITEMS = {
        'service_completed', 'customer_satisfied', 'products_recommended',
        'next_visit_suggested', 'feedback_collected', 'aftercare_reminded',
        'problem_handled',
    }

    @property
    def feedback_items_count(self) -> int:
        return len(self.feedback_items)

    def validate(self) -> Optional[str]:
        if len(self.feedback_items) > self.MAX_ITEMS:
            return f'B4: feedback_items exceeds maxItems:7 (got {len(self.feedback_items)})'
        items_set = set()
        for item in self.feedback_items:
            if item.get('check_item') not in self.VALID_CHECK_ITEMS:
                return f'B4: invalid check_item: {item.get("check_item")}'
            key = (item['check_item'], item.get('checked', False))
            if key in items_set:
                return f'B4: duplicate check_item: {item["check_item"]}'
            items_set.add(key)
        return None


# ═══════════════════════════════════════════════════════
# 7. ConsumptionEvent (B5 — 引用持有资产)
# ═══════════════════════════════════════════════════════
@dataclass
class ConsumptionEvent:
    event_id: str
    store_id: str
    customer_id: str
    member_id: str
    item_id: str
    quantity: int  # 正数
    task_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    upstream_contract: str = 'dm-customer-holdings-v0.1.2'
    created_at: str = field(default_factory=utcnow_iso)

    def validate(self) -> Optional[str]:
        if self.quantity <= 0:
            return f'B5: quantity must be positive (got {self.quantity})'
        return None


# ═══════════════════════════════════════════════════════
# 8. CustomerSignal (B6)
# ═══════════════════════════════════════════════════════
@dataclass
class CustomerSignal:
    signal_id: str
    store_id: str
    customer_id: str
    member_id: str
    signal_type: str  # repurchase_intent/churn_risk/complaint/low_engagement/expiring_soon/high_value_action/rejection/other
    signal_value: Optional[str] = None
    evidence_status: str = 'correlational'  # correlational/causal/estimated
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 9. EmployeeDailyStatus (C7 — 禁医疗诊断字段)
# ═══════════════════════════════════════════════════════
@dataclass
class EmployeeDailyStatus:
    status_id: str
    store_id: str
    member_id: str
    status_date: str
    daily_status: str  # on_duty/off_duty/attention_flag
    note: Optional[str] = None  # 自愿提供,禁医疗诊断
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    FORBIDDEN_NOTE_KEYWORDS = {'诊断', '病情', '抑郁症', '焦虑症', '服药', '病历',
        '心脏病', '高血压', '糖尿病', '癫痫', '精神分裂', '甲亢', '甲减', '乙肝', '艾滋病',
        '冠心病', '肝炎', '肾病', '胃病', '哮喘', '过敏', '皮肤病', '传染'}

    def validate(self) -> Optional[str]:
        if self.note:
            for kw in self.FORBIDDEN_NOTE_KEYWORDS:
                if kw in self.note:
                    return f'C7: forbidden medical keyword in note: {kw}'
        return None


# ═══════════════════════════════════════════════════════
# 10. StoreDailySummary (C5/F2)
# ═══════════════════════════════════════════════════════
@dataclass
class StoreDailySummary:
    summary_id: str
    store_id: str
    summary_date: str
    total_tasks: int = 0
    completed_tasks: int = 0
    skipped_tasks: int = 0
    total_consumption: int = 0
    total_feedback: int = 0
    auto_generated: int = 0  # 0=manual, 1=F2 auto
    quickfill_data: Optional[str] = None  # C5速填JSON
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 11. ServiceScript (E1 — 16字段话术卡)
# ═══════════════════════════════════════════════════════
@dataclass
class ServiceScript:
    script_id: str
    store_id: str
    member_id: str
    scene_type: str
    customer_id: Optional[str] = None
    task_id: Optional[str] = None
    today_goal: Optional[str] = None
    recommended_opening: Optional[str] = None
    professional_questions: Optional[str] = None  # JSON
    professional_explanation: Optional[str] = None
    emotional_value_phrases: Optional[str] = None  # JSON
    recommended_phrases: Optional[str] = None  # JSON
    prohibited_phrases: Optional[str] = None  # JSON
    next_action: Optional[str] = None
    stop_condition: Optional[str] = None
    evidence_refs: Optional[str] = None  # JSON
    rights_status: str = 'unknown'
    risk_level: str = 'low'  # low/medium/high
    enhanced: int = 0  # 0=模板,1=AI增强
    human_editable: int = 1
    auto_send: int = 0  # 常量false
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 12. PlatformCopy (E3-E6 — 四平台专用结构)
# ═══════════════════════════════════════════════════════
@dataclass
class PlatformCopy:
    copy_id: str
    store_id: str
    platform: str  # xhs/wechat_channel/douyin/private
    content_brief: str  # 不含PII
    content_json: str  # 平台专用结构JSON
    enhanced: int = 0
    human_editable: int = 1
    auto_send: int = 0
    compliance_status: str = 'pending_review'  # pending_review/approved/rejected/archived/published
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 13. CopyReview (E9)
# ═══════════════════════════════════════════════════════
@dataclass
class CopyReview:
    review_id: str
    copy_id: str
    store_id: str
    reviewer_member_id: str
    decision: str  # approved/rejected/archived
    review_result: Optional[str] = None
    review_note: Optional[str] = None
    comments: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 14. CopyUsageFeedback (E10)
# ═══════════════════════════════════════════════════════
@dataclass
class CopyUsageFeedback:
    feedback_id: str
    copy_id: str
    store_id: str
    member_id: str
    feedback_type: str  # adoption/customer_reaction/platform_metric/complaint
    evidence_status: str = 'correlational'  # correlational/causal/estimated
    feedback_data: Optional[str] = None  # JSON
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 15. PrivateTargetedMessage (E12 — consent硬检)
# ═══════════════════════════════════════════════════════
@dataclass
class PrivateTargetedMessage:
    message_id: str
    store_id: str
    customer_id: str
    member_id: str
    message_content: str
    consent_status: str  # unknown/granted/denied/withdrawn
    auto_send: int = 0  # 常量false
    frequency_count: int = 0
    sent_at: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    def can_send(self) -> bool:
        """denied和withdrawn硬短路"""
        return self.consent_status == 'granted'


# ═══════════════════════════════════════════════════════
# 16. KnowledgeCandidateProjection (F3 — fail-closed)
# ═══════════════════════════════════════════════════════
@dataclass
class KnowledgeCandidateProjection:
    projection_id: str
    store_id: str
    projection_type: str
    aggregated_data: str  # JSON (去标识)
    pii_scanned: bool  # 必填
    sample_size: int  # 必填, >=5
    source_event_hashes: str  # JSON数组
    projection_rule_version: str
    allowlist_policy_version: str
    provider_status: str = 'pending'
    flywheel_card_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)

    MIN_SAMPLE_SIZE = 5

    def validate_fail_closed(self) -> Optional[str]:
        """F3 fail-closed: 所有字段必须存在且合法"""
        if not self.pii_scanned:
            return 'F3: pii_scanned must be True (fail-closed)'
        if self.sample_size < self.MIN_SAMPLE_SIZE:
            return f'F3: sample_size must be >= {self.MIN_SAMPLE_SIZE} (got {self.sample_size})'
        if not self.source_event_hashes:
            return 'F3: source_event_hashes must not be empty'
        if not self.projection_rule_version:
            return 'F3: projection_rule_version must not be empty'
        if not self.allowlist_policy_version:
            return 'F3: allowlist_policy_version must not be empty'
        return None


# ═══════════════════════════════════════════════════════
# Saga: OperationJournal (头表+步骤表)
# ═══════════════════════════════════════════════════════
@dataclass
class OperationJournal:
    journal_id: str
    store_id: str
    operation_type: str  # customer_create/erasure/member_invite等
    initiated_by: str  # member_id
    resource_id: Optional[str] = None
    status: str = 'pending'  # pending/completed/partial_failed/manual_review
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    completed_at: Optional[str] = None


@dataclass
class OperationJournalStep:
    """Journal步骤 — append-only,不允许UPDATE。
    每次执行追加新行(attempt_number递增),终态按步骤重放确定。
    UNIQUE(journal_id, step_name, attempt_number)防止同一attempt写入两次。"""
    step_id: str
    journal_id: str
    step_order: int
    step_name: str
    attempt_number: int = 1
    step_status: str = 'pending'  # pending/completed/failed/skipped/compensated
    step_result: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)
    completed_at: Optional[str] = None


# ═══════════════════════════════════════════════════════
# Vault (加密PII,系统零访问)
# ═══════════════════════════════════════════════════════
@dataclass
class IdentityVault:
    vault_id: str
    subject_type: str  # customer/member
    subject_id: str
    store_id: str
    encrypted_phone: Optional[str] = None
    encrypted_name: Optional[str] = None
    encrypted_id_card: Optional[str] = None
    key_version: int = 1
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)


@dataclass
class VaultAccessLog:
    access_id: str
    vault_id: str
    access_type: str  # read/write/key_rotate
    access_reason: str  # 必填
    accessor_member_id: Optional[str] = None  # 系统服务=NULL(但系统零访问)
    access_result: str = 'granted'  # granted/denied/error
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# AuditLog
# ═══════════════════════════════════════════════════════
@dataclass
class AuditLog:
    audit_id: str
    store_id: str
    member_id: str
    action_type: str  # vault_access/manager_override/consumption_reversal/auth_change/role_transition
    resource_type: str
    resource_id: str
    detail_json: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# Infrastructure objects (not part of 16 domain objects)
# ═══════════════════════════════════════════════════════

@dataclass
class AppointmentTransition:
    """A6: 预约状态迁移记录"""
    transition_id: str
    appointment_id: str
    store_id: str
    from_status: str
    to_status: str
    transitioned_by: str  # member_id
    audit_reason: Optional[str] = None
    created_at: str = field(default_factory=utcnow_iso)


@dataclass
class CustomerHolding:
    """B5: 顾客持有资产引用(轻量引用,不复制V0.1.2余额真相)"""
    holding_id: str
    store_id: str
    customer_id: str
    item_id: str
    upstream_entry_id: Optional[str] = None  # V0.1.2流水ID
    sync_status: str = 'pending'  # pending/synced/failed
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)


# ═══════════════════════════════════════════════════════
# 16 domain objects list (for verification)
# ═══════════════════════════════════════════════════════
DOMAIN_OBJECTS = [
    StoreMember, CustomerProfile, Appointment, DailyCustomerTask,
    TaskExecution, ServiceFeedback, ConsumptionEvent, CustomerSignal,
    EmployeeDailyStatus, StoreDailySummary, ServiceScript, PlatformCopy,
    CopyReview, CopyUsageFeedback, PrivateTargetedMessage, KnowledgeCandidateProjection,
]

assert len(DOMAIN_OBJECTS) == 16, f"Expected 16 domain objects, got {len(DOMAIN_OBJECTS)}"
