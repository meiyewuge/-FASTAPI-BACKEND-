#!/usr/bin/env python3
"""Real main-backend adapter tests (R1a P0).

These exercise the ACTUAL deployable adapter in the main-backend code domain
(`backend.app.adapters.daily_loop_adapter.DailyLoopAdapter`) — NOT the Daily Loop
package test helper. They prove key-root isolation is fail-closed and that error
text never leaks a secret value.
"""
import unittest, os, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.adapters.daily_loop_adapter import (
    DailyLoopAdapter, is_enabled, enforce_main_backend_key_isolation,
    MainBackendKeyIsolationError, FORBIDDEN_IN_MAIN_BACKEND,
)
# server verifier to prove a real adapter request round-trips
from app.daily_loop.api.s2s import S2SVerifier, derive_s2s_key

ADAPTER_SECRET = 'test_adapter_shared_secret_16c'
SECRET_SENTINEL = 'SUPERSECRETVALUE_do_not_leak_0123456789'


class MockClock:
    def __init__(self): self._t = 1_000_000.0
    def __call__(self): return self._t


class BackendAdapterTests(unittest.TestCase):

    def setUp(self):
        # baseline env: only the adapter shared secret, no main-backend flag
        for k in ('DM_MAIN_BACKEND', 'DM_DAILY_LOOP_ADAPTER_ENABLED',
                  *FORBIDDEN_IN_MAIN_BACKEND):
            os.environ.pop(k, None)
        os.environ['DM_ADAPTER_SHARED_SECRET'] = ADAPTER_SECRET
        self.clock = MockClock()

    def tearDown(self):
        for k in ('DM_MAIN_BACKEND', 'DM_DAILY_LOOP_ADAPTER_ENABLED',
                  *FORBIDDEN_IN_MAIN_BACKEND):
            os.environ.pop(k, None)

    def test_feature_flag_default_off(self):
        self.assertFalse(is_enabled())
        ad = DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        with self.assertRaises(RuntimeError):
            ad.build_headers('GET', '/v1/dl/internal/tasks', b'', 'U-OWN', 'S001',
                             query={'task_date': '2026-07-17'})

    def test_v2_roundtrip_verifies(self):
        os.environ['DM_DAILY_LOOP_ADAPTER_ENABLED'] = '1'
        ad = DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        q = {'task_date': '2026-07-17'}
        h = ad.build_headers('GET', '/v1/dl/internal/tasks', b'', 'U-OWN', 'S001', query=q)
        verifier = S2SVerifier(derive_s2s_key(ADAPTER_SECRET), clock=self.clock)
        # a real adapter-signed request passes the server verifier (no exception)
        verifier.verify('GET', '/v1/dl/internal/tasks', h, q, b'')
        self.assertNotIn('X-DM-Caller-Token', h)

    def test_fail_closed_caller_signing_key(self):
        os.environ['DM_MAIN_BACKEND'] = '1'
        os.environ['DM_CALLER_SIGNING_KEY'] = SECRET_SENTINEL
        with self.assertRaises(MainBackendKeyIsolationError) as cm:
            DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        self.assertIn('DM_CALLER_SIGNING_KEY', str(cm.exception))
        self.assertNotIn(SECRET_SENTINEL, str(cm.exception))  # value never leaked

    def test_fail_closed_recovery_signing_key(self):
        os.environ['DM_MAIN_BACKEND'] = '1'
        os.environ['DM_PLATFORM_RECOVERY_SIGNING_KEY'] = SECRET_SENTINEL
        with self.assertRaises(MainBackendKeyIsolationError) as cm:
            DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        self.assertIn('DM_PLATFORM_RECOVERY_SIGNING_KEY', str(cm.exception))
        self.assertNotIn(SECRET_SENTINEL, str(cm.exception))

    def test_fail_closed_recovery_secret(self):
        os.environ['DM_MAIN_BACKEND'] = '1'
        os.environ['DM_PLATFORM_RECOVERY_SECRET'] = SECRET_SENTINEL
        with self.assertRaises(MainBackendKeyIsolationError) as cm:
            DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        self.assertIn('DM_PLATFORM_RECOVERY_SECRET', str(cm.exception))
        self.assertNotIn(SECRET_SENTINEL, str(cm.exception))

    def test_fail_closed_vault_master_key(self):
        os.environ['DM_MAIN_BACKEND'] = '1'
        os.environ['DM_VAULT_MASTER_KEY'] = SECRET_SENTINEL
        with self.assertRaises(MainBackendKeyIsolationError) as cm:
            DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        self.assertIn('DM_VAULT_MASTER_KEY', str(cm.exception))
        self.assertNotIn(SECRET_SENTINEL, str(cm.exception))

    def test_main_backend_with_only_adapter_secret_ok(self):
        os.environ['DM_MAIN_BACKEND'] = '1'  # main-backend mode, no forbidden roots
        ad = DailyLoopAdapter(ADAPTER_SECRET, clock=self.clock)
        self.assertIsNotNone(ad)

    def test_error_text_never_contains_secret_value(self):
        os.environ['DM_MAIN_BACKEND'] = '1'
        for k in FORBIDDEN_IN_MAIN_BACKEND:
            os.environ[k] = SECRET_SENTINEL
        try:
            with self.assertRaises(MainBackendKeyIsolationError) as cm:
                enforce_main_backend_key_isolation()
            msg = str(cm.exception)
            self.assertNotIn(SECRET_SENTINEL, msg)
            for k in FORBIDDEN_IN_MAIN_BACKEND:
                self.assertIn(k, msg)  # names present, values absent
        finally:
            for k in FORBIDDEN_IN_MAIN_BACKEND:
                os.environ.pop(k, None)


if __name__ == '__main__':
    unittest.main()
