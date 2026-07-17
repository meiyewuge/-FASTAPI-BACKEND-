#!/usr/bin/env python3
"""
DM Daily Loop V1.1 — B5 Holdings Bridge

B5(消耗确认)的唯一事实源是dm-customer-holdings-v0.1.2。
本桥接器将V0.1.2的HoldingsStore适配为Daily Loop的Provider接口。
不创建"默认余额100"的假数据。
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / 'vendor'))
from dm_customer_holdings.store import HoldingsStore
from dm_customer_holdings.contract import CONTRACT_VERSION as HOLDINGS_VERSION
from dm_customer_holdings.api import LedgerEntry, TransactionType, Customer, HoldingItem

from app.daily_loop.providers import CustomerHoldingsProvider


class V012HoldingsBridge(CustomerHoldingsProvider):
    """B5唯一消耗确认入口 — 委托给V0.1.2 HoldingsStore"""

    def __init__(self, holdings_db_path: str):
        self.store = HoldingsStore(holdings_db_path)
        self._contract_version = HOLDINGS_VERSION

    @property
    def contract_version(self) -> str:
        return self._contract_version

    def setup_customer_with_balance(self, store_id: str, customer_id: str, item_id: str,
                                     initial_quantity: int = 10) -> None:
        """注册顾客+项目+初始采购(用于测试环境)"""
        try:
            self.store.register_customer(Customer(
                customer_id=customer_id, store_id=store_id,
                display_name=customer_id, contact_auth='granted'))
        except Exception:
            pass  # already exists
        try:
            self.store.register_item(HoldingItem(
                item_id=item_id, store_id=store_id,
                item_type='service', item_name='test item', unit='session'))
        except Exception:
            pass  # already exists
        # Initial purchase
        ts = datetime.now(timezone.utc).isoformat()
        entry = LedgerEntry(
            entry_id=f"ent_{uuid.uuid4().hex[:16]}",
            transaction_id=f"tx_{uuid.uuid4().hex[:16]}",
            customer_id=customer_id, item_id=item_id, store_id=store_id,
            transaction_type=TransactionType.PURCHASE,
            quantity=initial_quantity, timestamp=ts, operator='system', note='initial purchase')
        self.store.append_entry(entry)

    def confirm_consumption(self, store_id: str, customer_id: str, item_id: str,
                           quantity: int, member_id: str,
                           idempotency_key: str = None) -> dict:
        """B5消耗确认 — 通过V0.1.2 HoldingsStore.append_entry_atomic"""
        entry = LedgerEntry(
            entry_id=f"ent_{uuid.uuid4().hex[:16]}",
            transaction_id=idempotency_key or f"tx_{uuid.uuid4().hex[:16]}",
            customer_id=customer_id,
            item_id=item_id,
            store_id=store_id,
            transaction_type=TransactionType.CONSUME,
            quantity=quantity,
            timestamp=datetime.now(timezone.utc).isoformat(),
            operator=member_id,
            note='B5 consumption confirm',
        )
        try:
            result = self.store.append_entry_atomic(
                entry,
                balance_check_fn=self._make_balance_checker(quantity)
            )
            return {
                'entry_id': result.entry_id,
                'confirmed': True,
                'balance_remaining': self._calc_balance(store_id, customer_id, item_id),
                'hash_chain_valid': self.store.verify_hash_chain(customer_id, item_id, store_id),
                'upstream_contract': self._contract_version,
            }
        except Exception as e:
            return {
                'confirmed': False,
                'error': str(e),
                'upstream_contract': self._contract_version,
            }

    def _check_balance(self, store_id: str, customer_id: str, item_id: str, quantity: int):
        """余额检查回调"""
        bal = self._calc_balance(store_id, customer_id, item_id)
        if bal < quantity:
            raise ValueError(f'Insufficient balance: {bal} < {quantity}')

    def _make_balance_checker(self, quantity: int):
        """创建balance_check_fn — V0.1.2签名: fn(entries_list) -> (ok, error_msg)"""
        def checker(entries):
            bal = 0
            from dm_customer_holdings.api import TransactionType
            for e in entries:
                if e.transaction_type == TransactionType.PURCHASE:
                    bal += e.quantity
                elif e.transaction_type == TransactionType.CONSUME:
                    bal -= e.quantity
                elif e.transaction_type == TransactionType.ADJUST:
                    bal += e.quantity
            if bal < quantity:
                return (False, f'Insufficient balance: {bal} < {quantity}')
            return (True, None)
        return checker

    def get_balance(self, store_id: str, customer_id: str, item_id: str) -> dict:
        """查询余额 — 从流水重放"""
        bal = self._calc_balance(store_id, customer_id, item_id)
        return {
            'item_id': item_id,
            'quantity_remaining': bal,
            'upstream_contract': self._contract_version
        }

    def verify_hash_chain(self, store_id: str, customer_id: str, item_id: str) -> bool:
        """验证哈希链完整性"""
        return self.store.verify_hash_chain(customer_id, item_id, store_id)

    def _calc_balance(self, store_id: str, customer_id: str, item_id: str) -> int:
        """从流水重放余额"""
        entries = self.store.get_entries_by_customer_item(customer_id, item_id, store_id)
        balance = 0
        for e in entries:
            if e.transaction_type == TransactionType.PURCHASE:
                balance += e.quantity
            elif e.transaction_type == TransactionType.CONSUME:
                balance -= e.quantity
            elif e.transaction_type == TransactionType.ADJUST:
                balance += e.quantity  # 冲正加回
        return balance
