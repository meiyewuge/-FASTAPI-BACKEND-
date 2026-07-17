"""DM Customer Holdings package V0.1.1.

Usage:
    from dm_customer_holdings import CustomerHoldingsAPI
    api = CustomerHoldingsAPI("holdings.db")
"""

from .contract import (
    CONTRACT_VERSION,
    Customer, HoldingItem, LedgerEntry, Balance,
    ItemType, TransactionType, EntryStatus, ContactAuthStatus,
    HoldingsError,
    generate_customer_id, generate_item_id, generate_transaction_id,
    validate_metadata_no_pii, validate_expiry_format, validate_display_name_pseudonym,
)
from .store import HoldingsStore
from .balance import compute_balance
from .api import CustomerHoldingsAPI

__all__ = [
    "CONTRACT_VERSION",
    "Customer", "HoldingItem", "LedgerEntry", "Balance",
    "ItemType", "TransactionType", "EntryStatus", "ContactAuthStatus",
    "HoldingsError",
    "generate_customer_id", "generate_item_id", "generate_transaction_id",
    "validate_metadata_no_pii", "validate_expiry_format", "validate_display_name_pseudonym",
    "HoldingsStore", "compute_balance", "CustomerHoldingsAPI",
]
