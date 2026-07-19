#!/usr/bin/env python3
"""S2S (service-to-service) authentication for the C1-B internal API — protocol
dm-s2s-v2.

R1 SECURITY FIX (P0-1): the signed message now binds the caller's PERMISSION
IDENTITY (auth_user_id, target_store_id) AND the canonical query, in addition to
method/path/timestamp/nonce/body. In v1 an attacker could sign as U-STF/S001 and
then rewrite the identity headers to U-OWN2/S002 (or tamper the date query) while
keeping a valid signature. v2 makes any such tamper flip the HMAC -> 401.

Canonical message (unambiguous, newline-delimited, fixed field order):

    dm-s2s-v2 \n method \n path \n timestamp \n nonce \n
    query_sha256 \n identity_sha256 \n body_sha256

where
    query_sha256    = sha256( json(query,  sort_keys, separators=(',',':')) )
    identity_sha256 = sha256( json(ident,  sort_keys, separators=(',',':')) )
    ident           = {"auth_user_id": ..., "target_store_id": ...}

Verification (fail-closed, terse codes, no internal detail leaked):
  - version header present and == 'dm-s2s-v2' (missing or v1 -> 401);
  - timestamp finite (reject NaN/Inf) and within +/- 60s;
  - nonce bounded charset/length, single-use, bounded-TTL cache with a hard cap;
  - identity headers present, bounded charset/length, no newlines;
  - HMAC-SHA256 constant-time compared; the nonce is only consumed AFTER the
    signature verifies, so a bad signature can never burn a nonce.

The canonicalization here is the single source of truth; the main-backend
adapter carries an independent copy pinned to shared golden vectors.
"""
from __future__ import annotations
import hmac, hashlib, os, time, re, json, math
from collections import OrderedDict
from typing import Optional

from app.daily_loop.api.errors import unauthorized

S2S_VERSION = 'dm-s2s-v2'
MAX_SKEW_SECONDS = 60
NONCE_TTL_SECONDS = 120
NONCE_MAX_ENTRIES = 4096
NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
# identity fields: bounded, printable, NO newlines/controls
IDENT_RE = re.compile(r'^[A-Za-z0-9_.:@-]{1,128}$')


# ---- canonicalization (single source of truth) ---------------------------

def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body or b'').hexdigest()


def canonical_query_sha256(query: Optional[dict]) -> str:
    payload = json.dumps(query or {}, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def canonical_identity_sha256(auth_user_id: str, target_store_id: str) -> str:
    ident = {'auth_user_id': auth_user_id, 'target_store_id': target_store_id}
    payload = json.dumps(ident, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def canonical_message(method: str, path: str, timestamp: str, nonce: str,
                      query_sha: str, identity_sha: str, body_hash: str) -> bytes:
    return '\n'.join([S2S_VERSION, method.upper(), path, str(timestamp), nonce,
                      query_sha, identity_sha, body_hash]).encode('utf-8')


def valid_identity_field(v) -> bool:
    return isinstance(v, str) and bool(IDENT_RE.match(v))


# ---- nonce cache ---------------------------------------------------------

class NonceCache:
    """Bounded, TTL-expiring single-use nonce store. Single-worker service."""

    def __init__(self, ttl: float = NONCE_TTL_SECONDS, max_entries: int = NONCE_MAX_ENTRIES, clock=None):
        self._ttl = ttl
        self._max = max_entries
        self._clock = clock or time.time
        self._store: "OrderedDict[str, float]" = OrderedDict()

    def _evict_expired(self, now: float):
        while self._store:
            k, exp = next(iter(self._store.items()))
            if exp <= now:
                self._store.popitem(last=False)
            else:
                break
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def check_and_add(self, nonce: str) -> bool:
        now = self._clock()
        self._evict_expired(now)
        if nonce in self._store and self._store[nonce] > now:
            return False
        self._store[nonce] = now + self._ttl
        self._store.move_to_end(nonce)
        # hard invariant: never exceed the cap, even transiently
        while len(self._store) > self._max:
            self._store.popitem(last=False)
        return True


# ---- verifier ------------------------------------------------------------

class S2SVerifier:
    def __init__(self, shared_secret: bytes, clock=None, nonce_cache: Optional[NonceCache] = None):
        self._secret = shared_secret
        self._clock = clock or time.time
        self._nonces = nonce_cache or NonceCache(clock=self._clock)

    @classmethod
    def from_env(cls, clock=None) -> 'S2SVerifier':
        secret = os.environ.get('DM_ADAPTER_SHARED_SECRET')
        if not secret or len(secret) < 16 or secret.startswith('dev_'):
            import sys
            sys.stderr.write('DM_ADAPTER_SHARED_SECRET missing, too short, or dev fallback\n')
            raise SystemExit(2)
        return cls(derive_s2s_key(secret), clock=clock)

    def verify(self, method: str, path: str, headers: dict,
               query: Optional[dict], body: bytes) -> None:
        """Raise ApiError(401) on any failure; return None on success. Binds
        identity + query into the signature (v2)."""
        h = {k.lower(): v for k, v in (headers or {}).items()}
        sig = h.get('x-dm-s2s-signature')
        ts = h.get('x-dm-s2s-timestamp')
        nonce = h.get('x-dm-s2s-nonce')
        version = h.get('x-dm-s2s-version')          # NO default: missing -> reject
        auth_user_id = h.get('x-dm-auth-user-id')
        target_store_id = h.get('x-dm-target-store-id')

        if version != S2S_VERSION:                    # missing / v1 / anything else
            raise unauthorized('E-S2S-VERSION', 's2s version unsupported')
        if not sig or not ts or not nonce:
            raise unauthorized('E-S2S-MISSING', 's2s headers missing')
        if not NONCE_RE.match(nonce):
            raise unauthorized('E-S2S-NONCE', 's2s nonce malformed')
        if not auth_user_id or not target_store_id:
            raise unauthorized('E-S2S-IDENTITY', 's2s identity headers missing')
        if not valid_identity_field(auth_user_id) or not valid_identity_field(target_store_id):
            raise unauthorized('E-S2S-IDENTITY', 's2s identity headers malformed')
        try:
            ts_val = float(ts)
        except (TypeError, ValueError):
            raise unauthorized('E-S2S-TIMESTAMP', 's2s timestamp malformed')
        if not math.isfinite(ts_val):                 # reject NaN / Inf / -Inf
            raise unauthorized('E-S2S-TIMESTAMP', 's2s timestamp not finite')
        now = self._clock()
        if abs(now - ts_val) > MAX_SKEW_SECONDS:
            raise unauthorized('E-S2S-EXPIRED', 's2s timestamp outside window')

        expected = hmac.new(
            self._secret,
            canonical_message(method, path, ts, nonce,
                              canonical_query_sha256(query),
                              canonical_identity_sha256(auth_user_id, target_store_id),
                              body_sha256(body)),
            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise unauthorized('E-S2S-SIGNATURE', 's2s signature invalid')
        # replay guard LAST: a bad signature never consumes a nonce
        if not self._nonces.check_and_add(nonce):
            raise unauthorized('E-S2S-REPLAY', 's2s nonce replay')


# ---- signing helpers (adapter / tests) -----------------------------------

def derive_s2s_key(shared_secret: str) -> bytes:
    return hashlib.scrypt(shared_secret.encode(), salt=b'dm_adapter_s2s', n=16384, r=8, p=1, dklen=32)


def sign_request(shared_secret_derived: bytes, method: str, path: str, body: bytes,
                 timestamp: str, nonce: str, query: Optional[dict],
                 auth_user_id: str, target_store_id: str) -> str:
    """v2 signature over the full canonical message (identity + query bound).
    Takes the already scrypt-derived key (same derivation as from_env)."""
    return hmac.new(
        shared_secret_derived,
        canonical_message(method, path, timestamp, nonce,
                          canonical_query_sha256(query),
                          canonical_identity_sha256(auth_user_id, target_store_id),
                          body_sha256(body)),
        hashlib.sha256).hexdigest()
