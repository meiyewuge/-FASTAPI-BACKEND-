#!/usr/bin/env python3
"""C1-B-R1 internal API test matrix (stdlib only; no running server, no FastAPI).

Drives the framework-agnostic DailyLoopApi core to prove the full security
semantics required by the C1-B work order matrix plus the R1 security closure:
dm-s2s-v2 binds identity + query into the HMAC (P0-1), S2S hardening (P1-2), and
structured 503 on dependency failure (P1-1). Item 13 (no regression on invariants
/ mutations / fault) is proven by re-running the frozen suites and recorded in the
API test report.

When DM_C1B_EVIDENCE_PATH is set, per-case structured evidence is written there.
"""
import unittest, os, sys, tempfile, json, time, uuid, sqlite3, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('DM_VAULT_MASTER_KEY', 'test_master_key_at_least_16_chars_long')
os.environ.setdefault('DM_CALLER_SIGNING_KEY', 'test_signing_key_at_least_16_chars')
os.environ.setdefault('DM_SERVICE_PRINCIPAL_SECRET', 'test_service_secret')
os.environ.setdefault('DM_ADAPTER_SHARED_SECRET', 'test_adapter_shared_secret_16c')

from app.daily_loop.services.repository import AuthRepository
from app.daily_loop.services.caller_context import TrustedMemberProvider
from app.daily_loop.models import StoreMember, DailyCustomerTask, Appointment, CustomerProfile
from app.daily_loop.api.s2s import (S2SVerifier, NonceCache, derive_s2s_key, sign_request,
                                    S2S_VERSION, NONCE_MAX_ENTRIES)
from app.daily_loop.api.identity_gateway import IdentityGateway
from app.daily_loop.api.core import DailyLoopApi
from app.daily_loop.api.serialization import TASK_FIELDS, APPOINTMENT_FIELDS
from app.daily_loop.adapter.main_backend_adapter import MainBackendAdapter, is_enabled

_EVIDENCE = []


def tearDownModule():
    p = os.environ.get('DM_C1B_EVIDENCE_PATH')
    if p:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'report_type': 'C1B_API_TEST_MATRIX', 'version': 'V1.3A.9-C1-B-R1',
                       'protocol': S2S_VERSION,
                       'total': len(_EVIDENCE), 'passed': sum(1 for e in _EVIDENCE if e['passed']),
                       'cases': _EVIDENCE}, f, indent=2, ensure_ascii=False)


class MockClock:
    def __init__(self): self._t = 1_000_000.0
    def __call__(self): return self._t
    def advance(self, s): self._t += s


ADAPTER_SECRET = 'test_adapter_shared_secret_16c'
TASKS = '/v1/dl/internal/tasks'
APPTS = '/v1/dl/internal/appointments'


class C1BApiTests(unittest.TestCase):

    def setUp(self):
        self.clock = MockClock()
        fd, self.auth_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        self.repo = AuthRepository(self.auth_path)
        self.repo.init_schema()
        self.repo.insert_member(StoreMember('M-OWN', 'S001', 'U-OWN', 'owner', 'own', 'active'))
        self.repo.insert_member(StoreMember('M-MGR', 'S001', 'U-MGR', 'manager', 'mgr', 'active'))
        self.repo.insert_member(StoreMember('M-STF', 'S001', 'U-STF', 'staff', 'stf', 'active'))
        self.repo.insert_member(StoreMember('M-STF2', 'S001', 'U-STF2', 'staff', 'stf2', 'active'))
        self.repo.insert_member(StoreMember('M-OWN2', 'S002', 'U-OWN2', 'owner', 'own2', 'active'))
        self.repo.insert_member(StoreMember('M-DIS', 'S001', 'U-DIS', 'staff', 'dis', 'disabled'))
        self.repo.insert_member(StoreMember('M-LEFT', 'S001', 'U-LEFT', 'staff', 'left', 'left'))
        self._insert_customer('C-1', 'S001'); self._insert_customer('C-2', 'S001')
        self._insert_customer('C-9', 'S002')
        today = '2026-07-17'
        self.today = today
        self.repo.insert_task(DailyCustomerTask('T-1', 'S001', 'C-1', today, 'M-STF', 'assigned', 5, 'care', 'B-1'))
        self.repo.insert_task(DailyCustomerTask('T-2', 'S001', 'C-2', today, 'M-STF', 'draft', 3, 'care', 'B-1'))
        self.repo.insert_task(DailyCustomerTask('T-3', 'S001', 'C-1', today, 'M-STF2', 'assigned', 5, 'care', 'B-1'))
        self.repo.insert_task(DailyCustomerTask('T-9', 'S002', 'C-9', today, 'M-OWN2', 'assigned', 5, 'care', 'B-9'))
        self.repo.insert_appointment(Appointment('A-1', 'S001', 'C-1', 'M-STF', today, '10:00', 60, 'scheduled'))
        self.repo.insert_appointment(Appointment('A-9', 'S002', 'C-9', 'M-OWN2', today, '11:00', 60, 'scheduled'))
        self.repo.close()

        self.provider = TrustedMemberProvider.from_env(self.auth_path, clock=self.clock)
        self.s2s = S2SVerifier(derive_s2s_key(ADAPTER_SECRET), clock=self.clock)
        self.api = DailyLoopApi(self.auth_path, self.provider, self.s2s)
        self.key = derive_s2s_key(ADAPTER_SECRET)

    def tearDown(self):
        try: os.unlink(self.auth_path)
        except OSError: pass

    def _insert_customer(self, cid, store):
        r = AuthRepository(self.auth_path)
        r.insert_customer(CustomerProfile(cid, store, 'name'))
        r.close()

    def _headers(self, method, path, auth_user_id, store_id, query=None, body=b'',
                 nonce=None, ts=None, version=None):
        """Build fully v2-signed headers binding identity + query into the HMAC."""
        ts = repr(self.clock()) if ts is None else ts
        nonce = nonce or uuid.uuid4().hex
        sig = sign_request(self.key, method, path, body, ts, nonce, query or {},
                           auth_user_id, store_id)
        return {'X-DM-S2S-Version': version or S2S_VERSION, 'X-DM-S2S-Timestamp': ts,
                'X-DM-S2S-Nonce': nonce, 'X-DM-S2S-Signature': sig,
                'X-DM-Auth-User-Id': auth_user_id, 'X-DM-Target-Store-Id': store_id}

    def _rec(self, case, status, expect, extra=None):
        ev = {'case': case, 'status': status, 'expected': expect, 'passed': status == expect}
        if extra: ev.update(extra)
        _EVIDENCE.append(ev)
        return ev

    # 1 healthz -----------------------------------------------------------
    def test_01_healthz_fixed(self):
        st, body = self.api.dispatch('GET', '/v1/dl/healthz')
        self.assertEqual(st, 200)
        self.assertEqual(body, {'status': 'ok'})
        self._rec('01_healthz_fixed', st, 200, {'body': body})

    # 2 readyz ------------------------------------------------------------
    def test_02_readyz_ok_and_failclosed(self):
        st, body = self.api.dispatch('GET', '/v1/dl/readyz')
        self.assertEqual(st, 200)
        self.assertEqual(body, {'ready': True, 'migrations_applied': True})
        broken = DailyLoopApi('/nonexistent/dir/x.db', self.provider, self.s2s)
        st2, body2 = broken.dispatch('GET', '/v1/dl/readyz')
        self.assertEqual(st2, 503)
        self.assertEqual(body2.get('error_code'), 'E-NOT-READY')
        self.assertNotIn('migrations_applied', body2)
        self._rec('02_readyz_ok', st, 200)
        self._rec('02_readyz_failclosed', st2, 503, {'body': body2})

    # 3 S2S ---------------------------------------------------------------
    def test_03_s2s_all_missing_version_rejected(self):
        st, body = self.api.dispatch('GET', TASKS,
                                     headers={'X-DM-Auth-User-Id': 'U-OWN', 'X-DM-Target-Store-Id': 'S001'})
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-VERSION')  # version missing -> reject
        self._rec('03_s2s_missing_version', st, 401, {'code': body['error_code']})

    def test_03_s2s_sig_missing_with_version(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001')
        del h['X-DM-S2S-Signature']
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-MISSING')
        self._rec('03_s2s_sig_missing', st, 401, {'code': body['error_code']})

    def test_03_s2s_wrong_signature(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001')
        h['X-DM-S2S-Signature'] = 'deadbeef' * 8
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self._rec('03_s2s_wrong_signature', st, 401, {'code': body['error_code']})

    def test_03_s2s_body_tamper(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', body=b'')
        st, body = self.api.dispatch('GET', TASKS, headers=h, body=b'{"x":1}')
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self._rec('03_s2s_body_tamper', st, 401, {'code': body['error_code']})

    def test_03_s2s_expired_timestamp(self):
        old_ts = repr(self.clock() - 120)
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', ts=old_ts)
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-EXPIRED')
        self._rec('03_s2s_expired', st, 401, {'code': body['error_code']})

    def test_03_s2s_nonce_replay(self):
        nonce = uuid.uuid4().hex
        q = {'task_date': self.today}
        h1 = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q, nonce=nonce)
        st1, _ = self.api.dispatch('GET', TASKS, headers=h1, query=q)
        self.assertEqual(st1, 200)
        h2 = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q, nonce=nonce)
        st2, body2 = self.api.dispatch('GET', TASKS, headers=h2, query=q)
        self.assertEqual(st2, 401)
        self.assertEqual(body2['error_code'], 'E-S2S-REPLAY')
        self._rec('03_s2s_nonce_replay', st2, 401, {'first': st1, 'code': body2['error_code']})

    def test_03_bad_signature_does_not_consume_nonce(self):
        nonce = uuid.uuid4().hex
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q, nonce=nonce)
        h['X-DM-S2S-Signature'] = 'deadbeef' * 8
        st1, _ = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st1, 401)
        h2 = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q, nonce=nonce)
        st2, _ = self.api.dispatch('GET', TASKS, headers=h2, query=q)
        self.assertEqual(st2, 200)
        self._rec('03_bad_sig_keeps_nonce', st2, 200)

    # 3R P0-1 identity/query binding (the exact exploit + tampers) --------
    def test_03R_exploit_identity_swap_now_401(self):
        """ChatGPT P0-1 exploit: sign as U-STF/S001 then rewrite headers to
        U-OWN2/S002. v2 binds identity into the HMAC -> 401, no S002 data."""
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-STF', 'S001', query=q)
        h['X-DM-Auth-User-Id'] = 'U-OWN2'
        h['X-DM-Target-Store-Id'] = 'S002'
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self.assertNotIn('items', body)
        self._rec('03R_exploit_identity_swap', st, 401, {'code': body['error_code']})

    def test_03R_tamper_auth_user_id(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-STF', 'S001', query=q)
        h['X-DM-Auth-User-Id'] = 'U-OWN'
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self._rec('03R_tamper_auth_user', st, 401, {'code': body['error_code']})

    def test_03R_tamper_target_store(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q)
        h['X-DM-Target-Store-Id'] = 'S002'
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self._rec('03R_tamper_target_store', st, 401, {'code': body['error_code']})

    def test_03R_tamper_query_date(self):
        signed_q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=signed_q)
        tampered_q = {'task_date': '2020-01-01'}
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=tampered_q)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-SIGNATURE')
        self._rec('03R_tamper_query', st, 401, {'code': body['error_code']})

    def test_03R_identity_missing_after_version(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001')
        del h['X-DM-Auth-User-Id']
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-IDENTITY')
        self._rec('03R_identity_missing', st, 401, {'code': body['error_code']})

    def test_03R_identity_illegal_chars(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001')
        h['X-DM-Auth-User-Id'] = 'U\nOWN'  # newline injection
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-IDENTITY')
        self._rec('03R_identity_illegal', st, 401, {'code': body['error_code']})

    def test_03R_identity_oversized(self):
        big = 'U' * 200
        h = self._headers('GET', TASKS, big, 'S001')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-IDENTITY')
        self._rec('03R_identity_oversized', st, 401, {'code': body['error_code']})

    def test_03R_version_v1_rejected(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', version='dm-s2s-v1')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-S2S-VERSION')
        self._rec('03R_version_v1', st, 401, {'code': body['error_code']})

    def test_03R_timestamp_nan_inf_rejected(self):
        for bad in ('nan', 'inf', '-inf', 'Infinity'):
            h = self._headers('GET', TASKS, 'U-OWN', 'S001', ts=bad)
            st, body = self.api.dispatch('GET', TASKS, headers=h)
            self.assertEqual(st, 401, f'ts={bad}')
            self.assertEqual(body['error_code'], 'E-S2S-TIMESTAMP', f'ts={bad}')
        self._rec('03R_timestamp_nan_inf', 401, 401)

    def test_03R_nonce_cache_bounded(self):
        cache = NonceCache(ttl=10_000, max_entries=64, clock=self.clock)
        for i in range(500):
            cache.check_and_add(f'nonce_{i:040d}')
        self.assertLessEqual(len(cache._store), 64)
        self._rec('03R_nonce_cache_bounded', len(cache._store), len(cache._store),
                  {'size': len(cache._store), 'cap': 64})

    # 4 audience ----------------------------------------------------------
    def test_04_audience_constant_anti_drift(self):
        gw = IdentityGateway(self.provider)
        self.assertEqual(gw.audience, TrustedMemberProvider.AUDIENCE)
        self.assertEqual(TrustedMemberProvider.AUDIENCE, 'dm_vault_business_v1')
        ctx = self.provider.create('U-OWN', 'S001')
        self.assertEqual(ctx.audience, 'dm_vault_business_v1')
        self._rec('04_audience_anti_drift', 200, 200, {'audience': ctx.audience})

    # 5 identity fail-closed ----------------------------------------------
    def test_05_no_mapping_401(self):
        h = self._headers('GET', TASKS, 'U-UNKNOWN', 'S001')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertEqual(body['error_code'], 'E-IDENTITY-NO-MAPPING')
        self._rec('05_no_mapping', st, 401, {'code': body['error_code']})

    def test_05_disabled_member_401(self):
        h = self._headers('GET', TASKS, 'U-DIS', 'S001')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self._rec('05_disabled', st, 401, {'code': body['error_code']})

    def test_05_left_member_401(self):
        h = self._headers('GET', TASKS, 'U-LEFT', 'S001')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self._rec('05_left', st, 401, {'code': body['error_code']})

    def test_05_expired_ctx_verify_false(self):
        ctx = self.provider.create('U-OWN', 'S001')
        self.assertTrue(self.provider.verify(ctx))
        self.clock.advance(301)
        self.assertFalse(self.provider.verify(ctx))
        self._rec('05_expired_ctx', 401, 401, {'note': 'verify() false after TTL'})

    def test_05_role_drift_verify_false(self):
        ctx = self.provider.create('U-OWN', 'S001')
        self.assertTrue(self.provider.verify(ctx))
        c = sqlite3.connect(self.auth_path)
        c.execute("UPDATE dl_store_member SET role='staff' WHERE member_id='M-OWN'"); c.commit(); c.close()
        self.assertFalse(self.provider.verify(ctx))
        self._rec('05_role_drift', 401, 401, {'note': 'verify() false on role drift'})

    def test_05_ctx_none_no_attributeerror(self):
        h = self._headers('GET', TASKS, 'U-DIS', 'S001')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self.assertIn('error_code', body)
        self._rec('05_ctx_none_structured', st, 401)

    # 6 staff isolation ---------------------------------------------------
    def test_06_staff_sees_only_own_tasks(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-STF', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 200)
        ids = sorted(i['task_id'] for i in body['items'])
        self.assertEqual(ids, ['T-1', 'T-2'])
        for i in body['items']:
            self.assertEqual(i['assigned_member_id'], 'M-STF')
        self._rec('06_staff_own_tasks', st, 200, {'ids': ids})

    # 7 owner/manager -----------------------------------------------------
    def test_07_owner_sees_all_store_tasks(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 200)
        ids = sorted(i['task_id'] for i in body['items'])
        self.assertEqual(ids, ['T-1', 'T-2', 'T-3'])
        self._rec('07_owner_all_tasks', st, 200, {'ids': ids})

    def test_07_manager_sees_all_store_tasks(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-MGR', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 200)
        self.assertEqual(len(body['items']), 3)
        self._rec('07_manager_all_tasks', st, 200)

    def test_07_appointments_own_store_all_roles(self):
        q = {'date': self.today}
        for uid in ('U-OWN', 'U-MGR', 'U-STF'):
            h = self._headers('GET', APPTS, uid, 'S001', query=q)
            st, body = self.api.dispatch('GET', APPTS, headers=h, query=q)
            self.assertEqual(st, 200)
            ids = sorted(i['appointment_id'] for i in body['items'])
            self.assertEqual(ids, ['A-1'])
        self._rec('07_appointments_own_store', 200, 200)

    # 8 cross-store + actor ----------------------------------------------
    def test_08_cross_store_403_no_disclosure(self):
        q = {'task_date': self.today, 'store_id': 'S002'}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 403)
        self.assertEqual(body['error_code'], 'E-SCOPE')
        self.assertNotIn('items', body)
        self._rec('08_cross_store_scope', st, 403, {'code': body['error_code']})

    def test_08_target_store_without_membership_401(self):
        h = self._headers('GET', TASKS, 'U-OWN', 'S002')
        st, body = self.api.dispatch('GET', TASKS, headers=h)
        self.assertEqual(st, 401)
        self._rec('08_target_no_membership', st, 401, {'code': body['error_code']})

    def test_08b_actor_spoof_query_rejected(self):
        q = {'member_id': 'M-OWN'}
        h = self._headers('GET', TASKS, 'U-STF', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 403)
        self.assertEqual(body['error_code'], 'E-ACTOR')
        self._rec('08b_actor_spoof_query', st, 403, {'code': body['error_code']})

    def test_08b_actor_spoof_body_rejected(self):
        body_bytes = b'{"member_id":"M-OWN"}'
        h = self._headers('GET', TASKS, 'U-STF', 'S001', body=body_bytes)
        st, body = self.api.dispatch('GET', TASKS, headers=h, body=body_bytes)
        self.assertEqual(st, 403)
        self.assertEqual(body['error_code'], 'E-ACTOR')
        self._rec('08b_actor_spoof_body', st, 403, {'code': body['error_code']})

    # 9 serialization -----------------------------------------------------
    def test_09_task_serialization_fields_exact(self):
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-STF', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        item = next(i for i in body['items'] if i['task_id'] == 'T-1')
        self.assertEqual(tuple(item.keys()), TASK_FIELDS)
        self.assertEqual(item['store_id'], 'S001')
        self.assertEqual(item['scenario_type'], 'care')
        for forbidden_field in ('encrypted_phone', 'phone', 'name', 'id_card'):
            self.assertNotIn(forbidden_field, item)
        self._rec('09_task_fields', st, 200, {'fields': list(item.keys())})

    def test_09_appointment_serialization_fields_exact(self):
        q = {'date': self.today}
        h = self._headers('GET', APPTS, 'U-OWN', 'S001', query=q)
        st, body = self.api.dispatch('GET', APPTS, headers=h, query=q)
        item = body['items'][0]
        self.assertEqual(tuple(item.keys()), APPOINTMENT_FIELDS)
        self.assertEqual(item['duration_min'], 60)
        self._rec('09_appointment_fields', st, 200, {'fields': list(item.keys())})

    # 10 adapter (server-side helper) -------------------------------------
    def test_10_adapter_default_off(self):
        os.environ.pop('DM_DAILY_LOOP_ADAPTER_ENABLED', None)
        self.assertFalse(is_enabled())
        ad = MainBackendAdapter(ADAPTER_SECRET, clock=self.clock)
        with self.assertRaises(RuntimeError):
            ad.build_headers('GET', TASKS, b'', 'U-OWN', 'S001', query={'task_date': self.today})
        self._rec('10_adapter_off', 200, 200, {'is_enabled': is_enabled()})

    def test_10_adapter_on_roundtrip(self):
        os.environ['DM_DAILY_LOOP_ADAPTER_ENABLED'] = '1'
        try:
            self.assertTrue(is_enabled())
            ad = MainBackendAdapter(ADAPTER_SECRET, clock=self.clock)
            q = {'task_date': self.today}
            h = ad.build_headers('GET', TASKS, b'', 'U-OWN', 'S001', query=q)
            st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
            self.assertEqual(st, 200)
            self.assertNotIn('X-DM-Caller-Token', h)
        finally:
            os.environ.pop('DM_DAILY_LOOP_ADAPTER_ENABLED', None)
        self._rec('10_adapter_on_roundtrip', st, 200)

    # 11 recovery/vault/holdings absent -----------------------------------
    def test_11_recovery_vault_holdings_routes_absent(self):
        for path in ('/v1/dl/recovery/backup', '/v1/dl/recovery/restore',
                     '/v1/dl/vault/contact', '/v1/dl/internal/holdings',
                     '/v1/dl/internal/balance', '/v1/dl/internal/consumption'):
            h = self._headers('GET', path, 'U-OWN', 'S001')
            st, body = self.api.dispatch('GET', path, headers=h)
            self.assertEqual(st, 404, f'{path} should not exist')
        self._rec('11_forbidden_routes_absent', 404, 404)

    def test_11_recovery_not_imported_by_api(self):
        import app.daily_loop.api.core as core_mod
        api_dir = Path(core_mod.__file__).resolve().parent
        for pyf in api_dir.glob('*.py'):
            import_lines = [l for l in pyf.read_text().splitlines()
                            if l.strip().startswith(('import ', 'from '))]
            joined = '\n'.join(import_lines)
            self.assertNotIn('vault_recovery_service', joined, f'{pyf.name} imports recovery')
            self.assertNotIn('platform_recovery', joined, f'{pyf.name} imports recovery')
        self.assertFalse(hasattr(core_mod, 'VaultRecoveryService'))
        self.assertFalse(hasattr(core_mod, 'PlatformRecoveryProvider'))
        self._rec('11_recovery_not_imported', 200, 200)

    # 12 docker/compose ---------------------------------------------------
    def test_12_runtime_image_excludes_tests_and_recovery(self):
        root = Path(__file__).resolve().parent.parent
        runtime = (root / 'deploy' / 'Dockerfile.runtime').read_text()
        copy_lines = [l for l in runtime.splitlines() if l.strip().upper().startswith('COPY')]
        self.assertTrue(copy_lines)
        for cl in copy_lines:
            for banned in ('tests', 'evidence', 'run_truth_gate', 'run_mutation', '.json'):
                self.assertNotIn(banned, cl, f'runtime COPY leaks {banned}: {cl}')
        env_lines = [l for l in runtime.splitlines() if l.strip().upper().startswith('ENV')]
        for el in env_lines:
            for r in ('DM_PLATFORM_RECOVERY_SECRET', 'DM_PLATFORM_RECOVERY_SIGNING_KEY', 'DM_VAULT_MASTER_KEY'):
                self.assertNotIn(r, el)
        self.assertIn('0.0.0.0', runtime)
        self.assertIn('--workers', runtime)
        self.assertIn('"1"', runtime)
        # P0-4: /data created and chowned to the non-root uid BEFORE USER
        self.assertIn('/data', runtime)
        self.assertRegex(runtime, r'chown[^\n]*10001[^\n]*/data')
        self._rec('12_runtime_excludes', 200, 200)

    def test_12_compose_publishes_loopback_only(self):
        root = Path(__file__).resolve().parent.parent
        compose = (root / 'deploy' / 'docker-compose.daily-loop.yml').read_text()
        self.assertIn('127.0.0.1:18090:18090', compose)
        self.assertNotIn('0.0.0.0:18090:18090', compose)
        self._rec('12_compose_loopback', 200, 200)

    # P1-1 structured 503 dependency failure ------------------------------
    def test_13_missing_table_structured_503(self):
        # drop the identity table; the request must fail-closed to 503 E-DEPENDENCY
        c = sqlite3.connect(self.auth_path)
        c.execute("DROP TABLE dl_store_member"); c.commit(); c.close()
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q)
        st, body = self.api.dispatch('GET', TASKS, headers=h, query=q)
        self.assertEqual(st, 503)
        self.assertEqual(body['error_code'], 'E-DEPENDENCY')
        # no internal detail leaked
        blob = json.dumps(body)
        for leak in ('dl_store_member', self.auth_path, 'SELECT', 'sqlite', 'Traceback'):
            self.assertNotIn(leak, blob)
        self._rec('13_missing_table_503', st, 503, {'body': body})

    def test_13_unreadable_db_structured_503(self):
        # point the api at a directory path -> connect/query raises OSError/sqlite
        bad = DailyLoopApi(str(Path(self.auth_path).parent), self.provider, self.s2s)
        q = {'task_date': self.today}
        h = self._headers('GET', TASKS, 'U-OWN', 'S001', query=q)
        st, body = bad.dispatch('GET', TASKS, headers=h, query=q)
        self.assertIn(st, (401, 503))  # identity DB unreadable -> fail-closed
        if st == 503:
            self.assertEqual(body['error_code'], 'E-DEPENDENCY')
        self._rec('13_unreadable_db', st, st, {'code': body.get('error_code')})


if __name__ == '__main__':
    unittest.main()
