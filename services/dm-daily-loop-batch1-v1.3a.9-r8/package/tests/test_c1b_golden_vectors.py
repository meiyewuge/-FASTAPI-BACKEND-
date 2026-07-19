#!/usr/bin/env python3
"""Golden-vector contract test binding the Daily Loop server verifier and the
main-backend adapter to ONE canonical dm-s2s-v2 signature.

The two implementations live in separate code domains (app/daily_loop vs
backend/app) and share no code. This test recomputes each pinned vector with
BOTH implementations and asserts they equal the frozen expected signature, so an
edit to either canonicalization that changes output fails the suite (anti-drift).
"""
import unittest, os, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault('DM_ADAPTER_SHARED_SECRET', 'test_adapter_shared_secret_16c')

from app.daily_loop.api.s2s import derive_s2s_key as server_derive, sign_request as server_sign
from backend.app.adapters.daily_loop_adapter import _derive_key as backend_derive, canonical_signature as backend_sign

VECTORS_PATH = ROOT / 'tests' / 's2s_golden_vectors.json'


class S2SGoldenVectorContract(unittest.TestCase):

    def setUp(self):
        self.doc = json.loads(VECTORS_PATH.read_text())
        self.ks = server_derive(self.doc['secret'])
        self.kb = backend_derive(self.doc['secret'])

    def test_server_and_backend_match_golden(self):
        self.assertTrue(self.doc['vectors'])
        for v in self.doc['vectors']:
            b = v['body'].encode('utf-8')
            s = server_sign(self.ks, v['method'], v['path'], b, v['timestamp'],
                            v['nonce'], v['query'], v['auth_user_id'], v['target_store_id'])
            k = backend_sign(self.kb, v['method'], v['path'], b, v['timestamp'],
                             v['nonce'], v['query'], v['auth_user_id'], v['target_store_id'])
            self.assertEqual(s, v['expected_sig'], f'server drift on {v}')
            self.assertEqual(k, v['expected_sig'], f'backend drift on {v}')
            self.assertEqual(s, k, 'server/backend canonicalization drift')

    def test_backend_does_not_import_daily_loop(self):
        import backend.app.adapters.daily_loop_adapter as mod
        src = Path(mod.__file__).read_text()
        import_lines = [l for l in src.splitlines() if l.strip().startswith(('import ', 'from '))]
        joined = '\n'.join(import_lines)
        self.assertNotIn('app.daily_loop', joined)
        self.assertNotIn('daily_loop.api', joined)


if __name__ == '__main__':
    unittest.main()
