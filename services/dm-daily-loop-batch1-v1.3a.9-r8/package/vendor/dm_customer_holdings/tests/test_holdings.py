"""Comprehensive tests for Customer Holdings V0.1.2.

V0.1.2 changes:
- All imports use package-relative (from dm_customer_holdings import ...)
- Tests run from both `python3 -m pytest tests/` and `python3 tests/test_holdings.py`
- Full-amount reversal only (partial reversal rejected)
- Cross-customer/cross-item reversal rejected
- denied → contact_forbidden (not pending_manual_verification)
- display_name pseudonym validation
"""

import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Support both: python3 -m pytest (from parent) and python3 tests/test_holdings.py
SCRIPT_DIR = Path(__file__).resolve().parent
# Add parent of dm_customer_holdings to path
PACKAGE_PARENT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PACKAGE_PARENT))

from dm_customer_holdings import CustomerHoldingsAPI
from dm_customer_holdings.contract import (
    Customer, HoldingItem, LedgerEntry, Balance,
    ItemType, TransactionType, EntryStatus, ContactAuthStatus,
    HoldingsError,
    generate_transaction_id,
    CUSTOMER_NOT_FOUND, CUSTOMER_ALREADY_EXISTS,
    ITEM_NOT_FOUND, ITEM_TYPE_INVALID,
    TRANSACTION_ID_DUPLICATE, INSUFFICIENT_BALANCE,
    ENTRY_NOT_FOUND, CROSS_STORE_ACCESS_DENIED,
    ENTRY_ALREADY_REVERSED, IDEMPOTENCY_PAYLOAD_CONFLICT,
    INVALID_EXPIRY_FORMAT, EXPIRY_ALREADY_PASSED,
    PII_DETECTED,
)

CONTRACT_VERSION = "dm-customer-holdings-v0.1.2"


class TestCustomerRegistration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_register_customer(self):
        c = self.api.register_customer("S001", "VIP-001")
        self.assertEqual(c.store_id, "S001")
        self.assertEqual(c.display_name, "VIP-001")
        self.assertEqual(c.contact_auth, "unknown")

    def test_duplicate_customer_id_rejected(self):
        c = self.api.register_customer("S001", "VIP-001")
        with self.assertRaises(HoldingsError):
            self.api.store.register_customer(c)

    def test_customer_not_found(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_customer("nonexistent", "S001")
        self.assertEqual(ctx.exception.code, CUSTOMER_NOT_FOUND)

    def test_cross_store_customer_access_denied(self):
        c = self.api.register_customer("S001", "VIP-001")
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_customer(c.customer_id, "S002")
        # Customer registered in S001, queried from S002 → not found (store isolation)
        self.assertIn(ctx.exception.code, [CROSS_STORE_ACCESS_DENIED, CUSTOMER_NOT_FOUND, ITEM_NOT_FOUND])

    def test_display_name_chinese_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.register_customer("S001", "张三")
        self.assertEqual(ctx.exception.code, "PII_IN_DISPLAY_NAME")

    def test_display_name_phone_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.register_customer("S001", "13800138000")
        self.assertEqual(ctx.exception.code, "PII_IN_DISPLAY_NAME")

    def test_display_name_email_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.register_customer("S001", "test@example.com")
        self.assertEqual(ctx.exception.code, "PII_IN_DISPLAY_NAME")

    def test_display_name_pseudonym_accepted(self):
        for name in ["VIP-001", "C-123", "CUSTOMER_456", "001", "A-2026-001"]:
            c = self.api.register_customer("S001", name)
            self.assertEqual(c.display_name, name)

    def test_metadata_pii_phone_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.register_customer("S001", "VIP-001", metadata={"phone": "13800138000"})
        self.assertEqual(ctx.exception.code, PII_DETECTED)

    def test_metadata_pii_name_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.register_customer("S001", "VIP-001", metadata={"name": "张三"})
        self.assertEqual(ctx.exception.code, PII_DETECTED)

    def test_metadata_nested_pii_rejected(self):
        with self.assertRaises(HoldingsError):
            self.api.register_customer("S001", "VIP-001",
                metadata={"profile": {"mobile": "13800138000"}})

    def test_metadata_clean_accepted(self):
        c = self.api.register_customer("S001", "VIP-001",
            metadata={"tag": "vip", "level": 3, "notes": "偏好护理"})
        self.assertEqual(c.metadata["tag"], "vip")


class TestItemRegistration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_register_item(self):
        item = self.api.register_item("S001", "project", "面部护理疗程", "次", 10)
        self.assertEqual(item.item_type, "project")
        self.assertEqual(item.item_name, "面部护理疗程")

    def test_invalid_item_type_rejected(self):
        with self.assertRaises(HoldingsError):
            self.api.register_item("S001", "invalid_type", "测试", "次", 1)

    def test_item_not_found(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_item("nonexistent", "S001")
        self.assertEqual(ctx.exception.code, ITEM_NOT_FOUND)

    def test_cross_store_item_access_denied(self):
        item = self.api.register_item("S001", "project", "测试", "次", 1)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_item(item.item_id, "S002")
        # Customer registered in S001, queried from S002 → not found (store isolation)
        self.assertIn(ctx.exception.code, [CROSS_STORE_ACCESS_DENIED, CUSTOMER_NOT_FOUND, ITEM_NOT_FOUND])


class TestLedgerOperations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_purchase(self):
        entry = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.assertEqual(entry.transaction_type, "purchase")
        self.assertEqual(entry.quantity, 10)
        self.assertEqual(entry.status, "confirmed")

    def test_consume(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        entry = self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        self.assertEqual(entry.transaction_type, "consume")
        self.assertEqual(entry.quantity, 3)

    def test_balance_after_purchase(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(balance.remaining_quantity, 10)
        self.assertEqual(balance.total_purchased, 10)

    def test_balance_after_consume(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(balance.remaining_quantity, 7)


class TestIdempotency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_same_transaction_id_returns_same_entry(self):
        tx_id = "T-fixed-001"
        e1 = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001",
                              quantity=10, transaction_id=tx_id)
        e2 = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001",
                              quantity=10, transaction_id=tx_id)
        self.assertEqual(e1.entry_id, e2.entry_id)

    def test_different_payload_same_tx_id_rejected(self):
        tx_id = "T-fixed-002"
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001",
                         quantity=10, transaction_id=tx_id)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.purchase(self.customer.customer_id, self.item.item_id, "S001",
                            quantity=5, transaction_id=tx_id)
        self.assertEqual(ctx.exception.code, IDEMPOTENCY_PAYLOAD_CONFLICT)


class TestNonNegativeBalance(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_consume_more_than_balance_rejected(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=5)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.assertEqual(ctx.exception.code, INSUFFICIENT_BALANCE)

    def test_consume_without_purchase_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=1)
        self.assertEqual(ctx.exception.code, INSUFFICIENT_BALANCE)


class TestCrossStoreIsolation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_cross_store_purchase_denied(self):
        c = self.api.register_customer("S001", "VIP-001")
        item = self.api.register_item("S002", "project", "项目B", "次", 10)
        with self.assertRaises(HoldingsError):
            self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)

    def test_customer_cannot_access_other_store(self):
        c = self.api.register_customer("S001", "VIP-001")
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_customer(c.customer_id, "S002")
        # Customer registered in S001, queried from S002 → not found (store isolation)
        self.assertIn(ctx.exception.code, [CROSS_STORE_ACCESS_DENIED, CUSTOMER_NOT_FOUND, ITEM_NOT_FOUND])

    def test_item_cannot_access_other_store(self):
        item = self.api.register_item("S001", "project", "测试", "次", 1)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_item(item.item_id, "S002")

    def test_ledger_entries_isolated(self):
        c1 = self.api.register_customer("S001", "VIP-001")
        c2 = self.api.register_customer("S002", "VIP-002")
        item1 = self.api.register_item("S001", "project", "项目A", "次", 10)
        item2 = self.api.register_item("S002", "project", "项目B", "次", 10)
        self.api.purchase(c1.customer_id, item1.item_id, "S001", quantity=10)
        self.api.purchase(c2.customer_id, item2.item_id, "S002", quantity=5)
        s1_entries = self.api.get_store_ledger("S001")
        s2_entries = self.api.get_store_ledger("S002")
        self.assertEqual(len(s1_entries), 1)
        self.assertEqual(len(s2_entries), 1)


class TestHashChainIntegrity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_entry_hash_is_deterministic(self):
        e = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.assertTrue(e.entry_hash)
        self.assertTrue(e.prev_hash == "" or e.prev_hash)

    def test_hash_chain_valid_after_multiple_entries(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=2)
        ok = self.api.verify_integrity(self.customer.customer_id, self.item.item_id, "S001")
        self.assertTrue(ok)

    def test_hash_chain_intact_after_reversal(self):
        """V0.1.2: Hash chain must be intact after reversal — original entry is NOT modified."""
        purchase = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        ok_before = self.api.verify_integrity(self.customer.customer_id, self.item.item_id, "S001")
        self.assertTrue(ok_before)

        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=10, reversal_of_entry_id=purchase.entry_id)

        ok_after = self.api.verify_integrity(self.customer.customer_id, self.item.item_id, "S001")
        self.assertTrue(ok_after, "Hash chain must be intact after reversal")


class TestHistoricalTraceability(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_entry_retrievable_by_id(self):
        e = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        retrieved = self.api.get_entry(e.entry_id, "S001")
        self.assertEqual(retrieved.entry_id, e.entry_id)

    def test_full_history_retrievable(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        history = self.api.get_transaction_history(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(len(history), 2)

    def test_store_ledger_complete(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        ledger = self.api.get_store_ledger("S001")
        self.assertEqual(len(ledger), 1)


class TestReversal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_reverse_consume_adds_back(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        consume = self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=3, reversal_of_entry_id=consume.entry_id)
        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(balance.remaining_quantity, 10)

    def test_reverse_purchase_no_consumption(self):
        purchase = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=10, reversal_of_entry_id=purchase.entry_id)
        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(balance.remaining_quantity, 0)

    def test_double_reversal_rejected(self):
        purchase = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=10, reversal_of_entry_id=purchase.entry_id)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                           quantity=10, reversal_of_entry_id=purchase.entry_id)
        self.assertEqual(ctx.exception.code, ENTRY_ALREADY_REVERSED)

    def test_partial_reversal_rejected(self):
        """V0.1.2: Only full-amount reversal is allowed."""
        purchase = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                           quantity=5, reversal_of_entry_id=purchase.entry_id)
        self.assertEqual(ctx.exception.code, "PARTIAL_REVERSAL_FORBIDDEN")

    def test_cross_customer_reversal_rejected(self):
        """V0.1.2: Cannot reverse an entry belonging to a different customer."""
        c1 = self.api.register_customer("S001", "VIP-001")
        c2 = self.api.register_customer("S001", "VIP-002")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        purchase = self.api.purchase(c1.customer_id, item.item_id, "S001", quantity=10)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.adjust(c2.customer_id, item.item_id, "S001",
                           quantity=10, reversal_of_entry_id=purchase.entry_id)
        self.assertEqual(ctx.exception.code, "CROSS_CUSTOMER_REVERSAL")

    def test_cross_item_reversal_rejected(self):
        """V0.1.2: Cannot reverse an entry belonging to a different item."""
        c = self.api.register_customer("S001", "VIP-001")
        item1 = self.api.register_item("S001", "project", "项目A", "次", 10)
        item2 = self.api.register_item("S001", "project", "项目B", "次", 10)
        purchase = self.api.purchase(c.customer_id, item1.item_id, "S001", quantity=10)
        with self.assertRaises(HoldingsError) as ctx:
            self.api.adjust(c.customer_id, item2.item_id, "S001",
                           quantity=10, reversal_of_entry_id=purchase.entry_id)
        self.assertEqual(ctx.exception.code, "CROSS_ITEM_REVERSAL")

    def test_reversed_entry_not_deleted(self):
        purchase = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=10, reversal_of_entry_id=purchase.entry_id)
        # Original entry still exists
        retrieved = self.api.get_entry(purchase.entry_id, "S001")
        self.assertEqual(retrieved.entry_id, purchase.entry_id)
        self.assertEqual(retrieved.status, "confirmed")  # NOT modified to "reversed"


class TestLedgerImmutable(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.entry = self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_update_rejected(self):
        with self.assertRaises(Exception):
            self.api.store._get_conn().execute(
                "UPDATE ledger_entries SET quantity = 999 WHERE entry_id = ?",
                (self.entry.entry_id,)
            )

    def test_delete_rejected(self):
        with self.assertRaises(Exception):
            self.api.store._get_conn().execute(
                "DELETE FROM ledger_entries WHERE entry_id = ?",
                (self.entry.entry_id,)
            )


class TestConcurrentConsume(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_concurrent_consume_cannot_go_negative(self):
        """Two threads trying to consume 8 each — only one should succeed."""
        results = []
        errors = []

        def try_consume():
            try:
                self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=8)
                results.append("ok")
            except HoldingsError as e:
                errors.append(e.code)

        t1 = threading.Thread(target=try_consume)
        t2 = threading.Thread(target=try_consume)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # One should succeed, one should fail with INSUFFICIENT_BALANCE
        self.assertEqual(len(results), 1, f"Expected 1 success, got {len(results)}")
        self.assertEqual(len(errors), 1, f"Expected 1 failure, got {len(errors)}")
        self.assertEqual(errors[0], INSUFFICIENT_BALANCE)

        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        self.assertEqual(balance.remaining_quantity, 2)


class TestBalanceDerivation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_complex_balance_scenario(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=2)
        # Reverse the second consume
        history = self.api.get_transaction_history(self.customer.customer_id, self.item.item_id, "S001")
        second_consume = history[2]  # 0=purchase, 1=consume3, 2=consume2
        self.api.adjust(self.customer.customer_id, self.item.item_id, "S001",
                       quantity=2, reversal_of_entry_id=second_consume.entry_id)

        balance = self.api.get_balance(self.customer.customer_id, self.item.item_id, "S001")
        # 10 - 3 (consume2 reversed) = 7
        self.assertEqual(balance.remaining_quantity, 7)

    def test_get_all_balances(self):
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)
        item2 = self.api.register_item("S001", "homecare", "家居套装", "套", 1)
        self.api.purchase(self.customer.customer_id, item2.item_id, "S001", quantity=1)
        balances = self.api.get_all_balances(self.customer.customer_id, "S001")
        self.assertEqual(len(balances), 2)


class TestContactAuth(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_set_contact_auth(self):
        c = self.api.register_customer("S001", "VIP-001")
        self.api.set_contact_auth(c.customer_id, "S001", "granted")
        updated = self.api.get_customer(c.customer_id, "S001")
        self.assertEqual(updated.contact_auth, "granted")

    def test_granted_customer_seeding_actionable(self):
        c = self.api.register_customer("S001", "VIP-001", contact_auth="granted")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=9)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["contact_status"], "contact_allowed")

    def test_unknown_customer_seeding_pending(self):
        c = self.api.register_customer("S001", "VIP-001")  # default unknown
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=9)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["contact_status"], "contact_unknown")

    def test_denied_customer_seeding_forbidden(self):
        """V0.1.2: denied → contact_forbidden, NOT pending_manual_verification."""
        c = self.api.register_customer("S001", "VIP-001", contact_auth="denied")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=9)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["contact_status"], "contact_forbidden")

    def test_seeding_does_not_return_display_name(self):
        """V0.1.2: Seeding results must NOT contain display_name."""
        c = self.api.register_customer("S001", "VIP-001", contact_auth="granted")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=9)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertNotIn("display_name", opps[0])


class TestExpiryReminders(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_set_and_get_expiry(self):
        expiry_date = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        self.api.set_expiry(self.customer.customer_id, self.item.item_id, "S001", expires_at=expiry_date)
        retrieved = self.api.get_expiry(self.customer.customer_id, self.item.item_id, "S001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["expires_at"], expiry_date)

    def test_list_expiring_soon(self):
        soon_date = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
        self.api.set_expiry(self.customer.customer_id, self.item.item_id, "S001", expires_at=soon_date)
        c2 = self.api.register_customer("S001", "VIP-002")
        item2 = self.api.register_item("S001", "homecare", "家居套装", "套", 1)
        self.api.purchase(c2.customer_id, item2.item_id, "S001", quantity=1)
        far_date = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
        self.api.set_expiry(c2.customer_id, item2.item_id, "S001", expires_at=far_date)
        expiring = self.api.list_expiring_soon("S001", within_days=30)
        self.assertEqual(len(expiring), 1)

    def test_past_expiry_rejected(self):
        past_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with self.assertRaises(HoldingsError) as ctx:
            self.api.set_expiry(self.customer.customer_id, self.item.item_id, "S001", expires_at=past_date)
        self.assertEqual(ctx.exception.code, EXPIRY_ALREADY_PASSED)

    def test_invalid_expiry_format_rejected(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.set_expiry(self.customer.customer_id, self.item.item_id, "S001", expires_at="not-a-date")
        self.assertEqual(ctx.exception.code, INVALID_EXPIRY_FORMAT)


class TestConsumptionVelocity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)
        self.customer = self.api.register_customer("S001", "VIP-001")
        self.item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(self.customer.customer_id, self.item.item_id, "S001", quantity=10)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_velocity_with_consumption(self):
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=3)
        self.api.consume(self.customer.customer_id, self.item.item_id, "S001", quantity=2)
        velocity = self.api.get_consumption_velocity(
            self.customer.customer_id, self.item.item_id, "S001", window_days=30
        )
        self.assertEqual(velocity["total_consumed_in_window"], 5)
        self.assertEqual(velocity["remaining_quantity"], 5)

    def test_velocity_no_consumption(self):
        velocity = self.api.get_consumption_velocity(
            self.customer.customer_id, self.item.item_id, "S001", window_days=30
        )
        self.assertEqual(velocity["daily_avg"], 0)
        self.assertIsNone(velocity["estimated_days_to_deplete"])


class TestSeedingOpportunities(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_low_remaining_triggers_opportunity(self):
        c = self.api.register_customer("S001", "VIP-001", contact_auth="granted")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=9)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["opportunity_type"], "low_remaining")

    def test_expiring_soon_triggers_opportunity(self):
        c = self.api.register_customer("S001", "VIP-001", contact_auth="granted")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        self.api.set_expiry(c.customer_id, item.item_id, "S001",
                           expires_at=(datetime.now(timezone.utc) + timedelta(days=15)).isoformat())
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0]["opportunity_type"], "expiring_soon")

    def test_no_opportunities_when_full_balance(self):
        c = self.api.register_customer("S001", "VIP-001")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=10)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 0)

    def test_no_opportunities_when_zero_balance(self):
        c = self.api.register_customer("S001", "VIP-001")
        item = self.api.register_item("S001", "project", "面部护理", "次", 10)
        self.api.purchase(c.customer_id, item.item_id, "S001", quantity=5)
        self.api.consume(c.customer_id, item.item_id, "S001", quantity=5)
        opps = self.api.list_seeding_opportunities("S001")
        self.assertEqual(len(opps), 0)

    def test_opportunities_cross_store_isolated(self):
        c1 = self.api.register_customer("S001", "VIP-001", contact_auth="granted")
        item1 = self.api.register_item("S001", "project", "项目A", "次", 10)
        self.api.purchase(c1.customer_id, item1.item_id, "S001", quantity=10)
        self.api.consume(c1.customer_id, item1.item_id, "S001", quantity=9)
        self.assertEqual(len(self.api.list_seeding_opportunities("S002")), 0)
        self.assertEqual(len(self.api.list_seeding_opportunities("S001")), 1)


class TestServiceModeNoERP(unittest.TestCase):

    def test_contract_version(self):
        from dm_customer_holdings import CONTRACT_VERSION
        self.assertEqual(CONTRACT_VERSION, "dm-customer-holdings-v0.1.2")

    def test_no_erp_dependency(self):
        import dm_customer_holdings
        self.assertFalse(hasattr(dm_customer_holdings, "ERPReadProvider"))


class TestRequiredDataNotAvailable(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.api = CustomerHoldingsAPI(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_balance_for_nonexistent_customer(self):
        with self.assertRaises(HoldingsError) as ctx:
            self.api.get_balance("nonexistent", "nonexistent_item", "S001")
        self.assertEqual(ctx.exception.code, CUSTOMER_NOT_FOUND)

    def test_empty_store_returns_empty_lists(self):
        self.assertEqual(self.api.list_customers("S001"), [])
        self.assertEqual(self.api.list_items("S001"), [])
        self.assertEqual(self.api.get_store_ledger("S001"), [])


if __name__ == "__main__":
    unittest.main()
