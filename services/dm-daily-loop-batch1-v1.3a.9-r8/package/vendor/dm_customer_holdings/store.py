"""Customer Holdings Store V0.1.1 — SQLite offline storage.

V0.1.1 changes:
- All imports are relative (from .contract import ...)
- ledger_entries table has TRIGGERs blocking UPDATE and DELETE
- append_entry_consume uses BEGIN IMMEDIATE for atomic balance check + append
- append_entry_reversal uses BEGIN IMMEDIATE for atomic reversal check + append
- No _mark_entry_reversed — original entries are NEVER modified
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .contract import (
    Customer, HoldingItem, LedgerEntry, Balance,
    TransactionType, EntryStatus, ContactAuthStatus,
    HoldingsError,
    CUSTOMER_NOT_FOUND, CUSTOMER_ALREADY_EXISTS, CUSTOMER_STORE_MISMATCH,
    ITEM_NOT_FOUND, TRANSACTION_ID_DUPLICATE, ENTRY_NOT_FOUND,
    STORE_ID_REQUIRED, CROSS_STORE_ACCESS_DENIED,
    LEDGER_HASH_CHAIN_BROKEN, LEDGER_IMMUTABLE_VIOLATION,
    IDEMPOTENCY_PAYLOAD_CONFLICT,
    INSUFFICIENT_BALANCE, ENTRY_ALREADY_REVERSED,
    CONTRACT_VERSION,
)


class HoldingsStore:
    """SQLite-based offline store with cross-store isolation."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS customers (
                        customer_id TEXT PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        display_name TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        contact_auth TEXT DEFAULT 'unknown',
                        metadata TEXT DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS holding_items (
                        item_id TEXT PRIMARY KEY,
                        store_id TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        item_name TEXT NOT NULL,
                        unit TEXT DEFAULT '次',
                        default_quantity INTEGER DEFAULT 1,
                        metadata TEXT DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS ledger_entries (
                        entry_id TEXT PRIMARY KEY,
                        transaction_id TEXT UNIQUE NOT NULL,
                        customer_id TEXT NOT NULL,
                        item_id TEXT NOT NULL,
                        store_id TEXT NOT NULL,
                        transaction_type TEXT NOT NULL,
                        quantity INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        operator TEXT DEFAULT '',
                        note TEXT DEFAULT '',
                        prev_hash TEXT DEFAULT '',
                        entry_hash TEXT NOT NULL,
                        status TEXT DEFAULT 'confirmed',
                        reversal_of TEXT DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS idx_ledger_customer_item
                        ON ledger_entries(customer_id, item_id, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_ledger_store
                        ON ledger_entries(store_id);
                    CREATE INDEX IF NOT EXISTS idx_ledger_transaction_id
                        ON ledger_entries(transaction_id);
                    CREATE INDEX IF NOT EXISTS idx_customers_store
                        ON customers(store_id);
                    CREATE INDEX IF NOT EXISTS idx_items_store
                        ON holding_items(store_id);

                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS item_expirations (
                        customer_id TEXT NOT NULL,
                        item_id TEXT NOT NULL,
                        store_id TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        note TEXT DEFAULT '',
                        set_at TEXT NOT NULL,
                        PRIMARY KEY (customer_id, item_id, store_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_expirations_store
                        ON item_expirations(store_id);
                    CREATE INDEX IF NOT EXISTS idx_expirations_date
                        ON item_expirations(store_id, expires_at);

                    -- V0.1.1: TRIGGER to block UPDATE on ledger_entries
                    CREATE TRIGGER IF NOT EXISTS block_ledger_update
                    BEFORE UPDATE ON ledger_entries
                    FOR EACH ROW
                    BEGIN
                        SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: UPDATE not allowed on ledger_entries');
                    END;

                    -- V0.1.1: TRIGGER to block DELETE on ledger_entries
                    CREATE TRIGGER IF NOT EXISTS block_ledger_delete
                    BEFORE DELETE ON ledger_entries
                    FOR EACH ROW
                    BEGIN
                        SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: DELETE not allowed on ledger_entries');
                    END;
                """)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, ?)",
                    ("contract_version", CONTRACT_VERSION)
                )
                conn.commit()
            finally:
                conn.close()

    # ── Store ID validation ────────────────────────────

    def _validate_store_id(self, store_id: str):
        if not store_id:
            raise HoldingsError(STORE_ID_REQUIRED, "store_id is required")

    # ── Customer operations ────────────────────────────

    def register_customer(self, customer: Customer) -> Customer:
        self._validate_store_id(customer.store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO customers (customer_id, store_id, display_name, created_at, contact_auth, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (customer.customer_id, customer.store_id, customer.display_name,
                     customer.created_at, customer.contact_auth,
                     json.dumps(customer.metadata, ensure_ascii=False))
                )
                conn.commit()
                return customer
            except sqlite3.IntegrityError:
                raise HoldingsError(CUSTOMER_ALREADY_EXISTS,
                                  f"customer_id {customer.customer_id} already exists")
            finally:
                conn.close()

    def get_customer(self, customer_id: str, store_id: str) -> Customer:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM customers WHERE customer_id = ? AND store_id = ?",
                    (customer_id, store_id)
                ).fetchone()
                if not row:
                    raise HoldingsError(CUSTOMER_NOT_FOUND,
                                      f"customer_id {customer_id} not found in store {store_id}")
                return Customer(
                    customer_id=row["customer_id"],
                    store_id=row["store_id"],
                    display_name=row["display_name"],
                    created_at=row["created_at"],
                    contact_auth=row["contact_auth"],
                    metadata=json.loads(row["metadata"]),
                )
            finally:
                conn.close()

    def list_customers(self, store_id: str) -> list[Customer]:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM customers WHERE store_id = ? ORDER BY created_at",
                    (store_id,)
                ).fetchall()
                return [Customer(
                    customer_id=r["customer_id"],
                    store_id=r["store_id"],
                    display_name=r["display_name"],
                    created_at=r["created_at"],
                    contact_auth=r["contact_auth"],
                    metadata=json.loads(r["metadata"]),
                ) for r in rows]
            finally:
                conn.close()

    def update_contact_auth(self, customer_id: str, store_id: str, auth_status: str):
        """Update customer contact authorization status."""
        self._validate_store_id(store_id)
        if auth_status not in [e.value for e in ContactAuthStatus]:
            raise HoldingsError("INVALID_CONTACT_AUTH", f"auth_status must be one of {[e.value for e in ContactAuthStatus]}")
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE customers SET contact_auth = ? WHERE customer_id = ? AND store_id = ?",
                    (auth_status, customer_id, store_id)
                )
                conn.commit()
            except sqlite3.IntegrityError as e:
                if "IMMUTABLE" in str(e):
                    raise HoldingsError(LEDGER_IMMUTABLE_VIOLATION, str(e))
                raise
            finally:
                conn.close()

    # ── Holding item operations ───────────────────────

    def register_item(self, item: HoldingItem) -> HoldingItem:
        self._validate_store_id(item.store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO holding_items (item_id, store_id, item_type, item_name, unit, "
                    "default_quantity, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item.item_id, item.store_id, item.item_type, item.item_name,
                     item.unit, item.default_quantity,
                     json.dumps(item.metadata, ensure_ascii=False))
                )
                conn.commit()
                return item
            except sqlite3.IntegrityError:
                raise HoldingsError("ITEM_ALREADY_EXISTS",
                                  f"item_id {item.item_id} already exists")
            finally:
                conn.close()

    def get_item(self, item_id: str, store_id: str) -> HoldingItem:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM holding_items WHERE item_id = ? AND store_id = ?",
                    (item_id, store_id)
                ).fetchone()
                if not row:
                    raise HoldingsError(ITEM_NOT_FOUND,
                                      f"item_id {item_id} not found in store {store_id}")
                return HoldingItem(
                    item_id=row["item_id"],
                    store_id=row["store_id"],
                    item_type=row["item_type"],
                    item_name=row["item_name"],
                    unit=row["unit"],
                    default_quantity=row["default_quantity"],
                    metadata=json.loads(row["metadata"]),
                )
            finally:
                conn.close()

    def list_items(self, store_id: str) -> list[HoldingItem]:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM holding_items WHERE store_id = ? ORDER BY item_name",
                    (store_id,)
                ).fetchall()
                return [HoldingItem(
                    item_id=r["item_id"],
                    store_id=r["store_id"],
                    item_type=r["item_type"],
                    item_name=r["item_name"],
                    unit=r["unit"],
                    default_quantity=r["default_quantity"],
                    metadata=json.loads(r["metadata"]),
                ) for r in rows]
            finally:
                conn.close()

    # ── Ledger operations ──────────────────────────────

    def append_entry(self, entry: LedgerEntry) -> LedgerEntry:
        """Append an immutable entry to the ledger.

        Idempotency: transaction_id must be unique.
        Hash chain: prev_hash links to previous entry for same (customer_id, item_id).
        """
        self._validate_store_id(entry.store_id)

        with self._lock:
            conn = self._get_conn()
            try:
                # Check transaction_id uniqueness (idempotency)
                existing = conn.execute(
                    "SELECT * FROM ledger_entries WHERE transaction_id = ?",
                    (entry.transaction_id,)
                ).fetchone()
                if existing:
                    raise HoldingsError(TRANSACTION_ID_DUPLICATE,
                                      f"transaction_id {entry.transaction_id} already exists")

                # Get previous entry hash for chain
                prev = conn.execute(
                    "SELECT entry_hash FROM ledger_entries "
                    "WHERE customer_id = ? AND item_id = ? AND store_id = ? "
                    "ORDER BY timestamp DESC, entry_id DESC LIMIT 1",
                    (entry.customer_id, entry.item_id, entry.store_id)
                ).fetchone()

                if prev:
                    entry.prev_hash = prev["entry_hash"]

                # Recompute hash with prev_hash
                entry.entry_hash = entry._compute_hash()

                conn.execute(
                    "INSERT INTO ledger_entries (entry_id, transaction_id, customer_id, item_id, "
                    "store_id, transaction_type, quantity, timestamp, operator, note, "
                    "prev_hash, entry_hash, status, reversal_of) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry.entry_id, entry.transaction_id, entry.customer_id, entry.item_id,
                     entry.store_id, entry.transaction_type, entry.quantity, entry.timestamp,
                     entry.operator, entry.note, entry.prev_hash, entry.entry_hash,
                     entry.status, entry.reversal_of)
                )
                conn.commit()
                return entry
            finally:
                conn.close()

    def append_entry_atomic(
        self,
        entry: LedgerEntry,
        balance_check_fn=None,
    ) -> LedgerEntry:
        """Append entry with atomic balance check using BEGIN IMMEDIATE.

        The balance_check_fn receives (entries_list) and should return (ok, error_msg).
        Both the balance check and the INSERT happen inside the same BEGIN IMMEDIATE
        transaction, so concurrent consumers cannot both pass the balance check.

        For idempotency: if transaction_id already exists, returns the existing entry
        (if payload matches) or raises IDEMPOTENCY_PAYLOAD_CONFLICT.
        """
        self._validate_store_id(entry.store_id)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.isolation_level = None  # autocommit mode for manual BEGIN

                # Idempotency check
                existing = conn.execute(
                    "SELECT * FROM ledger_entries WHERE transaction_id = ?",
                    (entry.transaction_id,)
                ).fetchone()
                if existing:
                    existing_entry = LedgerEntry.from_dict(dict(existing))
                    # Check payload consistency
                    if (existing_entry.customer_id == entry.customer_id and
                        existing_entry.item_id == entry.item_id and
                        existing_entry.store_id == entry.store_id and
                        existing_entry.transaction_type == entry.transaction_type and
                        existing_entry.quantity == entry.quantity):
                        return existing_entry
                    raise HoldingsError(IDEMPOTENCY_PAYLOAD_CONFLICT,
                        f"transaction_id {entry.transaction_id} exists with different payload",
                        {"existing": existing_entry.to_dict(), "new": entry.to_dict()})

                # BEGIN IMMEDIATE — acquires write lock, prevents concurrent writers
                conn.execute("BEGIN IMMEDIATE")

                try:
                    # Get all entries for balance computation
                    rows = conn.execute(
                        "SELECT * FROM ledger_entries "
                        "WHERE customer_id = ? AND item_id = ? AND store_id = ? "
                        "ORDER BY timestamp ASC, entry_id ASC",
                        (entry.customer_id, entry.item_id, entry.store_id)
                    ).fetchall()
                    entries = [LedgerEntry.from_dict(dict(r)) for r in rows]

                    # Run balance check if provided
                    if balance_check_fn:
                        ok, error_msg = balance_check_fn(entries)
                        if not ok:
                            conn.execute("ROLLBACK")
                            raise HoldingsError(INSUFFICIENT_BALANCE, error_msg)

                    # Get prev_hash
                    prev_hash = ""
                    if entries:
                        prev_hash = entries[-1].entry_hash

                    entry.prev_hash = prev_hash
                    entry.entry_hash = entry._compute_hash()

                    conn.execute(
                        "INSERT INTO ledger_entries (entry_id, transaction_id, customer_id, item_id, "
                        "store_id, transaction_type, quantity, timestamp, operator, note, "
                        "prev_hash, entry_hash, status, reversal_of) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry.entry_id, entry.transaction_id, entry.customer_id, entry.item_id,
                         entry.store_id, entry.transaction_type, entry.quantity, entry.timestamp,
                         entry.operator, entry.note, entry.prev_hash, entry.entry_hash,
                         entry.status, entry.reversal_of)
                    )
                    conn.execute("COMMIT")
                    return entry
                except Exception:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
            finally:
                conn.close()

    def append_reversal_atomic(
        self,
        reversal_entry: LedgerEntry,
        original_entry_id: str,
        reversal_check_fn=None,
    ) -> LedgerEntry:
        """Append a reversal entry atomically.

        The reversal check (is original already reversed? non-negative?) and the
        append of the reversal entry happen in the same BEGIN IMMEDIATE transaction.
        The original entry is NEVER modified — reversal is tracked purely through
        the reversal_of relationship on the new ADJUST entry.
        """
        self._validate_store_id(reversal_entry.store_id)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.isolation_level = None

                # Idempotency check
                existing = conn.execute(
                    "SELECT * FROM ledger_entries WHERE transaction_id = ?",
                    (reversal_entry.transaction_id,)
                ).fetchone()
                if existing:
                    existing_entry = LedgerEntry.from_dict(dict(existing))
                    if (existing_entry.customer_id == reversal_entry.customer_id and
                        existing_entry.item_id == reversal_entry.item_id and
                        existing_entry.store_id == reversal_entry.store_id):
                        return existing_entry
                    raise HoldingsError(IDEMPOTENCY_PAYLOAD_CONFLICT,
                        f"transaction_id {reversal_entry.transaction_id} exists with different payload")

                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Check original entry exists and is not already reversed
                    rows = conn.execute(
                        "SELECT * FROM ledger_entries WHERE entry_id = ? AND store_id = ?",
                        (original_entry_id, reversal_entry.store_id)
                    ).fetchall()
                    if not rows:
                        conn.execute("ROLLBACK")
                        raise HoldingsError(ENTRY_NOT_FOUND,
                                          f"entry_id {original_entry_id} not found")
                    original = LedgerEntry.from_dict(dict(rows[0]))

                    # Check if already reversed — look for an existing ADJUST entry
                    # with reversal_of pointing to this entry
                    reversal_check = conn.execute(
                        "SELECT entry_id FROM ledger_entries "
                        "WHERE reversal_of = ? AND store_id = ?",
                        (original_entry_id, reversal_entry.store_id)
                    ).fetchone()
                    if reversal_check:
                        conn.execute("ROLLBACK")
                        raise HoldingsError(
                            ENTRY_ALREADY_REVERSED,
                            f"Entry {original_entry_id} is already reversed by {reversal_check['entry_id']}"
                        )

                    # Run custom check (e.g., non-negative for PURCHASE reversal)
                    if reversal_check_fn:
                        all_rows = conn.execute(
                            "SELECT * FROM ledger_entries "
                            "WHERE customer_id = ? AND item_id = ? AND store_id = ? "
                            "ORDER BY timestamp ASC, entry_id ASC",
                            (reversal_entry.customer_id, reversal_entry.item_id, reversal_entry.store_id)
                        ).fetchall()
                        all_entries = [LedgerEntry.from_dict(dict(r)) for r in all_rows]
                        ok, error_msg = reversal_check_fn(all_entries, original)
                        if not ok:
                            conn.execute("ROLLBACK")
                            raise HoldingsError(INSUFFICIENT_BALANCE, error_msg)

                    # Get prev_hash
                    prev = conn.execute(
                        "SELECT entry_hash FROM ledger_entries "
                        "WHERE customer_id = ? AND item_id = ? AND store_id = ? "
                        "ORDER BY timestamp DESC, entry_id DESC LIMIT 1",
                        (reversal_entry.customer_id, reversal_entry.item_id, reversal_entry.store_id)
                    ).fetchone()
                    reversal_entry.prev_hash = prev["entry_hash"] if prev else ""
                    reversal_entry.entry_hash = reversal_entry._compute_hash()

                    conn.execute(
                        "INSERT INTO ledger_entries (entry_id, transaction_id, customer_id, item_id, "
                        "store_id, transaction_type, quantity, timestamp, operator, note, "
                        "prev_hash, entry_hash, status, reversal_of) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (reversal_entry.entry_id, reversal_entry.transaction_id,
                         reversal_entry.customer_id, reversal_entry.item_id,
                         reversal_entry.store_id, reversal_entry.transaction_type,
                         reversal_entry.quantity, reversal_entry.timestamp,
                         reversal_entry.operator, reversal_entry.note,
                         reversal_entry.prev_hash, reversal_entry.entry_hash,
                         reversal_entry.status, reversal_entry.reversal_of)
                    )
                    conn.execute("COMMIT")
                    return reversal_entry
                except Exception:
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
            finally:
                conn.close()

    def get_entry(self, entry_id: str, store_id: str) -> LedgerEntry:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM ledger_entries WHERE entry_id = ? AND store_id = ?",
                    (entry_id, store_id)
                ).fetchone()
                if not row:
                    raise HoldingsError(ENTRY_NOT_FOUND,
                                      f"entry_id {entry_id} not found in store {store_id}")
                return LedgerEntry.from_dict(dict(row))
            finally:
                conn.close()

    def get_entries_by_customer_item(
        self, customer_id: str, item_id: str, store_id: str
    ) -> list[LedgerEntry]:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM ledger_entries "
                    "WHERE customer_id = ? AND item_id = ? AND store_id = ? "
                    "ORDER BY timestamp ASC, entry_id ASC",
                    (customer_id, item_id, store_id)
                ).fetchall()
                return [LedgerEntry.from_dict(dict(r)) for r in rows]
            finally:
                conn.close()

    def get_all_entries(self, store_id: str) -> list[LedgerEntry]:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM ledger_entries WHERE store_id = ? "
                    "ORDER BY timestamp ASC, entry_id ASC",
                    (store_id,)
                ).fetchall()
                return [LedgerEntry.from_dict(dict(r)) for r in rows]
            finally:
                conn.close()

    def verify_hash_chain(
        self, customer_id: str, item_id: str, store_id: str
    ) -> bool:
        """Verify hash chain integrity for a customer+item pair.

        V0.1.1: entry_hash excludes status, so reversal (which only adds new entries,
        never modifies existing ones) does not break the chain.
        """
        entries = self.get_entries_by_customer_item(customer_id, item_id, store_id)
        prev_hash = ""
        for entry in entries:
            if entry.prev_hash != prev_hash:
                return False
            expected = entry._compute_hash()
            if entry.entry_hash != expected:
                return False
            prev_hash = entry.entry_hash
        return True

    def get_transaction_by_id(
        self, transaction_id: str, store_id: str
    ) -> LedgerEntry | None:
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM ledger_entries "
                    "WHERE transaction_id = ? AND store_id = ?",
                    (transaction_id, store_id)
                ).fetchone()
                if not row:
                    return None
                return LedgerEntry.from_dict(dict(row))
            finally:
                conn.close()

    def is_entry_reversed(self, entry_id: str, store_id: str) -> bool:
        """Check if an entry has been reversed by looking for ADJUST entries pointing to it."""
        self._validate_store_id(store_id)
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT entry_id FROM ledger_entries "
                    "WHERE reversal_of = ? AND store_id = ?",
                    (entry_id, store_id)
                ).fetchone()
                return row is not None
            finally:
                conn.close()
