"""Balance Calculator V0.1.1 — derives remaining balance from ledger replay.

V0.1.1 changes:
- No longer relies on entry.status to determine if reversed
- Instead, builds a set of reversed entry_ids from ADJUST entries with reversal_of
- Entries whose entry_id appears in the reversed set are excluded from computation
- This means the original entry is NEVER modified — reversal is purely additive

Balance is NEVER stored. It is always computed from the immutable ledger.
"""

from __future__ import annotations

from .contract import (
    LedgerEntry, Balance, HoldingItem,
    TransactionType, EntryStatus,
    HoldingsError,
    INSUFFICIENT_BALANCE,
)


def compute_balance(
    entries: list[LedgerEntry],
    customer_id: str,
    item_id: str,
    store_id: str,
    item: HoldingItem | None = None,
) -> Balance:
    """Compute balance from a list of ledger entries.

    V0.1.1: Reversed entries are identified by reversal_of relationships,
    NOT by checking entry.status. An entry is considered "reversed" if
    another ADJUST entry has its entry_id in the reversal_of field.

    This ensures the original entry is NEVER modified — the reversal is
    purely additive (a new ADJUST entry is appended).
    """
    # Build set of reversed entry_ids
    reversed_entry_ids: set[str] = set()
    for entry in entries:
        if entry.reversal_of:
            reversed_entry_ids.add(entry.reversal_of)

    total_purchased = 0
    total_consumed = 0
    total_adjusted = 0  # standalone adjustments only (not reversals)
    last_transaction_at = ""
    entry_count = 0

    for entry in entries:
        # Skip entries that have been reversed
        if entry.entry_id in reversed_entry_ids:
            continue

        # Skip reversal ADJUST entries — they don't affect balance directly,
        # they just mark the original entry as reversed (excluded above)
        if entry.reversal_of:
            continue

        entry_count += 1

        if entry.timestamp > last_transaction_at:
            last_transaction_at = entry.timestamp

        if entry.transaction_type == TransactionType.PURCHASE.value:
            total_purchased += entry.quantity
        elif entry.transaction_type == TransactionType.CONSUME.value:
            total_consumed += entry.quantity
        elif entry.transaction_type == TransactionType.ADJUST.value:
            # Only standalone ADJUST (no reversal_of) affects balance
            total_adjusted += entry.quantity

    remaining = total_purchased - total_consumed + total_adjusted

    return Balance(
        customer_id=customer_id,
        item_id=item_id,
        store_id=store_id,
        item_name=item.item_name if item else "",
        item_type=item.item_type if item else "",
        unit=item.unit if item else "次",
        remaining_quantity=remaining,
        total_purchased=total_purchased,
        total_consumed=total_consumed,
        total_adjusted=total_adjusted,
        last_transaction_at=last_transaction_at,
        entry_count=entry_count,
    )


def check_consume_ok(
    entries: list[LedgerEntry],
    quantity: int,
) -> tuple[bool, str]:
    """Check if a CONSUME transaction would result in non-negative balance."""
    # We need a dummy item for compute_balance, but it only uses item for naming
    balance = compute_balance(entries, "", "", "")
    if balance.remaining_quantity < quantity:
        return False, (f"Insufficient balance: remaining={balance.remaining_quantity}, "
                      f"requested={quantity}")
    return True, ""


def check_reversal_ok(
    entries: list[LedgerEntry],
    original: LedgerEntry,
    quantity: int,
) -> tuple[bool, str]:
    """Check if a reversal would result in non-negative balance.

    For reversing PURCHASE: the purchase will be excluded, so effectively
    remaining decreases by quantity.
    For reversing CONSUME: the consume will be excluded, so effectively
    remaining increases by quantity (always OK).
    """
    from .contract import TransactionType
    if original.transaction_type == TransactionType.PURCHASE.value:
        balance = compute_balance(entries, "", "", "")
        if balance.remaining_quantity < quantity:
            return False, (f"Cannot reverse purchase: would result in negative balance. "
                          f"remaining={balance.remaining_quantity}, reversing={quantity}")
    return True, ""
