"""Customer Holdings API V0.1.1 — public interface for the offline backend.

V0.1.1 changes:
- All imports are relative (from .contract import ...)
- consume() uses append_entry_atomic() with BEGIN IMMEDIATE
- adjust() with reversal uses append_reversal_atomic() with BEGIN IMMEDIATE
- No _mark_entry_reversed — original entries NEVER modified
- set_expiry validates ISO format and rejects past dates
- list_expiring_soon rejects already-expired records
- list_seeding_opportunities checks contact_auth, only returns customer_id (not display_name)
- register_customer validates metadata for PII
- Idempotency: same transaction_id with different payload → IDEMPOTENCY_PAYLOAD_CONFLICT
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from .contract import (
    Customer, HoldingItem, LedgerEntry, Balance,
    ItemType, TransactionType, EntryStatus, ContactAuthStatus,
    HoldingsError,
    generate_customer_id, generate_item_id, generate_transaction_id,
    validate_metadata_no_pii, validate_expiry_format,
    CUSTOMER_NOT_FOUND, ITEM_NOT_FOUND,
    INSUFFICIENT_BALANCE, ENTRY_ALREADY_REVERSED,
    REQUIRED_CUSTOMER_HOLDINGS_DATA_NOT_AVAILABLE,
    IDEMPOTENCY_PAYLOAD_CONFLICT,
    CONTACT_DENIED,
    CONTRACT_VERSION,
)
from .store import HoldingsStore
from .balance import compute_balance, check_consume_ok, check_reversal_ok


class CustomerHoldingsAPI:
    """Public API for customer holdings offline backend."""

    def __init__(self, db_path: str):
        self.store = HoldingsStore(db_path)
        self.contract_version = CONTRACT_VERSION

    # ── Customer ───────────────────────────────────────

    def register_customer(
        self, store_id: str, display_name: str = "",
        metadata: dict | None = None,
        contact_auth: str = ContactAuthStatus.UNKNOWN.value,
    ) -> Customer:
        """Register a new customer with a pseudonymous ID.

        V0.1.2: display_name must be a pseudonym format (e.g., VIP-001, C-123).
        Metadata is recursively checked for PII.
        """
        # V0.1.2: display_name must be pseudonym format — no real names
        if display_name:
            from .contract import validate_display_name_pseudonym
            validate_display_name_pseudonym(display_name)

        customer_id = generate_customer_id(store_id)
        customer = Customer(
            customer_id=customer_id,
            store_id=store_id,
            display_name=display_name,
            metadata=metadata or {},
            contact_auth=contact_auth,
        )
        return self.store.register_customer(customer)

    def get_customer(self, customer_id: str, store_id: str) -> Customer:
        return self.store.get_customer(customer_id, store_id)

    def list_customers(self, store_id: str) -> list[Customer]:
        return self.store.list_customers(store_id)

    def set_contact_auth(self, customer_id: str, store_id: str, auth_status: str):
        """Set customer contact authorization status.

        Three-state: unknown / granted / denied
        Only 'granted' allows seeding opportunities to be actionable.
        """
        self.store.get_customer(customer_id, store_id)
        self.store.update_contact_auth(customer_id, store_id, auth_status)

    # ── Holding Item ───────────────────────────────────

    def register_item(
        self, store_id: str, item_type: str, item_name: str,
        unit: str = "次", default_quantity: int = 1,
        metadata: dict | None = None,
    ) -> HoldingItem:
        item_id = generate_item_id(store_id)
        item = HoldingItem(
            item_id=item_id,
            store_id=store_id,
            item_type=item_type,
            item_name=item_name,
            unit=unit,
            default_quantity=default_quantity,
            metadata=metadata or {},
        )
        return self.store.register_item(item)

    def get_item(self, item_id: str, store_id: str) -> HoldingItem:
        return self.store.get_item(item_id, store_id)

    def list_items(self, store_id: str) -> list[HoldingItem]:
        return self.store.list_items(store_id)

    # ── Ledger operations ──────────────────────────────

    def purchase(
        self, customer_id: str, item_id: str, store_id: str,
        quantity: int, operator: str = "", note: str = "",
        transaction_id: str | None = None,
    ) -> LedgerEntry:
        """Record a purchase — adds to balance."""
        self.store.get_customer(customer_id, store_id)
        self.store.get_item(item_id, store_id)

        tx_id = transaction_id or generate_transaction_id()

        entry = LedgerEntry(
            entry_id="",
            transaction_id=tx_id,
            customer_id=customer_id,
            item_id=item_id,
            store_id=store_id,
            transaction_type=TransactionType.PURCHASE.value,
            quantity=quantity,
            timestamp=datetime.now(timezone.utc).isoformat(),
            operator=operator,
            note=note,
        )
        return self.store.append_entry_atomic(entry, balance_check_fn=None)

    def consume(
        self, customer_id: str, item_id: str, store_id: str,
        quantity: int, operator: str = "", note: str = "",
        transaction_id: str | None = None,
    ) -> LedgerEntry:
        """Record a consumption — subtracts from balance.

        V0.1.1: Uses BEGIN IMMEDIATE transaction for atomic balance check + append.
        Non-negative: rejected if remaining balance < quantity.
        """
        self.store.get_customer(customer_id, store_id)
        self.store.get_item(item_id, store_id)

        tx_id = transaction_id or generate_transaction_id()

        entry = LedgerEntry(
            entry_id="",
            transaction_id=tx_id,
            customer_id=customer_id,
            item_id=item_id,
            store_id=store_id,
            transaction_type=TransactionType.CONSUME.value,
            quantity=quantity,
            timestamp=datetime.now(timezone.utc).isoformat(),
            operator=operator,
            note=note,
        )

        def balance_check(entries):
            ok, msg = check_consume_ok(entries, quantity)
            return ok, msg

        return self.store.append_entry_atomic(entry, balance_check_fn=balance_check)

    def adjust(
        self, customer_id: str, item_id: str, store_id: str,
        quantity: int, operator: str = "", note: str = "",
        reversal_of_entry_id: str = "",
        transaction_id: str | None = None,
    ) -> LedgerEntry:
        """Record an adjustment/correction (冲正).

        V0.1.2 rules:
        - Reversal must be FULL amount: quantity must equal original entry's quantity
        - Cross-customer and cross-item reversal is rejected
        - Reversal appends a new ADJUST entry, original is NEVER modified
        - Uses BEGIN IMMEDIATE transaction for atomic check + append
        """
        self.store.get_customer(customer_id, store_id)
        self.store.get_item(item_id, store_id)

        tx_id = transaction_id or generate_transaction_id()

        if reversal_of_entry_id:
            # V0.1.2: Validate full-amount reversal and cross-entity rejection
            original = self.store.get_entry(reversal_of_entry_id, store_id)
            if original.customer_id != customer_id:
                raise HoldingsError(
                    "CROSS_CUSTOMER_REVERSAL",
                    f"Reversal customer_id={customer_id} does not match original customer_id={original.customer_id}"
                )
            if original.item_id != item_id:
                raise HoldingsError(
                    "CROSS_ITEM_REVERSAL",
                    f"Reversal item_id={item_id} does not match original item_id={original.item_id}"
                )
            if quantity != original.quantity:
                raise HoldingsError(
                    "PARTIAL_REVERSAL_FORBIDDEN",
                    f"Reversal quantity={quantity} must equal original quantity={original.quantity}. "
                    f"Only full-amount reversal is allowed."
                )

            entry = LedgerEntry(
                entry_id="",
                transaction_id=tx_id,
                customer_id=customer_id,
                item_id=item_id,
                store_id=store_id,
                transaction_type=TransactionType.ADJUST.value,
                quantity=quantity,
                timestamp=datetime.now(timezone.utc).isoformat(),
                operator=operator,
                note=note or (f"Reversal of {reversal_of_entry_id}"),
                reversal_of=reversal_of_entry_id,
            )

            def reversal_check(entries, original):
                ok, msg = check_reversal_ok(entries, original, quantity)
                return ok, msg

            return self.store.append_reversal_atomic(
                entry, reversal_of_entry_id, reversal_check_fn=reversal_check
            )
        else:
            entry = LedgerEntry(
                entry_id="",
                transaction_id=tx_id,
                customer_id=customer_id,
                item_id=item_id,
                store_id=store_id,
                transaction_type=TransactionType.ADJUST.value,
                quantity=quantity,
                timestamp=datetime.now(timezone.utc).isoformat(),
                operator=operator,
                note=note,
                reversal_of="",
            )
            return self.store.append_entry_atomic(entry, balance_check_fn=None)

    # ── Balance ────────────────────────────────────────

    def get_balance(
        self, customer_id: str, item_id: str, store_id: str
    ) -> Balance:
        self.store.get_customer(customer_id, store_id)
        item = self.store.get_item(item_id, store_id)
        entries = self.store.get_entries_by_customer_item(customer_id, item_id, store_id)
        return compute_balance(entries, customer_id, item_id, store_id, item)

    def get_all_balances(self, customer_id: str, store_id: str) -> list[Balance]:
        self.store.get_customer(customer_id, store_id)
        items = self.store.list_items(store_id)
        balances = []
        for item in items:
            entries = self.store.get_entries_by_customer_item(
                customer_id, item.item_id, store_id
            )
            if entries:
                balances.append(
                    compute_balance(entries, customer_id, item.item_id, store_id, item)
                )
        return balances

    # ── Traceability ───────────────────────────────────

    def get_transaction_history(
        self, customer_id: str, item_id: str, store_id: str
    ) -> list[LedgerEntry]:
        return self.store.get_entries_by_customer_item(customer_id, item_id, store_id)

    def get_store_ledger(self, store_id: str) -> list[LedgerEntry]:
        return self.store.get_all_entries(store_id)

    def verify_integrity(
        self, customer_id: str, item_id: str, store_id: str
    ) -> bool:
        return self.store.verify_hash_chain(customer_id, item_id, store_id)

    def get_entry(self, entry_id: str, store_id: str) -> LedgerEntry:
        return self.store.get_entry(entry_id, store_id)

    def is_entry_reversed(self, entry_id: str, store_id: str) -> bool:
        """Check if an entry has been reversed (without modifying it)."""
        return self.store.is_entry_reversed(entry_id, store_id)

    # ── Expiry Reminders ───────────────────────────────

    def set_expiry(
        self, customer_id: str, item_id: str, store_id: str,
        expires_at: str, note: str = "",
    ) -> dict:
        """Set expiry date for a customer's holding item.

        V0.1.1: Validates ISO 8601 format and rejects past dates.
        """
        self.store.get_customer(customer_id, store_id)
        self.store.get_item(item_id, store_id)
        validate_expiry_format(expires_at)  # raises if invalid or past

        with self.store._lock:
            conn = self.store._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO item_expirations "
                    "(customer_id, item_id, store_id, expires_at, note, set_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (customer_id, item_id, store_id, expires_at, note,
                     datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
            finally:
                conn.close()
        return {"customer_id": customer_id, "item_id": item_id,
                "store_id": store_id, "expires_at": expires_at, "note": note}

    def get_expiry(
        self, customer_id: str, item_id: str, store_id: str
    ) -> dict | None:
        self.store.get_customer(customer_id, store_id)
        with self.store._lock:
            conn = self.store._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM item_expirations "
                    "WHERE customer_id = ? AND item_id = ? AND store_id = ?",
                    (customer_id, item_id, store_id)
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def list_expiring_soon(
        self, store_id: str, within_days: int = 30
    ) -> list[dict]:
        """List all items expiring within N days for a store.

        V0.1.1: Only includes items where:
        current_time <= expires_at <= current_time + N_days
        (already-expired records are excluded)
        """
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(days=within_days)
        with self.store._lock:
            conn = self.store._get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM item_expirations "
                    "WHERE store_id = ? AND expires_at > ? AND expires_at <= ? "
                    "ORDER BY expires_at ASC",
                    (store_id, now.isoformat(), deadline.isoformat())
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ── Consumption Velocity & Seeding Opportunities ───

    def get_consumption_velocity(
        self, customer_id: str, item_id: str, store_id: str,
        window_days: int = 30,
    ) -> dict:
        self.store.get_customer(customer_id, store_id)
        item = self.store.get_item(item_id, store_id)
        entries = self.store.get_entries_by_customer_item(customer_id, item_id, store_id)

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        # V0.1.1: Use reversal-aware computation
        # Build reversed set
        reversed_ids = {e.reversal_of for e in entries if e.reversal_of}

        consume_entries = [
            e for e in entries
            if e.transaction_type == TransactionType.CONSUME.value
            and e.entry_id not in reversed_ids
            and not e.reversal_of
        ]

        recent_consumes = [
            e for e in consume_entries
            if datetime.fromisoformat(e.timestamp) >= window_start
        ]

        total_consumed = sum(e.quantity for e in recent_consumes)
        daily_avg = total_consumed / window_days if window_days > 0 else 0

        last_consume_at = ""
        if consume_entries:
            last_consume_at = max(e.timestamp for e in consume_entries)

        balance = compute_balance(entries, customer_id, item_id, store_id, item)

        estimated_days = None
        if daily_avg > 0 and balance.remaining_quantity > 0:
            estimated_days = int(balance.remaining_quantity / daily_avg)

        return {
            "customer_id": customer_id,
            "item_id": item_id,
            "store_id": store_id,
            "item_name": item.item_name,
            "total_consumed_in_window": total_consumed,
            "window_days": window_days,
            "daily_avg": round(daily_avg, 2),
            "last_consume_at": last_consume_at,
            "remaining_quantity": balance.remaining_quantity,
            "estimated_days_to_deplete": estimated_days,
        }

    def list_seeding_opportunities(
        self, store_id: str,
        low_remaining_threshold: float = 0.2,
        expiring_within_days: int = 30,
    ) -> list[dict]:
        """Identify seeding opportunities for a store.

        V0.1.1 changes:
        - Only returns customer_id (not display_name) — privacy
        - Checks contact_auth: only 'granted' customers are "actionable"
        - 'unknown' or 'denied' customers are returned as "pending_manual_verification"
        - Already-expired items are excluded from expiring_soon
        """
        opportunities = []
        customers = self.store.list_customers(store_id)
        items = self.store.list_items(store_id)

        now = datetime.now(timezone.utc)
        deadline = now + timedelta(days=expiring_within_days)

        for customer in customers:
            for item in items:
                entries = self.store.get_entries_by_customer_item(
                    customer.customer_id, item.item_id, store_id
                )
                if not entries:
                    continue

                balance = compute_balance(
                    entries, customer.customer_id, item.item_id, store_id, item
                )

                # Determine contact status — denied is forbidden, not "pending"
                if customer.contact_auth == ContactAuthStatus.GRANTED.value:
                    contact_status = "contact_allowed"
                elif customer.contact_auth == ContactAuthStatus.DENIED.value:
                    contact_status = "contact_forbidden"
                else:
                    contact_status = "contact_unknown"

                # Check low remaining
                total_purchased = balance.total_purchased
                if total_purchased > 0:
                    remaining_ratio = balance.remaining_quantity / total_purchased
                    if remaining_ratio <= low_remaining_threshold and balance.remaining_quantity > 0:
                        velocity = self.get_consumption_velocity(
                            customer.customer_id, item.item_id, store_id
                        )
                        opportunities.append({
                            "customer_id": customer.customer_id,
                            # V0.1.1: no display_name in seeding results
                            "item_id": item.item_id,
                            "item_name": item.item_name,
                            "item_type": item.item_type,
                            "store_id": store_id,
                            "opportunity_type": "low_remaining",
                            "remaining_quantity": balance.remaining_quantity,
                            "remaining_ratio": round(remaining_ratio, 2),
                            "daily_avg": velocity["daily_avg"],
                            "estimated_days_to_deplete": velocity["estimated_days_to_deplete"],
                            "contact_auth": customer.contact_auth,
                            "contact_status": contact_status,
                        })
                        continue

                # Check expiring soon (must be in the future)
                expiry = self.get_expiry(customer.customer_id, item.item_id, store_id)
                if expiry:
                    try:
                        exp_date = datetime.fromisoformat(expiry["expires_at"])
                        if exp_date.tzinfo is None:
                            exp_date = exp_date.replace(tzinfo=timezone.utc)
                        # Only include if not already expired and within window
                        if now < exp_date <= deadline and balance.remaining_quantity > 0:
                            days_left = (exp_date - now).days
                            opportunities.append({
                                "customer_id": customer.customer_id,
                                "item_id": item.item_id,
                                "item_name": item.item_name,
                                "item_type": item.item_type,
                                "store_id": store_id,
                                "opportunity_type": "expiring_soon",
                                "remaining_quantity": balance.remaining_quantity,
                                "expires_at": expiry["expires_at"],
                                "days_left": days_left,
                                "contact_auth": customer.contact_auth,
                                "contact_status": contact_status,
                            })
                    except (ValueError, TypeError):
                        pass

        return opportunities
