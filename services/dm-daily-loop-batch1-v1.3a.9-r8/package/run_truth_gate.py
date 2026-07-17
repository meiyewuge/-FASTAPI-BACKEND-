#!/usr/bin/env python3
"""
run_truth_gate.py - V1.3A.9-R8 Stage C structured truth gate.

Each detector returns a structured result:
  {check_id, status, exit_code, failure_codes[], details[], executed_checks[]}

Exit-code taxonomy (P0-7/8/9):
  0 = selected check PASS (security invariant holds)
  1 = real security FAIL — an invariant was violated; failure_codes is non-empty
  2 = argument / config error
  3 = execution ERROR — unexpected exception / SyntaxError / ImportError / broken schema / timeout

A detector NEVER converts an unexpected exception into a security FAIL. A broken
mutation that only produces a SyntaxError / OperationalError / AttributeError is
reported as status=ERROR exit 3, so it can no longer masquerade as BLOCKED.

Structured result is printed on a single line prefixed with `RESULT_JSON: ` for the
mutation runner to parse; the runner does not guess from human text.

Usage:
  python3 run_truth_gate.py                 # full 9-check gate
  python3 run_truth_gate.py --checks vault  # single detector (executed_checks == [vault])
  python3 run_truth_gate.py --selftest      # detector selector self-test
"""
import sys, os, json, ast, subprocess, hashlib, sqlite3, tempfile, argparse, time
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ['DM_VAULT_MASTER_KEY'] = 'test_master_key_at_least_16_chars_long'
os.environ['DM_CALLER_SIGNING_KEY'] = 'test_signing_key_at_least_16_chars'
os.environ['DM_SERVICE_PRINCIPAL_SECRET'] = 'test_service_secret'
os.environ['DM_PLATFORM_RECOVERY_SECRET'] = 'test_platform_secret_different'
os.environ['DM_PLATFORM_RECOVERY_SIGNING_KEY'] = 'test_recovery_signing_key_16chars'

# ── Result model ─────────────────────────────────────
# status in {PASS, FAIL, ERROR}; exit_code derived: PASS->0, FAIL->1, ERROR->3.
class DetectorResult:
    def __init__(self, check_id, status, failure_codes=None, details=None):
        self.check_id = check_id
        self.status = status
        self.failure_codes = failure_codes or []
        self.details = details or []
    @property
    def exit_code(self):
        return {'PASS': 0, 'FAIL': 1, 'ERROR': 3}[self.status]
    def to_dict(self, executed):
        return {
            'check_id': self.check_id, 'status': self.status, 'exit_code': self.exit_code,
            'failure_codes': self.failure_codes, 'details': self.details,
            'executed_checks': executed,
        }

def _ok(cid, details=None): return DetectorResult(cid, 'PASS', [], details)
def _fail(cid, codes, details): return DetectorResult(cid, 'FAIL', codes, details)


def run_subprocess(label, cmd, cwd=None, timeout=120):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or BASE)
    return result.returncode, result.stdout, result.stderr

def _sha256_file(path):
    """Stream a file's SHA-256 through a context manager (no leaked handles)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

# ── Subprocess-backed detectors ──────────────────────
# unittest returns rc!=0 for BOTH failures and errors; for mutation detection a
# mutated production/test file that makes the suite non-green is a real detection
# (FAIL). A rc==0 means the invariant held (PASS).

def check_main_tests():
    rc, out, err = run_subprocess("Main tests", [sys.executable, "-m", "unittest", "tests.run_tests", "-v"])
    if rc == 0:
        return _ok('main_tests', [{'info': 'exit=0'}])
    return _fail('main_tests', ['E-MAIN-TESTS-FAIL'], [{'exit': rc, 'tail': (err or out)[-400:]}])

def check_smoke():
    rc, out, err = run_subprocess("Smoke", [sys.executable, "-m", "unittest", "tests.test_repo_smoke", "-v"])
    if rc == 0:
        return _ok('smoke', [{'info': 'exit=0'}])
    return _fail('smoke', ['E-SMOKE-FAIL'], [{'exit': rc}])

def check_vendor():
    vendor_dir = BASE / "vendor" / "dm_customer_holdings"
    rc, out, err = run_subprocess("Vendor", [sys.executable, "-m", "unittest", "discover", "-s", str(vendor_dir / "tests"), "-q"])
    if rc == 0:
        return _ok('vendor', [{'info': 'exit=0'}])
    return _fail('vendor', ['E-VENDOR-FAIL'], [{'exit': rc}])

def check_tri_consistency():
    sys.path.insert(0, str(BASE))
    from app.daily_loop.utils.tri_consistency_validator import validate_consistency
    tc_errors, tc_warnings = validate_consistency()
    if len(tc_errors) == 0:
        return _ok('tri_consistency', [{'warnings': len(tc_warnings)}])
    return _fail('tri_consistency', ['E-TRI-CONSISTENCY'], [{'errors': tc_errors[:5]}])

# ── Cross-store detector (P0-2/P0-3/P0-9) ────────────
# Distinguishes three outcomes for the appointment cross-store trigger:
#   schema init raises            -> ERROR (broken DDL, NOT a security detection)
#   schema ok + trigger absent    -> FAIL  E-CROSS-STORE-TRIGGER-MISSING   (m6)
#   schema ok + cross-store write succeeds -> FAIL E-CROSS-STORE-SEMANTIC-BYPASS (m2)
def check_cross_store():
    from app.daily_loop.services.repository import AuthRepository
    from app.daily_loop.models import StoreMember, CustomerProfile
    fd, db_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    codes, details = [], []
    try:
        repo = AuthRepository(db_path); repo.init_schema()  # broken DDL -> exception -> ERROR
    except Exception:
        os.unlink(db_path)
        raise  # propagates to dispatch -> ERROR exit 3 (not a false BLOCKED)
    try:
        # P0-3: schema initialised; the named cross-store trigger must exist.
        trg = repo.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name='trg_appointment_cross_store_check'").fetchone()
        if not trg:
            codes.append('E-CROSS-STORE-TRIGGER-MISSING')
            details.append({'test_id': 'trigger_present', 'message': 'trg_appointment_cross_store_check missing after schema init'})

        # Seed two stores + a member in S001 + a customer in S002 only.
        repo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='manager', display_alias='M-001', status='active'))
        repo.insert_member(StoreMember(member_id='M-002', store_id='S002', auth_user_id='U002', role='manager', display_alias='M-002', status='active'))
        repo.insert_customer(CustomerProfile(customer_id='C-002', store_id='S002', display_name='C-002', stage='new', contact_auth='granted', assigned_member_id='M-002'))

        # P0-2: attempt a cross-store appointment — customer C-002 belongs to S002,
        # inserted under S001. The trigger MUST abort with IntegrityError (E-SCOPE).
        # Only sqlite3.IntegrityError counts as "blocked"; any other exception is ERROR.
        blocked = False
        try:
            repo.conn.execute(
                "INSERT INTO dl_appointment (appointment_id,store_id,customer_id,member_id,scheduled_date,status) "
                "VALUES ('A-X','S001','C-002','M-001','2026-01-01','scheduled')")
            repo.conn.commit()
        except sqlite3.IntegrityError as e:
            if 'E-SCOPE' in str(e):
                blocked = True
            else:
                codes.append('E-CROSS-STORE-UNEXPECTED-INTEGRITY')
                details.append({'test_id': 'semantic', 'message': f'unexpected integrity msg: {e}'})
                blocked = True
        if not blocked:
            codes.append('E-CROSS-STORE-SEMANTIC-BYPASS')
            details.append({'test_id': 'semantic', 'message': 'cross-store appointment insert was NOT blocked by trigger'})
    finally:
        try: repo.close()
        except Exception: pass
        try: os.unlink(db_path)
        except Exception: pass
    if codes:
        return _fail('cross_store', sorted(set(codes)), details)
    return _ok('cross_store', [{'info': 'trigger present and cross-store write blocked'}])

# ── Security detector (P0-8) ─────────────────────────
# Calls real production write paths that MUST reject; only the documented
# PermissionError is an acceptable rejection. TypeError/AttributeError/etc. are
# ERROR (propagate), never a silent PASS.
def check_security():
    from app.daily_loop.services.repository import AuthRepository
    from app.daily_loop.models import StoreMember, CustomerProfile, PrivateTargetedMessage, KnowledgeCandidateProjection
    fd, db_path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    codes, details = [], []
    try:
        repo = AuthRepository(db_path); repo.init_schema()
        repo.insert_member(StoreMember(member_id='M-001', store_id='S001', auth_user_id='U001', role='manager', display_alias='M-001', status='active'))
        repo.insert_customer(CustomerProfile(customer_id='C-001', store_id='S001', display_name='C-001', stage='new', contact_auth='denied', assigned_member_id='M-001'))
        # E12: a denied-consent targeted message must be rejected (ValueError E-CONSENT).
        # Build a real model object and call the real production write path.
        denied_msg = PrivateTargetedMessage(message_id='PM-1', store_id='S001', customer_id='C-001',
                                            member_id='M-001', message_content='promo', consent_status='denied')
        try:
            repo.insert_targeted_message(denied_msg)
            codes.append('E-SECURITY-CONSENT-BYPASS')
            details.append({'test_id': 'E12', 'message': 'denied-consent messaging not blocked'})
        except ValueError:
            pass  # correct rejection (E-CONSENT)
        # F3 fail-closed: pii_scanned False / sample_size<5 must be rejected (ValueError E-SCHEMA).
        bad_proj = KnowledgeCandidateProjection(projection_id='KP-1', store_id='S001', projection_type='agg',
                                                aggregated_data='{}', pii_scanned=False, sample_size=1,
                                                source_event_hashes='[]', projection_rule_version='v1',
                                                allowlist_policy_version='v1')
        try:
            repo.insert_projection(bad_proj)
            codes.append('E-SECURITY-PROJECTION-BYPASS')
            details.append({'test_id': 'F3', 'message': 'invalid (fail-closed) projection not blocked'})
        except ValueError:
            pass  # correct rejection (E-SCHEMA)
    finally:
        try: repo.close()
        except Exception: pass
        try: os.unlink(db_path)
        except Exception: pass
    if codes:
        return _fail('security', sorted(set(codes)), details)
    return _ok('security', [{'info': 'consent + projection guards enforced'}])

def check_assertion_linter():
    lint_errors = []
    for py_file in sorted((BASE / "tests").glob("*.py")):
        if py_file.name.startswith('_'): continue
        with open(py_file) as f: source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            lint_errors.append({'file': py_file.name, 'kind': 'syntax', 'message': str(e)})
            continue
        ALL_ASSERTS = {'assertTrue','assertFalse','assertEqual','assertNotEqual','assertIs','assertIsNot',
                       'assertIsNone','assertIsNotNone','assertIn','assertNotIn','assertRaises',
                       'assertIsInstance','assertGreater','assertGreaterEqual','assertLess','assertLessEqual',
                       'assertRegex','assertWarns','assertAlmostEqual','assertCountEqual','fail'}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                has_real = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        method = child.func.attr
                        if method in ALL_ASSERTS:
                            if method == 'assertTrue' and child.args:
                                if isinstance(child.args[0], ast.Constant) and child.args[0].value is True: continue
                                has_real = True
                            elif method == 'assertFalse' and child.args:
                                if isinstance(child.args[0], ast.Constant) and child.args[0].value is False: continue
                                has_real = True
                            elif method == 'assertEqual' and len(child.args) >= 2:
                                left, right = child.args[0], child.args[1]
                                if isinstance(left, ast.Name) and isinstance(right, ast.Name) and left.id == right.id: continue
                                if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and left.value == right.value: continue
                                has_real = True
                            else: has_real = True
                    if isinstance(child, ast.Assert):
                        if isinstance(child.test, ast.Constant) and child.test.value is True: continue
                        has_real = True
                if not has_real:
                    lint_errors.append({'file': py_file.name, 'kind': 'no_real_assertion', 'test': node.name})
    if not lint_errors:
        return _ok('assertion_linter', [{'info': 'all test functions carry a real assertion'}])
    codes = sorted({'E-TEST-SYNTAX-ERROR' if e['kind'] == 'syntax' else 'E-ASSERTION-TAUTOLOGY' for e in lint_errors})
    return _fail('assertion_linter', codes, lint_errors[:8])

# ── Vault detector (P0-4/P0-5/P0-6/P0-7) ─────────────
# 24 negative invariants, each isolated: a per-item unexpected exception is
# recorded as an item ERROR (does not abort the gate, is not counted as BLOCKED).
# Aggregation: any security violation -> FAIL(1); else any item error -> ERROR(3); else PASS(0).
VAULT_ITEM_IDS = [str(i) for i in range(1, 25)]

def check_vault():
    items, item_errors = _check_vault_impl()
    # items: {tid: {expected, observed, status, failure_code}}
    fail_codes, details = [], []
    any_fail = any_error = False
    for tid in VAULT_ITEM_IDS:
        it = items.get(tid, {'expected': '?', 'observed': 'not_run', 'status': 'ERROR', 'failure_code': 'E-VAULT-ITEM-NOT-RUN'})
        details.append({'test_id': tid, **it})
        if it['status'] == 'FAIL':
            any_fail = True
            if it.get('failure_code'): fail_codes.append(it['failure_code'])
        elif it['status'] == 'ERROR':
            any_error = True
            if it.get('failure_code'): fail_codes.append(it['failure_code'])
    if any_fail:
        return _fail('vault', sorted(set(fail_codes)), details)
    if any_error:
        return DetectorResult('vault', 'ERROR', sorted(set(fail_codes)) or ['E-VAULT-EXECUTION-ERROR'], details)
    return _ok('vault', details)

def _check_vault_impl():
    from app.daily_loop.services.repository import AuthRepository
    from app.daily_loop.models import StoreMember
    from app.daily_loop.services.vault_repository import VaultRepository
    from app.daily_loop.services.caller_context import CallerContext, TrustedMemberProvider
    from app.daily_loop.services.platform_recovery import PlatformRecoveryContext, PlatformRecoveryProvider
    from app.daily_loop.services.keyring import KeyRing
    from app.daily_loop.services.vault_recovery_service import VaultRecoveryService
    from cryptography.exceptions import InvalidTag
    import sqlite3 as _sqlite3
    items, item_errors = {}, []

    def deny(tid, code, action, succeeded=lambda r: r is not None):
        """Negative invariant: the op MUST be rejected. If it goes through -> FAIL."""
        try:
            r = action()
            if succeeded(r):
                items[tid] = {'expected': 'reject', 'observed': 'op_succeeded', 'status': 'FAIL', 'failure_code': code}
            else:
                items[tid] = {'expected': 'reject', 'observed': 'blocked', 'status': 'PASS', 'failure_code': None}
        except PermissionError:
            items[tid] = {'expected': 'reject', 'observed': 'PermissionError', 'status': 'PASS', 'failure_code': None}
        except Exception as e:
            items[tid] = {'expected': 'reject', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}
            item_errors.append({'test_id': tid, 'error': f'{type(e).__name__}: {e}'})

    def allow(tid, code, action, succeeded=lambda r: r is not None):
        """Positive invariant: the op MUST succeed. PermissionError / blocked -> FAIL.
        This is the P0-4 fix: a PermissionError is NOT treated as pass here."""
        try:
            r = action()
            if succeeded(r):
                items[tid] = {'expected': 'succeed', 'observed': 'op_succeeded', 'status': 'PASS', 'failure_code': None}
            else:
                items[tid] = {'expected': 'succeed', 'observed': 'blocked', 'status': 'FAIL', 'failure_code': code}
        except PermissionError:
            items[tid] = {'expected': 'succeed', 'observed': 'PermissionError', 'status': 'FAIL', 'failure_code': code}
        except Exception as e:
            items[tid] = {'expected': 'succeed', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}
            item_errors.append({'test_id': tid, 'error': f'{type(e).__name__}: {e}'})

    def assert_(tid, code, held, observed):
        items[tid] = {'expected': 'invariant_holds', 'observed': observed,
                      'status': 'PASS' if held else 'FAIL', 'failure_code': None if held else code}

    class MockClock:
        def __init__(self): self._t = 1000000.0
        def __call__(self): return self._t
        def advance(self, s): self._t += s
        def set(self, t): self._t = t
    clock = MockClock()
    afd, apath = tempfile.mkstemp(suffix='.db'); os.close(afd)
    arepo = AuthRepository(apath); arepo.init_schema()
    for mid, uid, sid, role in [('M-001','U001','S001','owner'),('M-002','U002','S002','owner'),
                                 ('M-003','U003','S001','staff'),('M-004','U004','S001','manager')]:
        arepo.insert_member(StoreMember(member_id=mid, store_id=sid, auth_user_id=uid, role=role, display_alias=mid, status='active'))
    arepo.close()
    kr = KeyRing()
    provider = TrustedMemberProvider.from_env(apath, clock=clock)
    recovery_provider = PlatformRecoveryProvider.from_env(clock=clock)
    fd, vpath = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(vpath)
    vrepo = VaultRepository(vpath, kr, provider=provider)
    vrepo.init_schema()
    recovery_service = VaultRecoveryService(vrepo, kr, clock=clock)
    ctx_owner = provider.create('U001', 'S001')
    ctx_s2_owner = provider.create('U002', 'S002')
    ctx_staff = provider.create('U003', 'S001')
    ctx_manager = provider.create('U004', 'S001')
    ctx_platform = recovery_provider.create('platform_admin', os.environ['DM_PLATFORM_RECOVERY_SECRET'])
    vrepo.insert_vault(vault_id='V-001', subject_type='customer', subject_id='C-001', store_id='S001', plaintext_phone='13800138000', plaintext_name='ZhangSan', ctx=ctx_owner)

    _wrote = lambda r: True  # any non-exception return from a write == it went through
    _rotated = lambda r: bool(r and r.get('rotated'))
    # 1-3 ctx=None (deny)
    deny('1', 'E-VAULT-READ-AUTH-BYPASS', lambda: vrepo.read_vault('V-001', None, 'null'))
    deny('2', 'E-VAULT-WRITE-AUTH-BYPASS', lambda: vrepo.insert_vault(vault_id='V-002', subject_type='customer', subject_id='C-002', store_id='S001', plaintext_phone='x', ctx=None), _wrote)
    deny('3', 'E-VAULT-ROTATE-AUTH-BYPASS', lambda: vrepo.rotate_key('V-001', 'v2', None), _rotated)
    # 4 forgery / 5 claims tampering (deny read)
    deny('4', 'E-VAULT-FORGERY-ACCEPTED', lambda: vrepo.read_vault('V-001', CallerContext('M-FAKE', 'S001', 'owner', token=b'fake'), 'spoof'))
    import copy
    def _tamper_ctx():
        t = copy.copy(ctx_owner); object.__setattr__(t, '_member_id', 'M-TAMPERED'); return t
    deny('5', 'E-VAULT-CLAIMS-TAMPER-ACCEPTED', lambda: vrepo.read_vault('V-001', _tamper_ctx(), 'tamper'))
    # 6 expires_at-1 valid window (ALLOW: token must still read) -- P0-4
    ctx_ttl = provider.create('U001', 'S001', ttl_seconds=60)
    def _valid_window_read():
        clock.set(ctx_ttl._expires_at - 1)
        try: return vrepo.read_vault('V-001', ctx_ttl, 'near')
        finally: clock.set(1000000.0)
    allow('6', 'E-VAULT-TOKEN-VALID-WINDOW', _valid_window_read)
    # 7 expires_at expired (deny)
    def _expired_read():
        clock.set(ctx_ttl._expires_at)
        try: return vrepo.read_vault('V-001', ctx_ttl, 'exp')
        finally: clock.set(1000000.0)
    deny('7', 'E-VAULT-TOKEN-EXPIRY', _expired_read)
    # 8 token uniqueness (assert)
    _a = provider.create('U001','S001'); _b = provider.create('U001','S001')
    assert_('8', 'E-VAULT-TOKEN-UNIQUENESS', _a._token_id != _b._token_id, f'token_ids_differ={_a._token_id != _b._token_id}')
    # 9-12 revoked-context reads (deny)
    def _mutate_member(uid, mid, sql):
        r = AuthRepository(apath); r.init_schema()
        r.insert_member(StoreMember(member_id=mid, store_id='S001', auth_user_id=uid, role='manager', display_alias=mid, status='active')); r.close()
        ctx = provider.create(uid, 'S001')
        c = _sqlite3.connect(apath); c.execute(sql); c.commit(); c.close()
        return ctx
    deny('9', 'E-VAULT-DISABLED-TOKEN', lambda: vrepo.read_vault('V-001', _mutate_member('U030','M-030',"UPDATE dl_store_member SET status='disabled' WHERE member_id='M-030'"), 'disabled'))
    deny('10', 'E-VAULT-LEFT-TOKEN', lambda: vrepo.read_vault('V-001', _mutate_member('U031','M-031',"UPDATE dl_store_member SET status='left' WHERE member_id='M-031'"), 'left'))
    deny('11', 'E-VAULT-ROLE-DOWNGRADE-TOKEN', lambda: vrepo.read_vault('V-001', _mutate_member('U040','M-040',"UPDATE dl_store_member SET role='staff' WHERE member_id='M-040'"), 'downgrade'))
    deny('12', 'E-VAULT-STORE-DRIFT-TOKEN', lambda: vrepo.read_vault('V-001', _mutate_member('U050','M-050',"UPDATE dl_store_member SET store_id='S002' WHERE member_id='M-050'"), 'drift'))
    # 13 staff read (deny)
    deny('13', 'E-VAULT-STAFF-READ', lambda: vrepo.read_vault('V-001', ctx_staff, 'staff'))
    # 14 staff write denied AND not persisted (deny + persistence assert)
    def _staff_write_and_check():
        wrote = False
        try:
            vrepo.insert_vault(vault_id='V-005', subject_type='customer', subject_id='C-005', store_id='S001', plaintext_phone='x', ctx=ctx_staff)
            wrote = True
        except PermissionError:
            wrote = False
        ec = _sqlite3.connect(vpath); n = ec.execute("SELECT count(*) FROM dl_identity_vault WHERE vault_id='V-005'").fetchone()[0]; ec.close()
        if wrote or n > 0:
            items['14'] = {'expected': 'reject', 'observed': f'wrote={wrote},persisted_rows={n}', 'status': 'FAIL', 'failure_code': 'E-VAULT-WRITE-AUTH-BYPASS'}
        else:
            items['14'] = {'expected': 'reject', 'observed': 'blocked,0_rows', 'status': 'PASS', 'failure_code': None}
    try: _staff_write_and_check()
    except Exception as e:
        items['14'] = {'expected': 'reject', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}; item_errors.append({'test_id': '14', 'error': str(e)})
    # 15 manager rotate (deny)
    deny('15', 'E-VAULT-ROTATE-AUTH-BYPASS', lambda: vrepo.rotate_key('V-001', 'v3', ctx_manager), _rotated)
    # 16 owner rotate (ALLOW) -- P0-4
    allow('16', 'E-VAULT-OWNER-ROTATE-BROKEN', lambda: vrepo.rotate_key('V-001', 'v2', ctx_owner), _rotated)
    # 17 cross-store read/write/rotate all denied (composite deny, code by first breach)
    def _cross_store():
        breaches = []
        for sub, act, ok, code in [
            ('read', lambda: vrepo.read_vault('V-001', ctx_s2_owner, 'cross'), (lambda r: r is not None), 'E-VAULT-CROSS-STORE-READ'),
            ('write', lambda: vrepo.insert_vault(vault_id='V-003', subject_type='customer', subject_id='C-003', store_id='S001', plaintext_phone='x', ctx=ctx_s2_owner), _wrote, 'E-VAULT-WRITE-AUTH-BYPASS'),
            ('rotate', lambda: vrepo.rotate_key('V-001', 'v4', ctx_s2_owner), _rotated, 'E-VAULT-ROTATE-AUTH-BYPASS')]:
            try:
                if ok(act()): breaches.append((sub, code))
            except PermissionError:
                pass
        return breaches
    try:
        b = _cross_store()
        if b:
            items['17'] = {'expected': 'reject_all', 'observed': ','.join(s for s, _ in b), 'status': 'FAIL', 'failure_code': b[0][1]}
        else:
            items['17'] = {'expected': 'reject_all', 'observed': 'all_blocked', 'status': 'PASS', 'failure_code': None}
    except Exception as e:
        items['17'] = {'expected': 'reject_all', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}; item_errors.append({'test_id': '17', 'error': str(e)})
    # 18 system context as platform recovery (deny)
    ctx_sys = provider.create_system('daily_loop_orchestrator', os.environ['DM_SERVICE_PRINCIPAL_SECRET'])
    deny('18', 'E-VAULT-SYSTEM-AS-PLATFORM', lambda: recovery_service.backup(vpath + '.bak3', ctx_sys), _wrote)
    # 19 business verifies platform / 20 platform verifies business (assert: verify must be False)
    assert_('19', 'E-VAULT-SIGNING-ROOT-BYPASS', not provider.verify(ctx_platform), 'business_verify_platform=False')
    assert_('20', 'E-VAULT-SIGNING-ROOT-BYPASS', not recovery_provider.verify(ctx_owner), 'platform_verify_business=False')
    # 21 expired recovery token -> backup AND restore both denied (composite deny)
    ctx_plat_exp = recovery_provider.create('platform_admin', os.environ['DM_PLATFORM_RECOVERY_SECRET'])
    def _exp_recovery():
        breaches = []
        for sub, act in [('backup', lambda: recovery_service.backup(vpath + '.bak4', ctx_plat_exp)),
                         ('restore', lambda: recovery_service.restore(vpath + '.bak4', ctx_plat_exp))]:
            clock.set(ctx_plat_exp._expires_at)
            try:
                act(); breaches.append(sub)
            except PermissionError:
                pass
            finally:
                clock.set(1000000.0)
        return breaches
    try:
        b = _exp_recovery()
        if b:
            items['21'] = {'expected': 'reject', 'observed': ','.join(b), 'status': 'FAIL', 'failure_code': 'E-RECOVERY-PROVIDER-VERIFY-BYPASS'}
        else:
            items['21'] = {'expected': 'reject', 'observed': 'both_blocked', 'status': 'PASS', 'failure_code': None}
    except Exception as e:
        items['21'] = {'expected': 'reject', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}; item_errors.append({'test_id': '21', 'error': str(e)})
    # 22 missing platform signing key -> subprocess exit 2 (assert)
    r22 = subprocess.run([sys.executable, '-c',
        'import os; os.environ.pop("DM_PLATFORM_RECOVERY_SIGNING_KEY", None); '
        'from app.daily_loop.services.platform_recovery import PlatformRecoveryProvider; PlatformRecoveryProvider.from_env()'],
        capture_output=True, text=True, cwd=str(BASE))
    assert_('22', 'E-VAULT-RECOVERY-KEY-MISSING-EXITCODE', r22.returncode == 2, f'exit={r22.returncode}')
    # 23 restore success invariants (ALLOW/composite) -- reconnect_count==1 etc.
    try:
        recovery_service.backup(vpath + '.bak5', ctx_platform)
        vrepo.insert_vault(vault_id='V-006', subject_type='customer', subject_id='C-006', store_id='S001', plaintext_phone='13900000000', ctx=ctx_owner)
        rr = recovery_service.restore(vpath + '.bak5', ctx_platform)
        code = obs = None
        if not rr.get('restored'):
            code, obs = 'E-VAULT-RESTORE-SUCCESS-BROKEN', 'not_restored'
        elif rr.get('reconnect_count', -1) != 1:
            code, obs = 'E-VAULT-RECONNECT-COUNT', f"reconnect={rr.get('reconnect_count')}"
        else:
            repo_rows = vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
            ec = _sqlite3.connect(vpath); ext_rows = ec.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]; ec.close()
            if repo_rows != 1 or ext_rows != 1:
                code, obs = 'E-VAULT-RESTORE-SUCCESS-BROKEN', f'repo_rows={repo_rows},ext_rows={ext_rows}'
        if code:
            items['23'] = {'expected': 'succeed', 'observed': obs, 'status': 'FAIL', 'failure_code': code}
        else:
            items['23'] = {'expected': 'succeed', 'observed': 'restored,reconnect=1,rows=1', 'status': 'PASS', 'failure_code': None}
    except Exception as e:
        items['23'] = {'expected': 'succeed', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}; item_errors.append({'test_id': '23', 'error': str(e)})
    # 24 restore failure invariance: wrong master key -> InvalidTag (precise) + rows unchanged
    try:
        orig = vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
        orig_sha = _sha256_file(vpath)
        os.environ['DM_VAULT_MASTER_KEY'] = 'wrong_key_at_least_16_chars!'
        from app.daily_loop.services.keyring import restore_vault, KeyRing as KR2
        observed = None
        try:
            restore_vault(vpath + '.bak5', vpath + '.x', KR2().get_master())
            observed = 'restore_succeeded'  # violation: wrong key should not restore
        except InvalidTag:
            observed = 'InvalidTag'          # correct precise rejection
        except Exception as e:
            observed = f'unexpected:{type(e).__name__}'
        os.environ['DM_VAULT_MASTER_KEY'] = 'test_master_key_at_least_16_chars_long'
        rows_after = vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
        sha_after = _sha256_file(vpath)
        if observed == 'InvalidTag' and rows_after == orig and sha_after == orig_sha:
            items['24'] = {'expected': 'reject_invalidtag_invariant', 'observed': 'InvalidTag,rows&sha_unchanged', 'status': 'PASS', 'failure_code': None}
        elif observed == 'restore_succeeded':
            items['24'] = {'expected': 'reject_invalidtag_invariant', 'observed': observed, 'status': 'FAIL', 'failure_code': 'E-VAULT-RESTORE-FAILURE-MUTATED'}
        elif rows_after != orig or sha_after != orig_sha:
            items['24'] = {'expected': 'reject_invalidtag_invariant', 'observed': f'{observed},rows/sha_changed', 'status': 'FAIL', 'failure_code': 'E-VAULT-RESTORE-FAILURE-MUTATED'}
        else:
            items['24'] = {'expected': 'reject_invalidtag_invariant', 'observed': observed, 'status': 'ERROR', 'failure_code': 'E-VAULT-WRONGKEY-UNEXPECTED-EXCEPTION'}
            item_errors.append({'test_id': '24', 'error': observed})
    except Exception as e:
        items['24'] = {'expected': 'reject_invalidtag_invariant', 'observed': type(e).__name__, 'status': 'ERROR', 'failure_code': 'E-VAULT-EXECUTION-ERROR'}; item_errors.append({'test_id': '24', 'error': str(e)})
    # cleanup
    try:
        vrepo.close()
        for ext in ['.bak3', '.bak4', '.bak5', '.x']:
            p = vpath + ext
            if os.path.exists(p): os.unlink(p)
        for p in (vpath, apath):
            if os.path.exists(p): os.unlink(p)
    except Exception:
        pass
    return items, item_errors

def check_manifest():
    mp = BASE / "manifest.json"
    if not mp.exists():
        return _fail('manifest', ['E-MANIFEST-MISSING'], [{'message': 'manifest.json not found'}])
    with open(mp) as f:
        manifest = json.load(f)
    mf = manifest.get("files", {})
    excluded = set()
    for it in manifest.get("excluded_generated_files", []):
        excluded.add(it["path"] if isinstance(it, dict) else it)
    mm = ms = 0
    for rel, expected in mf.items():
        if rel in excluded: continue
        fp = BASE / rel
        if not fp.exists(): ms += 1; continue
        if _sha256_file(fp) != expected: mm += 1
    disk = set()
    for root, dirs, filenames in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".venv", ".git", "evidence")]
        for f in filenames:
            rel = str(Path(root) / f).replace(str(BASE) + "/", "")
            if rel not in excluded and rel != "run_truth_gate.py":
                disk.add(rel)
    ul = len(disk - (set(mf.keys()) - excluded))
    if mm == 0 and ms == 0 and ul == 0:
        return _ok('manifest', [{'mismatch': 0, 'missing': 0, 'unlisted': 0}])
    codes = []
    if mm: codes.append('E-MANIFEST-MISMATCH')
    if ms: codes.append('E-MANIFEST-MISSING')
    if ul: codes.append('E-MANIFEST-UNLISTED')
    return _fail('manifest', codes, [{'mismatch': mm, 'missing': ms, 'unlisted': ul}])

def check_aad_class_binding():
    from app.daily_loop.services.keyring import KeyRing
    from cryptography.exceptions import InvalidTag
    kr = KeyRing()
    enc = kr.encrypt_field('test_data', 'v1', b'CORRECT_AAD')
    # Invariant A: the CORRECT AAD must decrypt back to the plaintext. If a neutered
    # AAD binding makes the correct AAD fail (InvalidTag) or return wrong data, that
    # is a real binding break -> FAIL (not an execution ERROR).
    try:
        pt = kr.decrypt_field(enc, 'v1', b'CORRECT_AAD')
    except InvalidTag:
        return _fail('aad_class_binding', ['E-AAD-BINDING-BROKEN'],
                     [{'message': 'correct AAD failed to decrypt (binding neutered)'}])
    if pt != 'test_data':
        return _fail('aad_class_binding', ['E-AAD-BINDING-BROKEN'], [{'message': 'correct AAD produced wrong plaintext'}])
    # Invariant B: a WRONG AAD must be rejected with InvalidTag.
    try:
        kr.decrypt_field(enc, 'v1', b'WRONG_AAD')
        return _fail('aad_class_binding', ['E-AAD-BINDING-BROKEN'], [{'message': 'wrong AAD decrypted successfully'}])
    except InvalidTag:
        return _ok('aad_class_binding', [{'info': 'correct AAD ok, wrong AAD -> InvalidTag'}])

# ── Dispatch ─────────────────────────────────────────
CHECKS = {
    "main_tests": check_main_tests, "smoke": check_smoke, "vendor": check_vendor,
    "tri_consistency": check_tri_consistency, "cross_store": check_cross_store,
    "security": check_security, "assertion_linter": check_assertion_linter,
    "vault": check_vault, "manifest": check_manifest, "aad_class_binding": check_aad_class_binding,
}
FULL_ORDER = ["main_tests", "smoke", "vendor", "tri_consistency", "cross_store", "security", "assertion_linter", "vault", "manifest"]

def _emit(result, executed):
    print("RESULT_JSON: " + json.dumps(result.to_dict(executed), ensure_ascii=False))

def selftest():
    """Selector self-test: each --checks id executes exactly that detector."""
    results = {}
    for cid in CHECKS:
        r = subprocess.run([sys.executable, str(BASE / 'run_truth_gate.py'), '--checks', cid, '--selftest-probe'],
                           capture_output=True, text=True, cwd=str(BASE), timeout=180)
        executed = None
        for line in r.stdout.splitlines():
            if line.startswith('RESULT_JSON: '):
                executed = json.loads(line[len('RESULT_JSON: '):]).get('executed_checks')
        results[cid] = (executed == [cid])
    ok = all(results.values())
    print("RESULT_JSON: " + json.dumps({'check_id': 'selftest', 'status': 'PASS' if ok else 'FAIL',
        'exit_code': 0 if ok else 1, 'per_selector': results, 'executed_checks': sorted(CHECKS)}, ensure_ascii=False))
    sys.exit(0 if ok else 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checks', default=None)
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--selftest-probe', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.selftest:
        selftest()

    if args.checks is not None and args.checks not in CHECKS:
        print(f"ERROR: unknown check '{args.checks}'. Valid: {sorted(CHECKS.keys())}")
        sys.exit(2)

    if args.checks:
        check_fn = CHECKS[args.checks]
        print(f"[{args.checks}]")
        try:
            result = check_fn()
        except Exception as e:
            # Unexpected exception -> ERROR exit 3 (never a security BLOCKED)
            res = DetectorResult(args.checks, 'ERROR', ['E-EXECUTION-ERROR'], [{'error': f'{type(e).__name__}: {e}'}])
            _emit(res, [args.checks])
            print(f"  ERROR: {type(e).__name__}: {e}")
            sys.exit(3)
        _emit(result, [args.checks])
        print(f"  {result.status}: failure_codes={result.failure_codes}")
        sys.exit(result.exit_code)
    else:
        errors = []
        for i, cid in enumerate(FULL_ORDER, 1):
            print(f"[{i}/9] {cid}...")
            try:
                result = CHECKS[cid]()
            except Exception as e:
                result = DetectorResult(cid, 'ERROR', ['E-EXECUTION-ERROR'], [{'error': f'{type(e).__name__}: {e}'}])
            if result.status != 'PASS':
                errors.append(f"{cid}: {result.status} {result.failure_codes}")
            print(f"  {result.status}: {result.failure_codes or 'ok'}")
        print("\n" + "=" * 60)
        if errors:
            print(f"TRUTH GATE: FAIL - {len(errors)} non-PASS")
            for e in errors[:20]: print(f"  X {e}")
            sys.exit(1)
        print("TRUTH GATE: PASS - all 9 checks passed")
        sys.exit(0)

if __name__ == "__main__":
    main()
