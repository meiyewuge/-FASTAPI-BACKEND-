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
_VAULT_CODE = {
    '1': 'E-VAULT-READ-AUTH-BYPASS', '2': 'E-VAULT-WRITE-AUTH-BYPASS', '3': 'E-VAULT-ROTATE-AUTH-BYPASS',
    '4': 'E-VAULT-FORGERY-ACCEPTED', '5': 'E-VAULT-CLAIMS-TAMPER-ACCEPTED',
    '6': 'E-VAULT-TOKEN-VALID-WINDOW', '7': 'E-VAULT-TOKEN-EXPIRY', '8': 'E-VAULT-TOKEN-UNIQUENESS',
    '9': 'E-VAULT-DISABLED-TOKEN', '10': 'E-VAULT-LEFT-TOKEN', '11': 'E-VAULT-ROLE-DOWNGRADE-TOKEN',
    '12': 'E-VAULT-STORE-DRIFT-TOKEN', '13': 'E-VAULT-STAFF-READ',
    '14': 'E-VAULT-WRITE-AUTH-BYPASS', '14-persisted': 'E-VAULT-WRITE-AUTH-BYPASS',
    '15': 'E-VAULT-ROTATE-AUTH-BYPASS', '16': 'E-VAULT-OWNER-ROTATE-BROKEN',
    '17-read': 'E-VAULT-CROSS-STORE-READ', '17-write': 'E-VAULT-WRITE-AUTH-BYPASS', '17-rotate': 'E-VAULT-ROTATE-AUTH-BYPASS',
    '18': 'E-VAULT-SYSTEM-AS-PLATFORM', '19': 'E-VAULT-SIGNING-ROOT-BYPASS', '20': 'E-VAULT-SIGNING-ROOT-BYPASS',
    '21-backup': 'E-RECOVERY-PROVIDER-VERIFY-BYPASS', '21-restore': 'E-RECOVERY-PROVIDER-VERIFY-BYPASS',
    '23-restore': 'E-VAULT-RESTORE-SUCCESS-BROKEN', '23-reconnect': 'E-VAULT-RECONNECT-COUNT',
    '23-rows': 'E-VAULT-RESTORE-SUCCESS-BROKEN', '23-ext': 'E-VAULT-RESTORE-SUCCESS-BROKEN',
    '24': 'E-VAULT-RESTORE-FAILURE-MUTATED', '24-rows': 'E-VAULT-RESTORE-FAILURE-MUTATED',
}
def _vault_code(tag):
    if tag in _VAULT_CODE: return _VAULT_CODE[tag]
    base = tag.split('-')[0].split('=')[0]
    return _VAULT_CODE.get(base, 'E-VAULT-INVARIANT-' + base)

def check_vault():
    violations, item_errors = _check_vault_impl()
    if violations:
        codes = sorted({_vault_code(t) for t in violations})
        return _fail('vault', codes, [{'test_id': t, 'code': _vault_code(t)} for t in violations])
    if item_errors:
        # Unexpected exceptions -> ERROR (exit 3), never a security BLOCKED.
        return DetectorResult('vault', 'ERROR', ['E-VAULT-EXECUTION-ERROR'], item_errors[:8])
    return _ok('vault', [{'info': '24/24 vault invariants held'}])

def _check_vault_impl():
    from app.daily_loop.services.repository import AuthRepository
    from app.daily_loop.models import StoreMember
    from app.daily_loop.services.vault_repository import VaultRepository
    from app.daily_loop.services.caller_context import CallerContext, TrustedMemberProvider
    from app.daily_loop.services.platform_recovery import PlatformRecoveryContext, PlatformRecoveryProvider
    from app.daily_loop.services.keyring import KeyRing
    from app.daily_loop.services.vault_recovery_service import VaultRecoveryService
    import sqlite3 as _sqlite3
    violations, item_errors = [], []

    def item(tid, fn):
        """Run one invariant. fn() returns True on VIOLATION, False if secure.
        PermissionError inside fn == secure. Any other exception == item ERROR."""
        try:
            if fn(): violations.append(tid)
        except PermissionError:
            pass
        except Exception as e:
            item_errors.append({'test_id': tid, 'error': f'{type(e).__name__}: {e}'})

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

    def _read(vid, ctx, reason):
        r = vrepo.read_vault(vid, ctx, reason); return r is not None
    # 1-3 ctx=None
    item('1', lambda: _read('V-001', None, 'null'))
    item('2', lambda: (vrepo.insert_vault(vault_id='V-002', subject_type='customer', subject_id='C-002', store_id='S001', plaintext_phone='x', ctx=None) or True))
    item('3', lambda: (vrepo.rotate_key('V-001', 'v2', None) or True))
    # 4 forgery
    item('4', lambda: _read('V-001', CallerContext('M-FAKE', 'S001', 'owner', token=b'fake'), 'spoof'))
    # 5 claims tampering
    import copy
    def _tamper():
        t = copy.copy(ctx_owner); object.__setattr__(t, '_member_id', 'M-TAMPERED')
        return _read('V-001', t, 'tamper')
    item('5', _tamper)
    # 6-7 token expiry (exact boundary via mock clock)
    ctx_ttl = provider.create('U001', 'S001', ttl_seconds=60)
    def _valid_window():
        clock.set(ctx_ttl._expires_at - 1)
        try: r = vrepo.read_vault('V-001', ctx_ttl, 'near'); return r is None  # must be readable
        finally: clock.set(1000000.0)
    item('6', _valid_window)
    def _expired():
        clock.set(ctx_ttl._expires_at)
        try: return _read('V-001', ctx_ttl, 'exp')
        finally: clock.set(1000000.0)
    item('7', _expired)
    # 8 uniqueness
    item('8', lambda: provider.create('U001','S001')._token_id == provider.create('U001','S001')._token_id)
    # 9 disabled / 10 left / 11 role-downgrade / 12 store-drift
    def _mutate_member(uid, mid, sql):
        r = AuthRepository(apath); r.init_schema()
        r.insert_member(StoreMember(member_id=mid, store_id='S001', auth_user_id=uid, role='manager', display_alias=mid, status='active')); r.close()
        ctx = provider.create(uid, 'S001')
        c = _sqlite3.connect(apath); c.execute(sql); c.commit(); c.close()
        return ctx
    item('9', lambda: _read('V-001', _mutate_member('U030','M-030',"UPDATE dl_store_member SET status='disabled' WHERE member_id='M-030'"), 'disabled'))
    item('10', lambda: _read('V-001', _mutate_member('U031','M-031',"UPDATE dl_store_member SET status='left' WHERE member_id='M-031'"), 'left'))
    item('11', lambda: _read('V-001', _mutate_member('U040','M-040',"UPDATE dl_store_member SET role='staff' WHERE member_id='M-040'"), 'downgrade'))
    item('12', lambda: _read('V-001', _mutate_member('U050','M-050',"UPDATE dl_store_member SET store_id='S002' WHERE member_id='M-050'"), 'drift'))
    # 13 staff read
    item('13', lambda: _read('V-001', ctx_staff, 'staff'))
    # 14 staff write (+ persistence check)
    item('14', lambda: (vrepo.insert_vault(vault_id='V-005', subject_type='customer', subject_id='C-005', store_id='S001', plaintext_phone='x', ctx=ctx_staff) or True))
    def _persisted():
        ec = _sqlite3.connect(vpath); n = ec.execute("SELECT count(*) FROM dl_identity_vault WHERE vault_id='V-005'").fetchone()[0]; ec.close(); return n > 0
    item('14-persisted', _persisted)
    # 15 manager rotate
    item('15', lambda: bool(vrepo.rotate_key('V-001', 'v3', ctx_manager).get('rotated')))
    # 16 owner rotate MUST succeed (violation if it does not)
    def _owner_rotate():
        try: return not bool(vrepo.rotate_key('V-001', 'v2', ctx_owner).get('rotated'))
        except PermissionError: return True  # unexpected denial == violation for item 16
    item('16', _owner_rotate)
    # 17 cross-store read/write/rotate
    item('17-read', lambda: _read('V-001', ctx_s2_owner, 'cross'))
    item('17-write', lambda: (vrepo.insert_vault(vault_id='V-003', subject_type='customer', subject_id='C-003', store_id='S001', plaintext_phone='x', ctx=ctx_s2_owner) or True))
    item('17-rotate', lambda: bool(vrepo.rotate_key('V-001', 'v4', ctx_s2_owner).get('rotated')))
    # 18 system context as platform recovery
    ctx_sys = provider.create_system('daily_loop_orchestrator', os.environ['DM_SERVICE_PRINCIPAL_SECRET'])
    item('18', lambda: (recovery_service.backup(vpath + '.bak3', ctx_sys) or True))
    # 19 business verifies platform / 20 platform verifies business (bidirectional root isolation)
    item('19', lambda: bool(provider.verify(ctx_platform)))
    item('20', lambda: bool(recovery_provider.verify(ctx_owner)))
    # 21 recovery token expired -> backup & restore rejected
    ctx_plat_exp = recovery_provider.create('platform_admin', os.environ['DM_PLATFORM_RECOVERY_SECRET'])
    def _exp_backup():
        clock.set(ctx_plat_exp._expires_at)
        try: return (recovery_service.backup(vpath + '.bak4', ctx_plat_exp) or True)
        finally: clock.set(1000000.0)
    item('21-backup', _exp_backup)
    def _exp_restore():
        clock.set(ctx_plat_exp._expires_at)
        try: return (recovery_service.restore(vpath + '.bak4', ctx_plat_exp) or True)
        finally: clock.set(1000000.0)
    item('21-restore', _exp_restore)
    # 22 missing platform signing key -> subprocess exit 2 (isolated; not a vault violation but a config invariant)
    r22 = subprocess.run([sys.executable, '-c',
        'import os; os.environ.pop("DM_PLATFORM_RECOVERY_SIGNING_KEY", None); '
        'from app.daily_loop.services.platform_recovery import PlatformRecoveryProvider; PlatformRecoveryProvider.from_env()'],
        capture_output=True, text=True, cwd=str(BASE))
    if r22.returncode != 2:
        violations.append('22')
        _VAULT_CODE['22'] = 'E-VAULT-RECOVERY-KEY-MISSING-EXITCODE'
    # 23 restore success invariants
    try:
        recovery_service.backup(vpath + '.bak5', ctx_platform)
        vrepo.insert_vault(vault_id='V-006', subject_type='customer', subject_id='C-006', store_id='S001', plaintext_phone='13900000000', ctx=ctx_owner)
        rr = recovery_service.restore(vpath + '.bak5', ctx_platform)
        if not rr.get('restored'):
            violations.append('23-restore')
        else:
            if rr.get('reconnect_count', -1) != 1: violations.append('23-reconnect')
            if vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0] != 1: violations.append('23-rows')
            ec = _sqlite3.connect(vpath); n = ec.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]; ec.close()
            if n != 1: violations.append('23-ext')
    except Exception as e:
        item_errors.append({'test_id': '23', 'error': f'{type(e).__name__}: {e}'})
    # 24 restore failure invariance (wrong master key)
    try:
        orig = vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]
        os.environ['DM_VAULT_MASTER_KEY'] = 'wrong_key_at_least_16_chars!'
        from app.daily_loop.services.keyring import restore_vault, KeyRing as KR2
        try:
            restore_vault(vpath + '.bak5', vpath + '.x', KR2().get_master()); violations.append('24')
        except Exception:
            pass
        os.environ['DM_VAULT_MASTER_KEY'] = 'test_master_key_at_least_16_chars_long'
        if orig != vrepo.conn.execute("SELECT count(*) FROM dl_identity_vault").fetchone()[0]:
            violations.append('24-rows')
    except Exception as e:
        item_errors.append({'test_id': '24', 'error': f'{type(e).__name__}: {e}'})
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
    return violations, item_errors

def check_manifest():
    mp = BASE / "manifest.json"
    if not mp.exists():
        return _fail('manifest', ['E-MANIFEST-MISSING'], [{'message': 'manifest.json not found'}])
    manifest = json.load(open(mp))
    mf = manifest.get("files", {})
    excluded = set()
    for it in manifest.get("excluded_generated_files", []):
        excluded.add(it["path"] if isinstance(it, dict) else it)
    mm = ms = 0
    for rel, expected in mf.items():
        if rel in excluded: continue
        fp = BASE / rel
        if not fp.exists(): ms += 1; continue
        h = hashlib.sha256(); h.update(open(fp, 'rb').read())
        if h.hexdigest() != expected: mm += 1
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
