#!/usr/bin/env python3
"""Daily Loop SERVER-SIDE test/dev signing helper (dm-s2s-v2).

R1 NOTE: this module is NOT the production main-backend adapter. It lives inside
the Daily Loop package and is used only by the Daily Loop test-suite to forge
valid v2-signed requests against its own verifier. The real, deployable
main-backend adapter lives in the separate backend code domain at
`backend/app/adapters/daily_loop_adapter.py`, which does NOT import this package.
Both implementations are pinned to the same golden vectors to prevent drift.

DEFAULT OFF (DM_DAILY_LOOP_ADAPTER_ENABLED != '1'). Never holds
DM_CALLER_SIGNING_KEY; uses only DM_ADAPTER_SHARED_SECRET; no network I/O.
"""
from __future__ import annotations
import os, time, uuid

from app.daily_loop.api.s2s import derive_s2s_key, sign_request, S2S_VERSION


def is_enabled() -> bool:
    return os.environ.get('DM_DAILY_LOOP_ADAPTER_ENABLED') == '1'


class MainBackendAdapter:
    """Server-side test helper: builds v2-signed S2S headers (identity + query
    bound). Off unless explicitly enabled."""

    def __init__(self, shared_secret: str = None, clock=None):
        self._clock = clock or time.time
        secret = shared_secret if shared_secret is not None else os.environ.get('DM_ADAPTER_SHARED_SECRET')
        if not secret or len(secret) < 16:
            raise SystemExit(2)
        self._key = derive_s2s_key(secret)

    def build_headers(self, method: str, path: str, body: bytes,
                      auth_user_id: str, target_store_id: str,
                      query: dict = None) -> dict:
        """Return the full header set for an outbound internal call. The signature
        binds identity + query (v2). DM_CALLER_SIGNING_KEY is never referenced."""
        if not is_enabled():
            raise RuntimeError('adapter disabled: set DM_DAILY_LOOP_ADAPTER_ENABLED=1 to enable')
        ts = repr(self._clock())
        nonce = uuid.uuid4().hex
        sig = sign_request(self._key, method, path, body or b'', ts, nonce,
                           query or {}, auth_user_id, target_store_id)
        return {
            'X-DM-S2S-Version': S2S_VERSION,
            'X-DM-S2S-Timestamp': ts,
            'X-DM-S2S-Nonce': nonce,
            'X-DM-S2S-Signature': sig,
            'X-DM-Auth-User-Id': auth_user_id,
            'X-DM-Target-Store-Id': target_store_id,
        }
