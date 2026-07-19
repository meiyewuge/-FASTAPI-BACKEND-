#!/usr/bin/env python3
"""Optional real-server integration test for the FastAPI runtime wrapper.

Skipped automatically when fastapi/starlette TestClient is unavailable, so the
frozen stdlib gate suites never gain a hard dependency. When present, it drives
the actual ASGI app end-to-end (routing, status codes, JSON body) to confirm the
thin wrapper faithfully exposes the DailyLoopApi core.
"""
import unittest, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault('DM_VAULT_MASTER_KEY', 'test_master_key_at_least_16_chars_long')
os.environ.setdefault('DM_CALLER_SIGNING_KEY', 'test_signing_key_at_least_16_chars')
os.environ.setdefault('DM_SERVICE_PRINCIPAL_SECRET', 'test_service_secret')
os.environ.setdefault('DM_ADAPTER_SHARED_SECRET', 'test_adapter_shared_secret_16c')

try:
    from fastapi.testclient import TestClient  # noqa
    from starlette.testclient import TestClient as _sc  # noqa
    _HAVE_FASTAPI = True
except Exception:
    _HAVE_FASTAPI = False

import uuid
from app.daily_loop.services.repository import AuthRepository
from app.daily_loop.models import StoreMember, DailyCustomerTask, CustomerProfile
from app.daily_loop.api.s2s import derive_s2s_key, sign_request, S2S_VERSION

ADAPTER_SECRET = 'test_adapter_shared_secret_16c'


@unittest.skipUnless(_HAVE_FASTAPI, 'fastapi TestClient not installed (runtime-only dep)')
class C1BFastApiIntegration(unittest.TestCase):

    def setUp(self):
        import time
        fd, self.auth_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
        repo = AuthRepository(self.auth_path); repo.init_schema()
        repo.insert_member(StoreMember('M-OWN', 'S001', 'U-OWN', 'owner', 'own', 'active'))
        repo.insert_customer(CustomerProfile('C-1', 'S001', 'name'))
        repo.insert_task(DailyCustomerTask('T-1', 'S001', 'C-1', '2026-07-17', 'M-OWN', 'assigned', 5, 'care', 'B-1'))
        repo.close()
        os.environ['DM_DAILY_LOOP_AUTH_DB'] = self.auth_path
        from service.daily_loop_server import create_app
        self.client = TestClient(create_app())
        self.key = derive_s2s_key(ADAPTER_SECRET)
        self.now = time.time

    def tearDown(self):
        try: os.unlink(self.auth_path)
        except OSError: pass

    def _headers(self, method, path, uid='U-OWN', store='S001', body=b'', query=None):
        ts = repr(self.now())
        nonce = uuid.uuid4().hex
        sig = sign_request(self.key, method, path, body, ts, nonce, query or {}, uid, store)
        return {'X-DM-S2S-Version': S2S_VERSION, 'X-DM-S2S-Timestamp': ts,
                'X-DM-S2S-Nonce': nonce, 'X-DM-S2S-Signature': sig,
                'X-DM-Auth-User-Id': uid, 'X-DM-Target-Store-Id': store}

    def test_healthz(self):
        r = self.client.get('/v1/dl/healthz')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'status': 'ok'})

    def test_readyz(self):
        r = self.client.get('/v1/dl/readyz')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ready'])

    def test_tasks_authenticated(self):
        path = '/v1/dl/internal/tasks'
        q = {'task_date': '2026-07-17'}
        r = self.client.get(path + '?task_date=2026-07-17', headers=self._headers('GET', path, query=q))
        self.assertEqual(r.status_code, 200)
        ids = [i['task_id'] for i in r.json()['items']]
        self.assertEqual(ids, ['T-1'])

    def test_tasks_identity_swap_after_sign_401(self):
        # real ASGI end-to-end: sign U-OWN/S001, then swap headers -> 401 (v2)
        path = '/v1/dl/internal/tasks'
        q = {'task_date': '2026-07-17'}
        h = self._headers('GET', path, 'U-OWN', 'S001', query=q)
        h['X-DM-Target-Store-Id'] = 'S002'
        r = self.client.get(path + '?task_date=2026-07-17', headers=h)
        self.assertEqual(r.status_code, 401)

    def test_tasks_s2s_missing_401(self):
        r = self.client.get('/v1/dl/internal/tasks',
                            headers={'X-DM-Auth-User-Id': 'U-OWN', 'X-DM-Target-Store-Id': 'S001'})
        self.assertEqual(r.status_code, 401)

    def test_unknown_route_404(self):
        path = '/v1/dl/internal/holdings'
        r = self.client.get(path, headers=self._headers('GET', path))
        self.assertEqual(r.status_code, 404)


if __name__ == '__main__':
    unittest.main()
