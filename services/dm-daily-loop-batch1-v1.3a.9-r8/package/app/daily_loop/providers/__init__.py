#!/usr/bin/env python3
"""
DM Daily Loop Batch 1 — Provider Interfaces

Frozen contract interfaces for external systems.
Default: fail-closed. No real connections.

upstream: dm-daily-contracts-v0.0.4.1 (FROZEN)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
import json


class CandidateIngestProvider(ABC):
    """F3: KnowledgeCandidateProjection → 18080 Flywheel card/score链"""

    @abstractmethod
    def submit_projection(self, projection_data: dict) -> dict:
        """Submit to /flywheel/card → /flywheel/score → queue → approval.
        Returns: {submitted: bool, provider_status: str, flywheel_card_id: str|None}
        """
        pass


class CustomerHoldingsProvider(ABC):
    """B5: ConsumptionEvent → dm-customer-holdings-v0.1.2"""

    @abstractmethod
    def confirm_consumption(self, store_id: str, customer_id: str, item_id: str,
                           quantity: int, member_id: str, idempotency_key: str) -> dict:
        """Returns: {entry_id: str, balance_remaining: int, upstream_contract: str}
        Raises if quantity <= 0 or idempotency conflict."""
        pass

    @abstractmethod
    def get_balance(self, store_id: str, customer_id: str, item_id: str) -> dict:
        """Returns: {item_id, quantity_remaining, last_updated}"""
        pass


class InMemoryCandidateProvider(CandidateIngestProvider):
    """Test-only in-memory provider. Fail-closed by default."""

    def __init__(self):
        self.submitted = []

    def submit_projection(self, projection_data: dict) -> dict:
        # fail-closed: validate before submit
        if not projection_data.get('pii_scanned'):
            return {'submitted': False, 'provider_status': 'rejected_pii_not_scanned', 'flywheel_card_id': None}
        if projection_data.get('sample_size', 0) < 5:
            return {'submitted': False, 'provider_status': 'rejected_sample_below_threshold', 'flywheel_card_id': None}

        card_id = f'card_{len(self.submitted):06d}'
        self.submitted.append({'card_id': card_id, 'data': projection_data})
        return {'submitted': True, 'provider_status': 'submitted', 'flywheel_card_id': card_id}


class InMemoryHoldingsProvider(CustomerHoldingsProvider):
    """Test-only in-memory holdings provider."""

    def __init__(self):
        self._balances = {}  # (store_id, customer_id, item_id) → quantity
        self._entries = []  # consumption entries
        self._idempotency_keys = {}  # key → entry_id

    def _ensure_balance(self, store_id: str, customer_id: str, item_id: str):
        key = (store_id, customer_id, item_id)
        if key not in self._balances:
            self._balances[key] = 100  # default for testing
        return self._balances[key]

    def confirm_consumption(self, store_id: str, customer_id: str, item_id: str,
                           quantity: int, member_id: str, idempotency_key: str) -> dict:
        if quantity <= 0:
            raise ValueError(f'quantity must be positive (got {quantity})')

        # Idempotency check
        if idempotency_key in self._idempotency_keys:
            existing_id = self._idempotency_keys[idempotency_key]
            return {'entry_id': existing_id, 'balance_remaining': self._balances.get((store_id, customer_id, item_id), 0),
                    'upstream_contract': 'dm-customer-holdings-v0.1.2', 'idempotent': True}

        self._ensure_balance(store_id, customer_id, item_id)
        key = (store_id, customer_id, item_id)

        if self._balances[key] < quantity:
            raise ValueError(f'insufficient balance: {self._balances[key]} < {quantity}')

        self._balances[key] -= quantity
        entry_id = f'entry_{len(self._entries):06d}'
        self._entries.append({'entry_id': entry_id, 'store_id': store_id, 'customer_id': customer_id,
                             'item_id': item_id, 'quantity': quantity, 'member_id': member_id})
        self._idempotency_keys[idempotency_key] = entry_id

        return {'entry_id': entry_id, 'balance_remaining': self._balances[key],
                'upstream_contract': 'dm-customer-holdings-v0.1.2', 'idempotent': False}

    def get_balance(self, store_id: str, customer_id: str, item_id: str) -> dict:
        key = (store_id, customer_id, item_id)
        return {'item_id': item_id, 'quantity_remaining': self._balances.get(key, 0),
                'last_updated': '2026-07-15T00:00:00Z'}


class FailClosedCandidateProvider(CandidateIngestProvider):
    """Production default: fail-closed, no real connection."""

    def submit_projection(self, projection_data: dict) -> dict:
        return {'submitted': False, 'provider_status': 'provider_not_configured', 'flywheel_card_id': None}


class FailClosedHoldingsProvider(CustomerHoldingsProvider):
    """Production default: fail-closed, no real connection."""

    def confirm_consumption(self, *args, **kwargs) -> dict:
        raise RuntimeError('CustomerHoldingsProvider not configured (fail-closed)')

    def get_balance(self, *args, **kwargs) -> dict:
        raise RuntimeError('CustomerHoldingsProvider not configured (fail-closed)')
