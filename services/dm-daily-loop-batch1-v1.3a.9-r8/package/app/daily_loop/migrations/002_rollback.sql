-- DM Daily Loop Batch 1 — Rollback DDL
-- Reverses 001_initial_schema.sql
-- WARNING: This drops all tables. Use only in dev/test.

PRAGMA foreign_keys=OFF;

DROP TRIGGER IF EXISTS trg_consumption_no_update;
DROP TRIGGER IF EXISTS trg_consumption_no_delete;
DROP TRIGGER IF EXISTS trg_journal_step_no_update;
DROP TRIGGER IF EXISTS trg_journal_step_no_delete;

DROP TABLE IF EXISTS dl_vault_access_log;
DROP TABLE IF EXISTS dl_identity_vault;
DROP TABLE IF EXISTS dl_customer_holding;
DROP TABLE IF EXISTS dl_audit_log;
DROP TABLE IF EXISTS dl_operation_journal_step;
DROP TABLE IF EXISTS dl_operation_journal;
DROP TABLE IF EXISTS dl_knowledge_candidate_projection;
DROP TABLE IF EXISTS dl_private_targeted_message;
DROP TABLE IF EXISTS dl_copy_usage_feedback;
DROP TABLE IF EXISTS dl_copy_review;
DROP TABLE IF EXISTS dl_platform_copy;
DROP TABLE IF EXISTS dl_service_script;
DROP TABLE IF EXISTS dl_store_daily_summary;
DROP TABLE IF EXISTS dl_employee_daily_status;
DROP TABLE IF EXISTS dl_customer_signal;
DROP TABLE IF EXISTS dl_consumption_event;
DROP TABLE IF EXISTS dl_service_feedback;
DROP TABLE IF EXISTS dl_task_execution;
DROP TABLE IF EXISTS dl_daily_customer_task;
DROP TABLE IF EXISTS dl_appointment_transition;
DROP TABLE IF EXISTS dl_appointment;
DROP TABLE IF EXISTS dl_customer_profile;
DROP TABLE IF EXISTS dl_store_member;

PRAGMA foreign_keys=ON;
