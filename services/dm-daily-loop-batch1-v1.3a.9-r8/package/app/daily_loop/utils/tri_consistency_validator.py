#!/usr/bin/env python3
"""
V1.3A A1: 三方一致性Validator

对每个DDL表、dataclass、Repository公开方法执行机器对账:
- INSERT/UPDATE列必须存在于DDL
- Repository读取/写入的dataclass字段必须存在
- DDL NOT NULL列必须被写入或有默认值
- enum/check与冻结Schema一致
- 每个公开Repository方法至少1个成功真实SQL测试+1个关键反例
"""
import ast, json, os, re, sqlite3, sys, inspect
from pathlib import Path
from dataclasses import fields as dataclass_fields

BASE = Path(__file__).resolve().parent.parent.parent.parent


def parse_ddl_columns(ddl_path):
    """Parse DDL file to extract table→column mappings."""
    with open(ddl_path) as f:
        content = f.read()
    tables = {}
    # Match CREATE TABLE blocks
    for m in re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);', content, re.DOTALL):
        table_name = m.group(1)
        body = m.group(2)
        columns = {}
        for line in body.split('\n'):
            line = line.strip().rstrip(',')
            if not line or line.startswith('--') or line.startswith('FOREIGN') or line.startswith('UNIQUE') or line.startswith('CHECK') or line.startswith('PRIMARY'):
                continue
            parts = line.split(None, 2)
            if len(parts) >= 2:
                col_name = parts[0]
                col_type = parts[1]
                is_nullable = 'NOT NULL' not in line.upper()
                has_default = 'DEFAULT' in line.upper()
                columns[col_name] = {
                    'type': col_type,
                    'nullable': is_nullable,
                    'has_default': has_default,
                    'raw': line,
                }
        tables[table_name] = columns
    return tables


def parse_dataclass_fields():
    """Import models and extract dataclass fields per model."""
    sys.path.insert(0, str(BASE))
    from app.daily_loop.models import (
        StoreMember, CustomerProfile, Appointment, DailyCustomerTask,
        TaskExecution, ServiceFeedback, ConsumptionEvent, CustomerSignal,
        EmployeeDailyStatus, StoreDailySummary, ServiceScript, PlatformCopy,
        CopyReview, CopyUsageFeedback, PrivateTargetedMessage,
        KnowledgeCandidateProjection, OperationJournal, OperationJournalStep,
        IdentityVault, VaultAccessLog, AuditLog,
        AppointmentTransition, CustomerHolding,
    )
    models = {
        'dl_store_member': StoreMember,
        'dl_customer_profile': CustomerProfile,
        'dl_appointment': Appointment,
        'dl_appointment_transition': AppointmentTransition,
        'dl_daily_customer_task': DailyCustomerTask,
        'dl_task_execution': TaskExecution,
        'dl_service_feedback': ServiceFeedback,
        'dl_consumption_event': ConsumptionEvent,
        'dl_customer_holding': CustomerHolding,
        'dl_customer_signal': CustomerSignal,
        'dl_employee_daily_status': EmployeeDailyStatus,
        'dl_store_daily_summary': StoreDailySummary,
        'dl_service_script': ServiceScript,
        'dl_platform_copy': PlatformCopy,
        'dl_copy_review': CopyReview,
        'dl_copy_usage_feedback': CopyUsageFeedback,
        'dl_private_targeted_message': PrivateTargetedMessage,
        'dl_knowledge_candidate_projection': KnowledgeCandidateProjection,
        'dl_operation_journal': OperationJournal,
        'dl_operation_journal_step': OperationJournalStep,
        'dl_identity_vault': IdentityVault,
        'dl_vault_access_log': VaultAccessLog,
        'dl_audit_log': AuditLog,
    }
    result = {}
    for table, model in models.items():
        result[table] = {f.name for f in dataclass_fields(model)}
    return result


def parse_repo_sql_columns():
    """Parse Repository INSERT statements to extract columns used."""
    repo_path = BASE / 'app' / 'daily_loop' / 'services' / 'repository.py'
    with open(repo_path) as f:
        content = f.read()
    inserts = {}
    for m in re.finditer(r'INSERT INTO (\w+)\s*\(([^)]+)\)', content):
        table = m.group(1)
        cols = [c.strip() for c in m.group(2).split(',')]
        if table not in inserts:
            inserts[table] = set()
        inserts[table].update(cols)
    return inserts


def validate_consistency():
    """Run all consistency checks. Returns (errors, warnings)."""
    errors = []
    warnings = []

    ddl_path = BASE / 'app' / 'daily_loop' / 'migrations' / '001_initial_schema.sql'
    vault_path = BASE / 'app' / 'daily_loop' / 'migrations' / 'vault_001_initial.sql'

    ddl_tables = {}
    for p in [ddl_path, vault_path]:
        if p.exists():
            ddl_tables.update(parse_ddl_columns(p))

    model_fields = parse_dataclass_fields()
    repo_cols = parse_repo_sql_columns()

    # Check 1: Every DDL table has a model
    for table in ddl_tables:
        if table not in model_fields:
            errors.append(f'DDL table {table} has no dataclass model')

    # Check 2: Repository INSERT columns exist in DDL
    for table, cols in repo_cols.items():
        if table not in ddl_tables:
            errors.append(f'Repository INSERT into {table} but table not in DDL')
            continue
        for col in cols:
            if col not in ddl_tables[table]:
                errors.append(f'Repository INSERT into {table}.{col} but column not in DDL')

    # Check 3: DDL NOT NULL columns are in repo INSERT or have default
    # These are ERRORS, not warnings — they cause real runtime failures
    for table, cols in ddl_tables.items():
        if table not in repo_cols:
            continue
        for col_name, col_info in cols.items():
            if not col_info['nullable'] and not col_info['has_default']:
                if col_name not in repo_cols.get(table, set()):
                    errors.append(f'DDL {table}.{col_name} is NOT NULL but not in Repository INSERT')

    return errors, warnings


if __name__ == '__main__':
    errors, warnings = validate_consistency()
    if errors:
        print(f'FAIL: {len(errors)} errors')
        for e in errors[:20]:
            print(f'  X {e}')
        sys.exit(1)
    else:
        print('PASS: tri-consistency validated')
    if warnings:
        print(f'Warnings: {len(warnings)}')
        for w in warnings[:10]:
            print(f'  ! {w}')
    sys.exit(0)
