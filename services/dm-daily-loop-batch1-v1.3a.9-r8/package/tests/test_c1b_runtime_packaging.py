#!/usr/bin/env python3
"""R1b runtime-packaging static gate.

Verifies the runtime image will actually be able to import the vendored
dm_customer_holdings package, WITHOUT dragging in vendor/ tests or using a broad
PYTHONPATH hack. These are structural assertions on real Dockerfile directives
and the on-disk file set (not comment matching), plus a real import smoke run.
"""
import unittest, os, sys, subprocess, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_RUNTIME_FILES = ('__init__.py', 'api.py', 'balance.py', 'contract.py', 'store.py')


class RuntimePackagingTests(unittest.TestCase):

    def setUp(self):
        self.runtime = (ROOT / 'deploy' / 'Dockerfile.runtime').read_text()
        # directive lines only (drop full-line comments), so prose that mentions a
        # forbidden pattern to explain its absence never trips a structural check
        self.directives = '\n'.join(l for l in self.runtime.splitlines()
                                    if l.strip() and not l.lstrip().startswith('#'))
        self.copy_lines = [l for l in self.directives.splitlines()
                           if l.strip().upper().startswith('COPY')]

    def test_dockerfile_copies_holdings_runtime_py(self):
        # a COPY brings the vendored runtime .py files into an importable location
        self.assertTrue(any('vendor/dm_customer_holdings/' in l and '.py' in l
                            for l in self.copy_lines),
                        'Dockerfile.runtime must COPY vendor/dm_customer_holdings/*.py')

    def test_dockerfile_does_not_copy_whole_vendor_or_tests(self):
        for l in self.copy_lines:
            norm = l.split('#', 1)[0]
            # forbid `COPY vendor/ ...` (whole tree) and any vendor tests copy
            self.assertNotRegex(norm, r'COPY\s+vendor/\s', 'must not COPY the whole vendor/ tree')
            self.assertNotRegex(norm, r'COPY\s+vendor/\s+', 'must not COPY the whole vendor/ tree')
            self.assertNotIn('tests', norm, f'runtime COPY must not include tests: {l}')

    def test_dockerfile_no_broad_pythonpath_hack(self):
        # no `PYTHONPATH=/app/vendor` style broad path injection (directives only)
        hit = re.search(r'PYTHONPATH\s*=\s*[^\n]*vendor', self.directives)
        self.assertFalse(hit, 'must not use a broad vendor PYTHONPATH')

    def test_product_tree_contains_five_runtime_files(self):
        base = ROOT / 'vendor' / 'dm_customer_holdings'
        for f in REQUIRED_RUNTIME_FILES:
            self.assertTrue((base / f).exists(), f'missing runtime file {f}')

    def test_runtime_import_smoke_script_present_and_passes(self):
        smoke = ROOT / 'tools' / 'runtime_import_smoke.py'
        self.assertTrue(smoke.exists(), 'runtime_import_smoke.py must exist')
        # run it for real from the product root (simulates in-image import layout:
        # top-level dm_customer_holdings is reachable via vendor on sys.path here;
        # in the image it is copied to /app/dm_customer_holdings)
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'vendor') + os.pathsep + str(ROOT))
        r = subprocess.run([sys.executable, str(smoke)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, f'smoke failed: {r.stdout}{r.stderr}')
        self.assertIn('RUNTIME_IMPORT_SMOKE_OK', r.stdout)


if __name__ == '__main__':
    unittest.main()
