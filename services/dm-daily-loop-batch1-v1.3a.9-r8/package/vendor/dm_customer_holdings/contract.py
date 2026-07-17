"""Customer Holdings Contract V0.1.1 — data models and error codes.

V0.1.1 changes:
- Hash chain excludes status (status is runtime state, not entry content)
- Reversal appends new entry, never modifies original
- Balance replay recognizes reversal_of relationships
- PII rejection in metadata
- Contact authorization three-state: unknown/granted/denied
- Expiry date ISO validation

NO production DB. NO ERP. NO financial data. NO deployment.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Constants ─────────────────────────────────────────

CONTRACT_VERSION = "dm-customer-holdings-v0.1.2"
STORE_BUSINESS_TYPE = "service"
ERP_INVENTORY_ENABLED = False


# ── Enums ─────────────────────────────────────────────

class ItemType(str, Enum):
    PROJECT = "project"
    SINGLE = "single"
    HOMECARE = "homecare"


class TransactionType(str, Enum):
    PURCHASE = "purchase"
    CONSUME = "consume"
    ADJUST = "adjust"


class EntryStatus(str, Enum):
    CONFIRMED = "confirmed"
    REVERSED = "reversed"


class ContactAuthStatus(str, Enum):
    """Customer contact authorization three-state."""
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DENIED = "denied"


# ── Error Codes ───────────────────────────────────────

class HoldingsError(Exception):
    """Base error for customer holdings module."""
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


# Customer errors
CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
CUSTOMER_ALREADY_EXISTS = "CUSTOMER_ALREADY_EXISTS"
CUSTOMER_STORE_MISMATCH = "CUSTOMER_STORE_MISMATCH"

# Item errors
ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
ITEM_TYPE_INVALID = "ITEM_TYPE_INVALID"

# Ledger errors
TRANSACTION_ID_DUPLICATE = "TRANSACTION_ID_DUPLICATE"
IDEMPOTENCY_PAYLOAD_CONFLICT = "IDEMPOTENCY_PAYLOAD_CONFLICT"
INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
ENTRY_NOT_FOUND = "ENTRY_NOT_FOUND"
ENTRY_ALREADY_REVERSED = "ENTRY_ALREADY_REVERSED"
LEDGER_HASH_CHAIN_BROKEN = "LEDGER_HASH_CHAIN_BROKEN"
LEDGER_IMMUTABLE_VIOLATION = "LEDGER_IMMUTABLE_VIOLATION"

# Store errors
STORE_ID_REQUIRED = "STORE_ID_REQUIRED"
CROSS_STORE_ACCESS_DENIED = "CROSS_STORE_ACCESS_DENIED"

# Data errors
REQUIRED_CUSTOMER_HOLDINGS_DATA_NOT_AVAILABLE = "REQUIRED_CUSTOMER_HOLDINGS_DATA_NOT_AVAILABLE"
INVALID_QUANTITY = "INVALID_QUANTITY"
INVALID_EXPIRY_FORMAT = "INVALID_EXPIRY_FORMAT"
EXPIRY_ALREADY_PASSED = "EXPIRY_ALREADY_PASSED"

# Privacy errors
PII_DETECTED = "PII_DETECTED"
CONTACT_DENIED = "CONTACT_DENIED"


# ── PII Detection ─────────────────────────────────────

# PII field names to reject in metadata
PII_FIELD_NAMES = {
    "phone", "mobile", "tel", "telephone",
    "real_name", "name", "customer_name",
    "address", "home_address",
    "id_card", "id_number", "passport",
    "email",
    "wechat", "weixin",
    "birthday", "birth_date",
}

# PII value patterns (Chinese phone numbers, ID cards)
PII_VALUE_PATTERNS = [
    re.compile(r'^1[3-9]\d{9}$'),           # Chinese mobile
    re.compile(r'^\d{15}$'),                 # ID card (15 digit)
    re.compile(r'^\d{17}[\dXx]$'),           # ID card (18 digit)
    re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),  # email
]


def _check_pii_in_metadata(metadata: dict[str, Any], path: str = "") -> list[str]:
    """Recursively check metadata for PII fields and values.

    Returns list of PII violation descriptions.
    """
    violations: list[str] = []
    if not isinstance(metadata, dict):
        return violations

    for key, val in metadata.items():
        full_path = f"{path}.{key}" if path else key

        # Check field name
        if key.lower() in PII_FIELD_NAMES:
            violations.append(f"PII field name: {full_path}")
            continue

        # Check value patterns
        if isinstance(val, str):
            for item in PII_VALUE_PATTERNS:
                pattern, label = item
                if pattern.match(val.strip()):
                    violations.append(f"PII value pattern ({label}) in {full_path}: {val[:3]}***")
                    break

        # Recurse into nested dicts
        if isinstance(val, dict):
            violations.extend(_check_pii_in_metadata(val, full_path))

        # Check lists of dicts
        if isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    violations.extend(_check_pii_in_metadata(item, f"{full_path}[{i}]"))

    return violations


def validate_metadata_no_pii(metadata: dict[str, Any]) -> None:
    """Validate that metadata contains no PII. Raises HoldingsError if PII found."""
    violations = _check_pii_in_metadata(metadata)
    if violations:
        raise HoldingsError(
            PII_DETECTED,
            f"PII detected in metadata: {'; '.join(violations[:3])}",
            {"violations": violations}
        )


# ── Expiry Validation ─────────────────────────────────

def validate_expiry_format(expires_at: str) -> datetime:
    """Validate that expires_at is a valid ISO 8601 datetime and is in the future.

    Returns the parsed datetime.
    Raises HoldingsError if invalid or already passed.
    """
    if not expires_at or not isinstance(expires_at, str):
        raise HoldingsError(INVALID_EXPIRY_FORMAT,
                          f"expires_at must be a non-empty ISO 8601 string, got: {expires_at!r}")

    try:
        exp_dt = datetime.fromisoformat(expires_at)
    except (ValueError, TypeError) as e:
        raise HoldingsError(INVALID_EXPIRY_FORMAT,
                          f"expires_at is not valid ISO 8601: {expires_at!r} — {e}")

    # Must be timezone-aware (if not, assume UTC)
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)

    # Must be in the future
    now = datetime.now(timezone.utc)
    if exp_dt <= now:
        raise HoldingsError(EXPIRY_ALREADY_PASSED,
                          f"expires_at is already passed: {expires_at}")

    return exp_dt


# PII field names that are forbidden in metadata
PII_FIELDS = {
    "phone", "mobile", "tel", "telephone",
    "name", "real_name", "username", "full_name",
    "address", "home_address", "street",
    "id_card", "id_number", "passport",
    "email", "mail",
    "birth", "birthday", "dob",
    "wechat", "weixin", "qq",
}

PII_VALUE_PATTERNS = [
    (re.compile(r'^1[3-9]\d{9}$'), "phone_number_pattern"),
    (re.compile(r'^\d{15}|\d{18}$'), "id_card_pattern"),
    (re.compile(r'^[\w.+-]+@[\w-]+\.[\w.-]+$'), "email_pattern"),
]


def validate_display_name_pseudonym(display_name: str) -> None:
    """Validate that display_name is a pseudonym, not a real name.

    Allowed formats:
    - Alphanumeric with hyphens/underscores: VIP-001, C-123, CUSTOMER_456
    - Pure numbers: 001, 12345
    - Prefix + number: A-001, VIP-2026-001

    Forbidden:
    - Chinese characters (likely real names)
    - Phone numbers
    - Email addresses
    - More than 30 characters
    """
    if not display_name:
        return

    if len(display_name) > 30:
        raise HoldingsError("PII_IN_DISPLAY_NAME",
            f"display_name too long (max 30 chars): {display_name[:10]}...")

    # Check for phone number pattern
    for pattern, label in PII_VALUE_PATTERNS:
        if pattern.match(display_name):
            raise HoldingsError("PII_IN_DISPLAY_NAME",
                f"display_name matches {label}: rejected")

    # Check for Chinese characters (likely real names)
    if re.search(r'[\u4e00-\u9fff]', display_name):
        raise HoldingsError("PII_IN_DISPLAY_NAME",
            f"display_name contains Chinese characters (use pseudonym like VIP-001): rejected")

    # Must be alphanumeric + hyphens/underscores only
    if not re.match(r'^[A-Za-z0-9_-]+$', display_name):
        raise HoldingsError("PII_IN_DISPLAY_NAME",
            f"display_name must be alphanumeric/hyphen/underscore only (e.g., VIP-001): rejected")


# ── Data Models ───────────────────────────────────────

@dataclass
class Customer:
    """Customer profile — manually entered, pseudonymous.

    PII rules:
    - No customer name or phone number stored
    - customer_id is a pseudonymous identifier
    - display_name is a label for staff reference (e.g., "VIP-001")
    - metadata is recursively checked for PII
    - contact_auth: three-state contact authorization
    """
    customer_id: str
    store_id: str
    display_name: str = ""
    created_at: str = ""
    contact_auth: str = ContactAuthStatus.UNKNOWN.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.customer_id:
            raise HoldingsError("INVALID_CUSTOMER_ID", "customer_id is required")
        if not self.store_id:
            raise HoldingsError(STORE_ID_REQUIRED, "store_id is required")
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.contact_auth not in [e.value for e in ContactAuthStatus]:
            self.contact_auth = ContactAuthStatus.UNKNOWN.value
        validate_metadata_no_pii(self.metadata)


@dataclass
class HoldingItem:
    """A purchasable/holdable item definition."""
    item_id: str
    store_id: str
    item_type: str
    item_name: str
    unit: str = "次"
    default_quantity: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.item_id:
            raise HoldingsError("INVALID_ITEM_ID", "item_id is required")
        if not self.store_id:
            raise HoldingsError(STORE_ID_REQUIRED, "store_id is required")
        if self.item_type not in [e.value for e in ItemType]:
            raise HoldingsError(ITEM_TYPE_INVALID,
                              f"item_type must be one of {[e.value for e in ItemType]}")
        if self.default_quantity <= 0:
            raise HoldingsError(INVALID_QUANTITY,
                              f"default_quantity must be > 0, got {self.default_quantity}")
        validate_metadata_no_pii(self.metadata)


@dataclass
class LedgerEntry:
    """Immutable ledger entry — append-only, NEVER modified or deleted.

    V0.1.1 changes:
    - entry_hash excludes status (status is runtime state, not content)
    - Reversal appends a new ADJUST entry; original entry is NEVER modified
    - Balance replay recognizes reversal_of: if an entry has a reversal pointing to it,
      that entry is excluded from balance computation

    Hash chain: each entry's prev_hash links to the previous entry's entry_hash,
    forming a tamper-evident chain per (customer_id, item_id) pair.

    Idempotency: transaction_id must be unique across the ledger.
    """
    entry_id: str
    transaction_id: str
    customer_id: str
    item_id: str
    store_id: str
    transaction_type: str
    quantity: int
    timestamp: str
    operator: str = ""
    note: str = ""
    prev_hash: str = ""
    entry_hash: str = ""
    status: str = EntryStatus.CONFIRMED.value
    reversal_of: str = ""

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = str(uuid.uuid4())
        if not self.transaction_id:
            raise HoldingsError("INVALID_TRANSACTION_ID", "transaction_id is required")
        if not self.customer_id:
            raise HoldingsError("INVALID_CUSTOMER_ID", "customer_id is required")
        if not self.store_id:
            raise HoldingsError(STORE_ID_REQUIRED, "store_id is required")
        if self.transaction_type not in [e.value for e in TransactionType]:
            raise HoldingsError("INVALID_TRANSACTION_TYPE",
                              f"transaction_type must be one of {[e.value for e in TransactionType]}")
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise HoldingsError(INVALID_QUANTITY,
                              f"quantity must be positive int, got {self.quantity}")
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.entry_hash:
            self.entry_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash of entry content.

        V0.1.1: EXCLUDES status — status is runtime state that changes on reversal.
        The hash represents the entry's identity, not its current lifecycle state.
        """
        content = {
            "entry_id": self.entry_id,
            "transaction_id": self.transaction_id,
            "customer_id": self.customer_id,
            "item_id": self.item_id,
            "store_id": self.store_id,
            "transaction_type": self.transaction_type,
            "quantity": self.quantity,
            "timestamp": self.timestamp,
            "operator": self.operator,
            "note": self.note,
            "prev_hash": self.prev_hash,
            "reversal_of": self.reversal_of,
        }
        raw = json.dumps(content, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEntry":
        return cls(**data)


@dataclass
class Balance:
    """Derived balance for a customer's holding item.

    Computed from ledger replay — never stored directly.
    """
    customer_id: str
    item_id: str
    store_id: str
    item_name: str = ""
    item_type: str = ""
    unit: str = "次"
    remaining_quantity: int = 0
    total_purchased: int = 0
    total_consumed: int = 0
    total_adjusted: int = 0
    last_transaction_at: str = ""
    entry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Utility ───────────────────────────────────────────

def generate_customer_id(store_id: str) -> str:
    return f"C-{store_id}-{uuid.uuid4().hex[:12]}"


def generate_item_id(store_id: str) -> str:
    return f"I-{store_id}-{uuid.uuid4().hex[:12]}"


def generate_transaction_id() -> str:
    return f"T-{uuid.uuid4().hex}"
