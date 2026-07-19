#!/usr/bin/env python3
"""Production main-backend -> Daily Loop adapter (dm-s2s-v2).

Lives in the REAL main-backend code domain (`backend/app/adapters/`). It is
fully SELF-CONTAINED: it does NOT import the Daily Loop top-level `app` package
and does NOT put Daily Loop on sys.path (the two `app` namespaces would collide).
The small amount of canonicalization duplicated here is pinned to the SAME golden
vectors as the Daily Loop server verifier (see tests/test_c1b_golden_vectors.py),
so the two implementations can never drift.

Contract (C1-B-R1 work order §3):
  - feature flag DEFAULT OFF (DM_DAILY_LOOP_ADAPTER_ENABLED != '1');
  - not mounted on any external router;
  - main backend holds ONLY DM_ADAPTER_SHARED_SECRET, never DM_CALLER_SIGNING_KEY;
  - emits real v2 requests the Daily Loop verifier accepts;
  - no change to existing main-backend auth/router behaviour (import-only module).
"""
from __future__ import annotations
import os, time, uuid, hmac, hashlib, json, re

# ---- self-contained canonicalization (mirror of the Daily Loop verifier) ----
# Pinned to shared golden vectors; DO NOT edit without updating the vectors and
# the server side in lock-step.
S2S_VERSION = 'dm-s2s-v2'
_IDENT_RE = re.compile(r'^[A-Za-z0-9_.:@-]{1,128}$')


def _body_sha256(body: bytes) -> str:
    return hashlib.sha256(body or b'').hexdigest()


def _canonical_query_sha256(query) -> str:
    payload = json.dumps(query or {}, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _canonical_identity_sha256(auth_user_id: str, target_store_id: str) -> str:
    ident = {'auth_user_id': auth_user_id, 'target_store_id': target_store_id}
    payload = json.dumps(ident, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _canonical_message(method, path, ts, nonce, query_sha, identity_sha, body_sha) -> bytes:
    return '\n'.join([S2S_VERSION, method.upper(), path, str(ts), nonce,
                      query_sha, identity_sha, body_sha]).encode('utf-8')


def _derive_key(shared_secret: str) -> bytes:
    return hashlib.scrypt(shared_secret.encode(), salt=b'dm_adapter_s2s', n=16384, r=8, p=1, dklen=32)


def canonical_signature(shared_secret_derived: bytes, method: str, path: str, body: bytes,
                        timestamp: str, nonce: str, query, auth_user_id: str,
                        target_store_id: str) -> str:
    return hmac.new(
        shared_secret_derived,
        _canonical_message(method, path, timestamp, nonce,
                           _canonical_query_sha256(query),
                           _canonical_identity_sha256(auth_user_id, target_store_id),
                           _body_sha256(body)),
        hashlib.sha256).hexdigest()


def is_enabled(enabled=None) -> bool:
    """Feature enablement. R1c: the REAL request path passes the authoritative
    value from Settings (``settings.dm_daily_loop_adapter_enabled``); the os.environ
    read is only a fallback for direct/legacy callers so there is a single source of
    truth on the Facade path."""
    if enabled is not None:
        return bool(enabled)
    return os.environ.get('DM_DAILY_LOOP_ADAPTER_ENABLED') == '1'


class MainBackendKeyIsolationError(RuntimeError):
    """Raised (fail-closed) when a main-backend adapter process is found holding a
    secret root it must never carry. The message names the OFFENDING KEY NAMES
    only — never their values."""


class AdapterConfigError(RuntimeError):
    """Raised (fail-closed) when the adapter is constructed without a usable S2S
    shared secret. Carries no secret VALUE."""


# Secret roots that must NEVER be present in a main-backend process. The main
# backend is allowed exactly ONE DM_* secret: DM_ADAPTER_SHARED_SECRET.
FORBIDDEN_IN_MAIN_BACKEND = (
    'DM_CALLER_SIGNING_KEY',            # identity minting stays inside Daily Loop
    'DM_PLATFORM_RECOVERY_SIGNING_KEY', # break-glass recovery root
    'DM_PLATFORM_RECOVERY_SECRET',      # break-glass recovery root
    'DM_VAULT_MASTER_KEY',              # vault master key
)


def enforce_main_backend_key_isolation(env=None, main_backend=None) -> None:
    """Fail-closed if this main-backend process holds any forbidden secret root.

    R1c: whether this is a main backend is driven by the authoritative
    ``main_backend`` flag passed in (from ``settings.dm_main_backend``) rather than
    a second os.environ read; when it is None we fall back to DM_MAIN_BACKEND for
    direct/legacy callers. Enforcement still SCANS the process environment for the
    forbidden Caller/Recovery/Vault roots. Combined dev/test processes that
    legitimately carry Daily Loop roots pass main_backend=False and are unaffected.
    Never prints secret VALUES — only the offending key names."""
    env = env if env is not None else os.environ
    if main_backend is None:
        main_backend = env.get('DM_MAIN_BACKEND') == '1'
    if not main_backend:
        return
    present = sorted(k for k in FORBIDDEN_IN_MAIN_BACKEND if env.get(k))
    if present:
        raise MainBackendKeyIsolationError(
            'main-backend process must not hold secret roots: ' + ', '.join(present))


class DailyLoopAdapter:
    """Builds signed v2 S2S headers for outbound calls from the main backend to
    the Daily Loop internal API. Off unless explicitly enabled. Holds only the
    S2S shared secret; never the caller signing / recovery / vault roots."""

    def __init__(self, shared_secret: str = None, main_backend=None, enabled=None, clock=None):
        # P0 (R1a): hard key-root isolation. R1c: config is injected from the single
        # Settings source (shared_secret / main_backend / enabled) so the adapter no
        # longer needs a second os.environ path to work; a leaked Caller/Recovery/
        # Vault root still fails closed (isolation scans the process env).
        enforce_main_backend_key_isolation(main_backend=main_backend)
        self._clock = clock or time.time
        self._enabled = is_enabled(enabled)
        secret = shared_secret if shared_secret is not None else os.environ.get('DM_ADAPTER_SHARED_SECRET')
        if not secret or len(secret) < 16:
            # fail-closed (missing/short shared secret); no secret value in the error
            raise AdapterConfigError('adapter shared secret missing or too short')
        self._key = _derive_key(secret)

    def build_headers(self, method: str, path: str, body: bytes,
                      auth_user_id: str, target_store_id: str, query: dict = None) -> dict:
        if not self._enabled:
            raise RuntimeError('adapter disabled: enable via settings.dm_daily_loop_adapter_enabled')
        if not _IDENT_RE.match(auth_user_id or '') or not _IDENT_RE.match(target_store_id or ''):
            raise ValueError('identity fields must be bounded and newline-free')
        ts = repr(self._clock())
        nonce = uuid.uuid4().hex
        sig = canonical_signature(self._key, method, path, body or b'', ts, nonce,
                                  query or {}, auth_user_id, target_store_id)
        return {
            'X-DM-S2S-Version': S2S_VERSION,
            'X-DM-S2S-Timestamp': ts,
            'X-DM-S2S-Nonce': nonce,
            'X-DM-S2S-Signature': sig,
            'X-DM-Auth-User-Id': auth_user_id,
            'X-DM-Target-Store-Id': target_store_id,
        }
