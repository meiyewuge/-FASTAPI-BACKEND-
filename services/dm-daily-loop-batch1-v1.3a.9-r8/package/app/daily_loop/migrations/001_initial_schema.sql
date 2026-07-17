-- DM Daily Loop Batch 1 — Initial Schema DDL
-- 21 AUTH tables (VAULT 2 tables moved to vault_001_initial.sql)
-- Database: SQLite (AUTHORITATIVE_DB, dev=test, prod=workbench_test.db)
-- lifecycle_state: DESIGNED → CODED (Batch 1)
-- upstream: dm-daily-contracts-v0.0.4.1 (FROZEN)
-- upstream: dm-customer-holdings-v0.1.2 (FROZEN)

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ═══════════════════════════════════════════════════════
-- G组: StoreMember 身份根 (G1-G4)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_store_member (
    member_id       TEXT PRIMARY KEY,          -- 假名ID (M-xxx格式)
    store_id        TEXT NOT NULL,              -- 门店ID
    auth_user_id    TEXT NOT NULL,              -- 关联auth_user
    role            TEXT NOT NULL CHECK(role IN ('owner','manager','staff')),
    display_alias   TEXT NOT NULL,              -- 假名(只允许字母数字_-)
    status          TEXT NOT NULL DEFAULT 'invited' CHECK(status IN ('invited','active','disabled','left')),
    invited_by      TEXT,                       -- 邀请人member_id
    invited_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    activated_at    TEXT,
    disabled_at     TEXT,
    left_at         TEXT,
    audit_reason    TEXT,                       -- 状态变更审计理由
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(store_id, auth_user_id)              -- 一个auth_user在一家店只能有一个member身份
);
CREATE INDEX IF NOT EXISTS idx_store_member_store ON dl_store_member(store_id, status);
CREATE INDEX IF NOT EXISTS idx_store_member_auth ON dl_store_member(auth_user_id);

-- ═══════════════════════════════════════════════════════
-- A组: 顾客与预约 (A1-A7)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_customer_profile (
    customer_id     TEXT PRIMARY KEY,          -- 假名ID (C-xxx格式)
    store_id        TEXT NOT NULL,
    display_name    TEXT NOT NULL,              -- 假名(只允许字母数字_-)
    stage           TEXT NOT NULL DEFAULT 'new' CHECK(stage IN ('new','active','dormant','lost','won_back')),
    contact_auth    TEXT NOT NULL DEFAULT 'unknown' CHECK(contact_auth IN ('unknown','granted','denied','withdrawn')),
    contact_auth_updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    assigned_member_id TEXT,                    -- 分配到的员工member_id
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_customer_profile_store ON dl_customer_profile(store_id, stage);
CREATE INDEX IF NOT EXISTS idx_customer_profile_member ON dl_customer_profile(assigned_member_id);

-- Semantic cross-store: assigned_member_id must be in same store as customer
CREATE TRIGGER IF NOT EXISTS trg_customer_profile_assigned_member_cross_store
    BEFORE INSERT ON dl_customer_profile
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.assigned_member_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.assigned_member_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: assigned_member does not belong to this store')
        END;
    END;

CREATE TABLE IF NOT EXISTS dl_appointment (
    appointment_id  TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    member_id       TEXT,                       -- 指定服务成员
    scheduled_date  TEXT NOT NULL,              -- ISO date
    scheduled_time  TEXT,                       -- HH:MM
    duration_min    INTEGER DEFAULT 60,
    status          TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','rescheduled','cancelled','arrived','no_show','completed')),
    source          TEXT DEFAULT 'manual',      -- manual/batch_import
    idempotency_key TEXT,                       -- 幂等键
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_appointment_store_date ON dl_appointment(store_id, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_appointment_customer ON dl_appointment(customer_id);

-- Cross-store isolation trigger for dl_appointment
CREATE TRIGGER IF NOT EXISTS trg_appointment_cross_store_check
    BEFORE INSERT ON dl_appointment
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_customer_profile
                WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_store_member
                WHERE member_id = NEW.member_id AND store_id = NEW.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;


CREATE TABLE IF NOT EXISTS dl_appointment_transition (
    transition_id   TEXT PRIMARY KEY,
    appointment_id  TEXT NOT NULL,
    from_status     TEXT NOT NULL,
    to_status       TEXT NOT NULL,
    transitioned_by TEXT NOT NULL,              -- 操作人member_id
    store_id        TEXT NOT NULL,
    audit_reason    TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (appointment_id) REFERENCES dl_appointment(appointment_id),
    FOREIGN KEY (transitioned_by) REFERENCES dl_store_member(member_id)
);
CREATE INDEX IF NOT EXISTS idx_appt_transition_appt ON dl_appointment_transition(appointment_id);

-- ═══════════════════════════════════════════════════════
-- B组: 员工工作台 (B1-B7)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_daily_customer_task (
    task_id          TEXT PRIMARY KEY,
    store_id         TEXT NOT NULL,
    customer_id      TEXT NOT NULL,
    assigned_member_id TEXT,                    -- 分配到的员工
    task_date        TEXT NOT NULL,              -- 任务日期
    status           TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reviewed','assigned','in_progress','completed','skipped')),
    priority         INTEGER DEFAULT 5,
    scenario_type    TEXT,                       -- 场景类型(18种之一)
    batch_id         TEXT,                       -- F1批任务ID
    frozen_at        TEXT,                       -- 冻结时间戳
    idempotency_key  TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id),
    FOREIGN KEY (assigned_member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_task_store_date ON dl_daily_customer_task(store_id, task_date, status);

-- Cross-store isolation trigger for dl_daily_customer_task
CREATE TRIGGER IF NOT EXISTS trg_task_cross_store_check
    BEFORE INSERT ON dl_daily_customer_task
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_customer_profile
                WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
        SELECT CASE
            WHEN NEW.assigned_member_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM dl_store_member
                WHERE member_id = NEW.assigned_member_id AND store_id = NEW.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;
CREATE INDEX IF NOT EXISTS idx_task_member ON dl_daily_customer_task(assigned_member_id, task_date);

CREATE TABLE IF NOT EXISTS dl_task_execution (
    execution_id    TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at    TEXT,
    idempotency_key TEXT,
    FOREIGN KEY (task_id) REFERENCES dl_daily_customer_task(task_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_task_exec_task ON dl_task_execution(task_id);

CREATE TABLE IF NOT EXISTS dl_service_feedback (
    feedback_id     TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    feedback_items_json TEXT NOT NULL,           -- JSON数组,最多7项
    feedback_items_count INTEGER NOT NULL CHECK(feedback_items_count >= 0 AND feedback_items_count <= 7),
    data_gap_flags  TEXT,                        -- 缺失数据标记
    data_gap_flags_json TEXT,                    -- alias for repo compat
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (task_id) REFERENCES dl_daily_customer_task(task_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_feedback_task ON dl_service_feedback(task_id);

CREATE TRIGGER IF NOT EXISTS trg_feedback_cross_store_check
    BEFORE INSERT ON dl_service_feedback
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_daily_customer_task
                WHERE task_id = NEW.task_id AND store_id = NEW.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: task does not belong to this store')
        END;
    END;


CREATE TABLE IF NOT EXISTS dl_consumption_event (
    event_id             TEXT PRIMARY KEY,
    store_id             TEXT NOT NULL,
    customer_id          TEXT NOT NULL,
    task_id              TEXT,
    member_id            TEXT NOT NULL,
    item_id              TEXT NOT NULL,
    quantity             INTEGER NOT NULL CHECK(quantity > 0),
    hash_prev            TEXT,
    hash_curr            TEXT,
    reversal_of_event_id TEXT,
    idempotency_key      TEXT,
    upstream_contract    TEXT NOT NULL DEFAULT 'dm-customer-holdings-v0.1.2',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_consumption_customer ON dl_consumption_event(customer_id, item_id);

CREATE TABLE IF NOT EXISTS dl_customer_signal (
    signal_id       TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    signal_type     TEXT NOT NULL CHECK(signal_type IN ('repurchase_intent','churn_risk','complaint','low_engagement','expiring_soon','high_value_action','rejection','other')),
    signal_value    TEXT,                        -- 信号值/描述
    evidence_status TEXT NOT NULL DEFAULT 'correlational' CHECK(evidence_status IN ('correlational','causal','estimated')),
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_signal_customer ON dl_customer_signal(customer_id, signal_type);

-- ═══════════════════════════════════════════════════════
-- C组: 店长工作台 (C1-C7)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_employee_daily_status (
    status_id       TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    status_date     TEXT NOT NULL,
    daily_status    TEXT NOT NULL CHECK(daily_status IN ('on_duty','off_duty','attention_flag')),
    note            TEXT,                        -- 自愿提供的排班/负荷/需关注标记(禁医疗诊断)
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(store_id, member_id, status_date)
);
CREATE INDEX IF NOT EXISTS idx_emp_status_store_date ON dl_employee_daily_status(store_id, status_date);

CREATE TABLE IF NOT EXISTS dl_store_daily_summary (
    summary_id      TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    summary_date    TEXT NOT NULL,
    total_tasks     INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    skipped_tasks   INTEGER DEFAULT 0,
    total_consumption INTEGER DEFAULT 0,
    total_feedback  INTEGER DEFAULT 0,
    auto_generated  INTEGER NOT NULL DEFAULT 0,  -- 0=manual, 1=F2 auto
    quickfill_data  TEXT,                        -- C5速填JSON
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(store_id, summary_date)
);
CREATE INDEX IF NOT EXISTS idx_summary_store_date ON dl_store_daily_summary(store_id, summary_date);

-- ═══════════════════════════════════════════════════════
-- E组: 双文案引擎 (E1-E12)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_service_script (
    script_id       TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    task_id         TEXT,
    member_id       TEXT NOT NULL,
    customer_id     TEXT,                        -- 假名ID
    scene_type      TEXT NOT NULL,               -- 18场景之一
    today_goal      TEXT,
    recommended_opening TEXT,
    professional_questions TEXT,                 -- JSON数组
    professional_explanation TEXT,
    emotional_value_phrases TEXT,                -- JSON数组
    recommended_phrases TEXT,                    -- JSON数组
    prohibited_phrases TEXT,                     -- JSON数组
    script_data_json TEXT,                       -- full script JSON (alias for repo compat)
    next_action     TEXT,
    stop_condition  TEXT,
    evidence_refs   TEXT,                        -- JSON数组
    rights_status   TEXT DEFAULT 'unknown',
    risk_level      TEXT DEFAULT 'low' CHECK(risk_level IN ('low','medium','high')),
    enhanced        INTEGER NOT NULL DEFAULT 0,  -- 0=模板,1=AI增强
    human_editable  INTEGER NOT NULL DEFAULT 1,
    auto_send       INTEGER NOT NULL DEFAULT 0,  -- 常量false
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_script_store ON dl_service_script(store_id, scene_type);

CREATE TABLE IF NOT EXISTS dl_platform_copy (
    copy_id         TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    platform        TEXT NOT NULL CHECK(platform IN ('xhs','wechat_channel','douyin','private')),
    content_brief   TEXT NOT NULL,
    content_json    TEXT NOT NULL,
    copy_data_json  TEXT,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','pending_review','approved','rejected','published','archived')),
    enhanced        INTEGER NOT NULL DEFAULT 0,
    human_editable  INTEGER NOT NULL DEFAULT 1,
    auto_send       INTEGER NOT NULL DEFAULT 0,
    compliance_status TEXT DEFAULT 'pending_review' CHECK(compliance_status IN ('pending_review','approved','rejected','archived','published')),
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_copy_store_platform ON dl_platform_copy(store_id, platform, compliance_status);

CREATE TABLE IF NOT EXISTS dl_copy_review (
    review_id       TEXT PRIMARY KEY,
    copy_id         TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    reviewer_member_id TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK(decision IN ('approved','rejected','archived')),
    review_result   TEXT,
    review_note     TEXT,
    comments        TEXT,
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (copy_id) REFERENCES dl_platform_copy(copy_id),
    FOREIGN KEY (reviewer_member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);

CREATE TABLE IF NOT EXISTS dl_copy_usage_feedback (
    feedback_id     TEXT PRIMARY KEY,
    copy_id         TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    feedback_type   TEXT NOT NULL CHECK(feedback_type IN ('adoption','customer_reaction','platform_metric','complaint')),
    evidence_status TEXT NOT NULL DEFAULT 'correlational' CHECK(evidence_status IN ('correlational','causal','estimated')),
    feedback_data       TEXT,                -- JSON
    evidence_data_json TEXT,                -- alias
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (copy_id) REFERENCES dl_platform_copy(copy_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_copy_feedback_copy ON dl_copy_usage_feedback(copy_id, feedback_type);

CREATE TABLE IF NOT EXISTS dl_private_targeted_message (
    message_id      TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    message_content TEXT NOT NULL,
    consent_status  TEXT NOT NULL CHECK(consent_status IN ('unknown','granted','denied','withdrawn')),
    auto_send       INTEGER NOT NULL DEFAULT 0,
    frequency_count INTEGER NOT NULL DEFAULT 0,
    sent_at         TEXT,
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_targeted_msg_customer ON dl_private_targeted_message(customer_id);

-- ═══════════════════════════════════════════════════════
-- F组: 每日编排 (F1-F3)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_knowledge_candidate_projection (
    projection_id       TEXT PRIMARY KEY,
    store_id            TEXT NOT NULL,
    projection_type     TEXT NOT NULL,
    aggregated_data     TEXT NOT NULL,           -- JSON (去标识)
    pii_scanned         INTEGER NOT NULL DEFAULT 0, -- 必填,fail-closed
    sample_size         INTEGER NOT NULL CHECK(sample_size >= 5), -- 最小5
    source_event_hashes TEXT NOT NULL,           -- JSON数组
    projection_rule_version TEXT NOT NULL,
    allowlist_policy_version TEXT NOT NULL,
    provider_status     TEXT DEFAULT 'pending',
    flywheel_card_id    TEXT,                    -- 落飞轮后的card_id
    idempotency_key     TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(idempotency_key)
);

-- ═══════════════════════════════════════════════════════
-- Saga: OperationJournal (头表+步骤表)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_operation_journal (
    journal_id      TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    operation_type  TEXT NOT NULL,               -- customer_create/erasure/member_invite等
    resource_id     TEXT,                        -- 操作的资源ID
    status          TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','partial_failed','manual_review')),
    initiated_by    TEXT NOT NULL,               -- member_id
    idempotency_key TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at    TEXT,
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_journal_store ON dl_operation_journal(store_id, status);

CREATE TABLE IF NOT EXISTS dl_operation_journal_step (
    step_id         TEXT PRIMARY KEY,
    journal_id      TEXT NOT NULL,
    step_order      INTEGER NOT NULL,
    step_name       TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    step_status     TEXT NOT NULL DEFAULT 'pending' CHECK(step_status IN ('pending','completed','failed','skipped','compensated')),
    step_result     TEXT,                        -- JSON
    error_code      TEXT,                        -- 机器错误码
    error_message   TEXT,
    idempotency_key TEXT,                        -- 步骤幂等键
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    completed_at    TEXT,
    FOREIGN KEY (journal_id) REFERENCES dl_operation_journal(journal_id),
    UNIQUE(journal_id, step_name, attempt_number)  -- 防止同一步骤同一attempt写入两次
);
CREATE INDEX IF NOT EXISTS idx_journal_step_journal ON dl_operation_journal_step(journal_id, step_order, attempt_number);

-- ═══════════════════════════════════════════════════════
-- 审计日志
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_audit_log (
    audit_id        TEXT PRIMARY KEY,
    store_id        TEXT NOT NULL,
    member_id       TEXT NOT NULL,
    action_type     TEXT NOT NULL,               -- vault_access/manager_override/consumption_reversal/auth_change/role_transition
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    detail_json     TEXT,                        -- JSON (含reason等)
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (member_id) REFERENCES dl_store_member(member_id)
);
CREATE INDEX IF NOT EXISTS idx_audit_store ON dl_audit_log(store_id, action_type, created_at);

-- ═══════════════════════════════════════════════════════
-- 顾客持有(引用upstream,本地只存引用)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dl_customer_holding (
    holding_id      TEXT PRIMARY KEY,            -- 本地引用ID
    store_id        TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    upstream_contract TEXT NOT NULL DEFAULT 'dm-customer-holdings-v0.1.2',
    upstream_entry_id TEXT,                      -- 上游entry_id
    last_synced_at  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    FOREIGN KEY (customer_id) REFERENCES dl_customer_profile(customer_id)
);
CREATE INDEX IF NOT EXISTS idx_holding_customer ON dl_customer_holding(customer_id, item_id);

-- ═══════════════════════════════════════════════════════
-- VAULT tables moved to vault_001_initial.sql (物理拆库)


-- ═══════════════════════════════════════════════════════
-- 不可变流水TRIGGER (dl_consumption_event)
-- ═══════════════════════════════════════════════════════
CREATE TRIGGER IF NOT EXISTS trg_consumption_no_update
    BEFORE UPDATE ON dl_consumption_event
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'dl_consumption_event is immutable: UPDATE forbidden');
    END;

CREATE TRIGGER IF NOT EXISTS trg_consumption_no_delete
    BEFORE DELETE ON dl_consumption_event
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'dl_consumption_event is immutable: DELETE forbidden');
    END;

-- Saga步骤表append-only
CREATE TRIGGER IF NOT EXISTS trg_journal_step_no_update
    BEFORE UPDATE ON dl_operation_journal_step
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'dl_operation_journal_step is append-only: UPDATE forbidden');
    END;

CREATE TRIGGER IF NOT EXISTS trg_journal_step_no_delete
    BEFORE DELETE ON dl_operation_journal_step
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'dl_operation_journal_step is append-only: DELETE forbidden');
    END;

-- ═══════════════════════════════════════════════════════
-- 表计数验证
-- ═══════════════════════════════════════════════════════
-- AUTH(21): dl_store_member, dl_customer_profile, dl_appointment,
--   dl_appointment_transition, dl_daily_customer_task, dl_task_execution,
--   dl_service_feedback, dl_consumption_event, dl_customer_signal,
--   dl_employee_daily_status, dl_store_daily_summary, dl_service_script,
--   dl_platform_copy, dl_copy_review, dl_copy_usage_feedback,
--   dl_private_targeted_message, dl_knowledge_candidate_projection,
--   dl_operation_journal, dl_operation_journal_step, dl_audit_log,
--   dl_customer_holding
-- VAULT 2 tables: see vault_001_initial.sql (物理拆库)
-- TOTAL AUTH: 21 + VAULT: 2 = 23


-- ═══════════════════════════════════════════════════════
-- 全域跨店隔离TRIGGER (补充)
-- ═══════════════════════════════════════════════════════

-- dl_customer_signal: 信号必须引用本店顾客
CREATE TRIGGER IF NOT EXISTS trg_signal_cross_store_check
    BEFORE INSERT ON dl_customer_signal
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_customer_profile WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
    END;

-- dl_consumption_event: 消耗必须引用本店顾客和成员
CREATE TRIGGER IF NOT EXISTS trg_consumption_cross_store_check
    BEFORE INSERT ON dl_consumption_event
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_customer_profile WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.member_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;

-- dl_service_script: 话术必须引用本店顾客(如果customer_id不为空)
CREATE TRIGGER IF NOT EXISTS trg_script_cross_store_check
    BEFORE INSERT ON dl_service_script
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.customer_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dl_customer_profile WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
    END;

-- dl_platform_copy: 文案必须属于本店
CREATE TRIGGER IF NOT EXISTS trg_copy_cross_store_check
    BEFORE INSERT ON dl_platform_copy
    FOR EACH ROW
    BEGIN
        -- platform_copy has no customer_id (E3-E6 structural absence, Q9)
        -- Only validate store_id is non-empty
        SELECT CASE
            WHEN NEW.store_id IS NULL OR LENGTH(NEW.store_id) = 0
            THEN RAISE(ABORT, 'E-SCHEMA: store_id is required')
        END;
    END;

-- dl_private_targeted_message: 定向消息必须引用本店顾客
CREATE TRIGGER IF NOT EXISTS trg_targeted_msg_cross_store_check
    BEFORE INSERT ON dl_private_targeted_message
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_customer_profile WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.member_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;

-- dl_employee_daily_status: 员工状态必须引用本店成员
CREATE TRIGGER IF NOT EXISTS trg_emp_status_cross_store_check
    BEFORE INSERT ON dl_employee_daily_status
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.member_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;

-- dl_knowledge_candidate_projection: 投影必须属于本店
CREATE TRIGGER IF NOT EXISTS trg_projection_cross_store_check
    BEFORE INSERT ON dl_knowledge_candidate_projection
    FOR EACH ROW
    BEGIN
        -- F3 is system-only, store_id is validated at service layer
        -- No member_id in this table, only store_id check needed
        SELECT CASE
            WHEN NEW.store_id IS NULL OR LENGTH(NEW.store_id) = 0
            THEN RAISE(ABORT, 'E-SCHEMA: store_id is required')
        END;
    END;

-- dl_copy_usage_feedback: 反馈必须引用本店文案
CREATE TRIGGER IF NOT EXISTS trg_copy_feedback_cross_store_check
    BEFORE INSERT ON dl_copy_usage_feedback
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_platform_copy WHERE copy_id = NEW.copy_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: copy does not belong to this store')
        END;
    END;

-- dl_copy_review: 审核必须引用本店文案
CREATE TRIGGER IF NOT EXISTS trg_copy_review_cross_store_check
    BEFORE INSERT ON dl_copy_review
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_platform_copy WHERE copy_id = NEW.copy_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: copy does not belong to this store')
        END;
    END;

-- ═══════════════════════════════════════════════════════
-- 补充跨店TRIGGER (V1.3A.1: GPT审计遗漏的5张表)
-- ═══════════════════════════════════════════════════════

-- dl_appointment_transition: 迁移必须引用本店预约
CREATE TRIGGER IF NOT EXISTS trg_appt_transition_cross_store_check
    BEFORE INSERT ON dl_appointment_transition
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_appointment WHERE appointment_id = NEW.appointment_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: appointment does not belong to this store')
        END;
    END;

-- dl_task_execution: 执行必须引用本店任务
CREATE TRIGGER IF NOT EXISTS trg_task_exec_cross_store_check
    BEFORE INSERT ON dl_task_execution
    FOR EACH ROW
    BEGIN
        -- task_execution has no store_id; resolve via task's store_id and member's store_id
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_daily_customer_task t
                JOIN dl_store_member m ON m.member_id = NEW.member_id
                WHERE t.task_id = NEW.task_id AND t.store_id = m.store_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: task and member must be in same store')
        END;
    END;

-- dl_customer_holding: 持有引用必须引用本店顾客
CREATE TRIGGER IF NOT EXISTS trg_holding_cross_store_check
    BEFORE INSERT ON dl_customer_holding
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_customer_profile WHERE customer_id = NEW.customer_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')
        END;
    END;

-- dl_audit_log: 审计必须引用本店成员
CREATE TRIGGER IF NOT EXISTS trg_audit_cross_store_check
    BEFORE INSERT ON dl_audit_log
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.member_id AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: member does not belong to this store')
        END;
    END;

-- dl_operation_journal: journal必须引用本店initiator
CREATE TRIGGER IF NOT EXISTS trg_journal_cross_store_check
    BEFORE INSERT ON dl_operation_journal
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (SELECT 1 FROM dl_store_member WHERE member_id = NEW.initiated_by AND store_id = NEW.store_id)
            THEN RAISE(ABORT, 'E-SCOPE: journal initiator does not belong to this store')
        END;
    END;

-- dl_operation_journal_step: 步骤必须引用本店journal
CREATE TRIGGER IF NOT EXISTS trg_journal_step_cross_store_check
    BEFORE INSERT ON dl_operation_journal_step
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM dl_operation_journal j
                WHERE j.journal_id = NEW.journal_id
            )
            THEN RAISE(ABORT, 'E-SCOPE: journal does not exist')
        END;
    END;
