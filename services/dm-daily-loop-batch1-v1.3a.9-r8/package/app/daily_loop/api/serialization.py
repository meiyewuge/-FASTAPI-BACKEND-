#!/usr/bin/env python3
"""Contract-exact serialization for the C1-B read endpoints.

Fields are pinned to the C1-A-R2 contract and the real dataclasses in
app/daily_loop/models. No vault plaintext / PII fields are ever serialized here
(tasks and appointments carry no phone/name/id-card).
"""
from __future__ import annotations
from app.daily_loop.models import DailyCustomerTask, Appointment

# The exact fields the contract exposes, in order. Kept explicit so an accidental
# model change cannot silently widen the response surface.
TASK_FIELDS = (
    'task_id', 'store_id', 'customer_id', 'task_date', 'assigned_member_id',
    'status', 'priority', 'scenario_type', 'batch_id', 'frozen_at',
    'created_at', 'updated_at',
)

APPOINTMENT_FIELDS = (
    'appointment_id', 'store_id', 'customer_id', 'member_id', 'scheduled_date',
    'scheduled_time', 'duration_min', 'status', 'source',
    'created_at', 'updated_at',
)


def serialize_task(t: DailyCustomerTask) -> dict:
    return {f: getattr(t, f) for f in TASK_FIELDS}


def serialize_appointment(a: Appointment) -> dict:
    return {f: getattr(a, f) for f in APPOINTMENT_FIELDS}
