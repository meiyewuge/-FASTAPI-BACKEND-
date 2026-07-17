#!/usr/bin/env python3
"""
run_mutation_tests.py - V1.3A.9-R8 Stage C black-box mutation harness.

P0-1  BLOCKED requires a structured semantic failure_code (∈ the mutation's
      allowed set) AND hits_match — not a bare exit-1.
P0-2..P0-6  Mutations reach the real security path (no SQL/syntax/AttributeError
      short-circuits); each is caught by a detector emitting its semantic code.
P0-10 Report carries started_at/ended_at/duration_ms/timed_out/signal, argv
      detector_command, normal-before/after raw logs + SHAs, selector self-test.
P0-12 Reproducible: build_id injected by the top-level build; default (replay)
      mode compares only a stable signature (volatile fields excluded).

Modes:
  python3 run_mutation_tests.py --write-report --build-id <id>   # build
  python3 run_mutation_tests.py                                   # replay (stable compare)
"""
import sys, os, json, shutil, subprocess, tempfile, hashlib, argparse, time, uuid, re, signal as _signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ORIGIN = Path(__file__).resolve().parent
BUILD_ID = str(uuid.uuid4())
DETECTOR_TIMEOUT = 120

def _utc():
    return datetime.now(timezone.utc).isoformat()

@dataclass
class MutationSpec:
    name: str
    target_file: str
    old: str
    new: str
    expected_hits: int
    detector_id: str
    expected_failure_code: str      # the semantic code the detector MUST emit
    recompute_manifest: bool = True
    special: str = None

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''): h.update(chunk)
    return h.hexdigest()

def sha256_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def recompute_manifest(work):
    EXCLUDED = ['manifest.json', 'run_truth_gate.py', 'run_mutation_tests.py']
    files = {}
    for root, dirs, filenames in os.walk(work):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache', 'evidence', '.venv', '.git')]
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            rel = str(fpath).replace(str(work) + '/', '')
            if rel in EXCLUDED: continue
            if fname.endswith('.db') or fname.endswith('.pyc'): continue
            files[rel] = sha256_file(fpath)
    manifest = {'excluded_generated_files': [{'path': e, 'reason': 'generated'} for e in EXCLUDED], 'files': files}
    with open(work / 'manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

# ── Mutation matrix (semantically-valid; each reaches the real path) ──
MUTATIONS = [
    MutationSpec("m1_dataclass_drift", 'app/daily_loop/services/repository.py',
                 'm.member_id', 'm.nonexistent_xyz', 2, 'main_tests', 'E-MAIN-TESTS-FAIL'),
    # P0-2: SQL-valid no-op keeps schema + trigger; cross-store write now succeeds.
    MutationSpec("m2_trigger_neutered", 'app/daily_loop/migrations/001_initial_schema.sql',
                 "THEN RAISE(ABORT, 'E-SCOPE: customer does not belong to this store')", "THEN 1", 7,
                 'cross_store', 'E-CROSS-STORE-SEMANTIC-BYPASS'),
    MutationSpec("m3_syntax_error", 'tests/run_tests.py',
                 'import unittest', 'INVALID SYNTAX {{{{}}}\nimport unittest', 1,
                 'assertion_linter', 'E-TEST-SYNTAX-ERROR'),
    MutationSpec("m4_unlisted_file", '.hidden_mutation_test', '', 'secret', 1,
                 'manifest', 'E-MANIFEST-UNLISTED', recompute_manifest=False),
    # P0-4: keep ctx=None -> PermissionError, drop role/store authz -> staff/cross write succeeds.
    MutationSpec("m5_vault_spoof", 'app/daily_loop/services/vault_repository.py',
                 "self._authorize('write', ctx, store_id)", "self._require_context(ctx, 'write')", 1,
                 'vault', 'E-VAULT-WRITE-AUTH-BYPASS'),
    # P0-3: fully remove the trigger block; schema still initialises; trigger absent.
    MutationSpec("m6_delete_trigger", 'app/daily_loop/migrations/001_initial_schema.sql',
                 '', '', 1, 'cross_store', 'E-CROSS-STORE-TRIGGER-MISSING',
                 recompute_manifest=True, special='remove_appointment_trigger'),
    MutationSpec("m7_manifest_missing", 'manifest.json', '__REMOVE_FIRST_ENTRY__', '', 1,
                 'manifest', 'E-MANIFEST-MISSING', recompute_manifest=False, special='m7_manifest_missing'),
    MutationSpec("m8_tautology", 'tests/run_tests.py',
                 'self.assertEqual(len(rows), 1)', 'self.assertTrue(True)', 2,
                 'assertion_linter', 'E-ASSERTION-TAUTOLOGY'),
    # P0-5: drop rotate role/store authz -> manager/cross-store rotate succeeds.
    MutationSpec("m9_rotate_auth_bypass", 'app/daily_loop/services/vault_repository.py',
                 "self._authorize('rotate', ctx, ctx.store_id)", "self._require_context(ctx, 'rotate')", 1,
                 'vault', 'E-VAULT-ROTATE-AUTH-BYPASS'),
    # P0-6: syntax-valid True -> `if not True:` -> provider verification genuinely bypassed.
    MutationSpec("m10_verifier_mix", 'app/daily_loop/services/vault_recovery_service.py',
                 "self._provider.verify(recovery_ctx)", "True", 2,
                 'vault', 'E-RECOVERY-PROVIDER-VERIFY-BYPASS'),
    MutationSpec("m11_duplicate_reconnect", 'app/daily_loop/services/vault_recovery_service.py',
                 "reconnect_count = 1", "reconnect_count = 1; reconnect_count = 2  # duplicate", 2,
                 'vault', 'E-VAULT-RECONNECT-COUNT'),
    MutationSpec("m12_unique_tautology", 'tests/run_tests.py',
                 "self.assertFalse(result['confirmed'])", 'self.assertTrue(True)', 1,
                 'assertion_linter', 'E-ASSERTION-TAUTOLOGY'),
    MutationSpec("m13_aad_bypass", 'app/daily_loop/services/keyring.py',
                 "decrypt_aad = aad if isinstance(aad, bytes) else aad.encode('utf-8')",
                 "decrypt_aad = b''  # AAD neutered", 1,
                 'aad_class_binding', 'E-AAD-BINDING-BROKEN'),
]

def apply_mutation(work, spec):
    if spec.special == 'm7_manifest_missing':
        # Manifest lists a file that does not exist on disk -> detector reports MISSING.
        p = work / 'manifest.json'
        m = json.loads(p.read_text())
        m.setdefault('files', {})['__phantom_missing_file__.py'] = '0' * 64
        p.write_text(json.dumps(m, indent=2))
        return 1
    if spec.special == 'remove_appointment_trigger':
        p = work / spec.target_file
        content = p.read_text()
        # Remove the entire CREATE TRIGGER ... trg_appointment_cross_store_check ... END; block.
        pattern = re.compile(
            r"CREATE TRIGGER IF NOT EXISTS trg_appointment_cross_store_check.*?\n    END;\n",
            re.DOTALL)
        new_content, n = pattern.subn("-- trigger removed by mutation\n", content)
        if n != 1:
            raise ValueError(f'trigger block removal expected 1, got {n}')
        p.write_text(new_content)
        return 1
    if spec.name == 'm4_unlisted_file':
        (work / spec.target_file).write_text(spec.new if spec.new else 'secret')
        return 1
    p = work / spec.target_file
    content = p.read_text()
    actual_hits = content.count(spec.old)
    if actual_hits == 0:
        raise ValueError(f'mutation target not found: {spec.old[:60]}')
    p.write_text(content.replace(spec.old, spec.new))
    return actual_hits

def detector_argv(detector_id):
    """Normalized argv (stable, machine-independent) for the report."""
    return ["python3", "run_truth_gate.py", "--checks", detector_id]

def run_detector(work, detector_id):
    """Run the detector; return (exit_code, parsed_result, stdout, stderr, timed_out, sig)."""
    cmd = [sys.executable, 'run_truth_gate.py', '--checks', detector_id]
    timed_out = False
    sig = None
    try:
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=DETECTOR_TIMEOUT)
        rc, out, err = r.returncode, r.stdout, r.stderr
        if rc < 0:
            sig = _signal.Signals(-rc).name
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc, out, err = 124, (e.stdout or ''), (e.stderr or '')
    parsed = None
    for line in out.splitlines():
        if line.startswith('RESULT_JSON: '):
            try: parsed = json.loads(line[len('RESULT_JSON: '):])
            except Exception: parsed = None
    return rc, parsed, out, err, timed_out, sig

def run_full_gate(work):
    cmd = [sys.executable, 'run_truth_gate.py']
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout, r.stderr

def run_selector_selftest(work):
    cmd = [sys.executable, 'run_truth_gate.py', '--selftest']
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=300)
    parsed = None
    for line in r.stdout.splitlines():
        if line.startswith('RESULT_JSON: '):
            parsed = json.loads(line[len('RESULT_JSON: '):])
    return r.returncode, parsed

def stable_signature(report):
    """Volatile-free projection for reproducible replay comparison (P0-12)."""
    sigs = []
    for r in report['results']:
        # NOTE: raw sha_before/sha_after are intentionally excluded — for the
        # manifest-targeting mutation (m7) they depend on build ordering. The
        # boolean sha_changed is stable and preserves the "the file really changed"
        # invariant without coupling the signature to environment-specific hashes.
        sigs.append({
            'name': r['name'], 'detector_id': r['detector_id'], 'result': r['result'],
            'detector_command': r['detector_command'],
            'expected_failure_code': r['expected_failure_code'],
            'observed_failure_codes': r['observed_failure_codes'],
            'expected_hits': r['expected_hits'], 'actual_hits': r['actual_hits'],
            'hits_match': r['hits_match'], 'exit_code': r['exit_code'],
            'sha_changed': r['sha_changed'],
        })
    # NOTE: 'version' and 'build_id' are deliberately excluded — the stable
    # signature captures mutation BEHAVIOUR (results/codes/hits), not labels, so
    # a default-mode replay reproduces it without needing --version/--build-id.
    return {
        'total_mutations': report['total_mutations'],
        'blocked': report['blocked'], 'false_green': report['false_green'],
        'error_count': report['error_count'], 'sequence_pass': report['sequence_pass'],
        'normal_before_exit': report['normal_before_exit'], 'normal_after_exit': report['normal_after_exit'],
        'selector_selftest_pass': report['selector_selftest']['pass'],
        'signatures': sigs,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-report', action='store_true')
    parser.add_argument('--version', default='V1.3A.9-R8')
    parser.add_argument('--build-id', default=BUILD_ID)
    args = parser.parse_args()

    total_start = time.monotonic()
    print("=" * 60)
    print(f"Black-Box Mutation Tests {args.version}")
    print(f"Build ID: {args.build_id}")
    print("=" * 60)
    print(f"Total mutations: {len(MUTATIONS)}\n")

    log_dir = ORIGIN / "evidence" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # normal-before (full gate on pristine origin)
    nb_rc, nb_out, nb_err = run_full_gate(ORIGIN)
    (log_dir / 'normal_before.stdout.log').write_text(nb_out)
    (log_dir / 'normal_before.stderr.log').write_text(nb_err)

    results = []
    all_passed = True
    for spec in MUTATIONS:
        started = _utc(); t0 = time.monotonic()
        tmp = tempfile.mkdtemp()
        work = Path(tmp) / 'work'
        shutil.copytree(ORIGIN, work, ignore=shutil.ignore_patterns(
            '__pycache__', '.pytest_cache', '*.pyc', 'evidence', '.venv', '.git',
            'mutation_report.json'))
        try:
            tgt = work / spec.target_file
            sha_before = sha256_file(tgt) if (spec.special != 'm4_unlisted_file' and tgt.exists()) else ''
            actual_hits = apply_mutation(work, spec)
            sha_after = sha256_file(tgt) if tgt.exists() else ''
            hits_match = (actual_hits == spec.expected_hits)
            sha_changed = (sha_before != sha_after)
            if spec.recompute_manifest:
                recompute_manifest(work)
            rc, parsed, out, err, timed_out, sig = run_detector(work, spec.detector_id)
            # persist evidence logs
            (log_dir / f'{spec.name}.stdout.log').write_text(out)
            (log_dir / f'{spec.name}.stderr.log').write_text(err)
            status = parsed.get('status') if parsed else None
            observed_codes = sorted(parsed.get('failure_codes', [])) if parsed else []
            code_ok = spec.expected_failure_code in observed_codes
            # P0-1: BLOCKED iff real FAIL(exit1) + allowed semantic code + hits match
            if status == 'FAIL' and rc == 1 and code_ok and hits_match:
                result = 'BLOCKED'
            elif status == 'ERROR' or rc == 3:
                result = 'ERROR'; all_passed = False
            elif rc == 0 or status == 'PASS':
                result = 'FALSE_GREEN'; all_passed = False
            elif status == 'FAIL' and not code_ok:
                result = 'WRONG_CODE'; all_passed = False
            elif not hits_match:
                result = 'HITS_MISMATCH'; all_passed = False
            else:
                result = 'ERROR'; all_passed = False
            ended = _utc(); dt_ms = round((time.monotonic() - t0) * 1000, 1)
            mark = '✓' if result == 'BLOCKED' else '✗'
            print(f"[{spec.name}] detector={spec.detector_id} {result} {mark} "
                  f"(hits={actual_hits}/{spec.expected_hits}, code={'ok' if code_ok else 'MISS'}, {dt_ms:.0f}ms)")
            results.append({
                "name": spec.name, "result": result, "detector_id": spec.detector_id,
                "detector_command": detector_argv(spec.detector_id),
                "expected_failure_code": spec.expected_failure_code,
                "observed_failure_codes": observed_codes,
                "observed_status": status, "expected_hits": spec.expected_hits,
                "actual_hits": actual_hits, "hits_match": hits_match,
                "target_file": spec.target_file, "sha_before": sha_before, "sha_after": sha_after,
                "sha_changed": sha_changed, "exit_code": rc,
                "started_at": started, "ended_at": ended, "duration_ms": dt_ms,
                "timed_out": timed_out, "signal": sig,
                "stdout_log": f"evidence/logs/{spec.name}.stdout.log",
                "stdout_sha256": sha256_text(out),
                "stderr_log": f"evidence/logs/{spec.name}.stderr.log",
                "stderr_sha256": sha256_text(err),
            })
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # sequence normal-after
    na_rc, na_out, na_err = run_full_gate(ORIGIN)
    (log_dir / 'normal_after.stdout.log').write_text(na_out)
    (log_dir / 'normal_after.stderr.log').write_text(na_err)
    seq_ok = (nb_rc == 0 and na_rc == 0)
    if not seq_ok: all_passed = False

    # selector self-test
    st_rc, st_parsed = run_selector_selftest(ORIGIN)
    selftest = {'pass': (st_rc == 0 and bool(st_parsed) and st_parsed.get('status') == 'PASS'),
                'exit_code': st_rc, 'per_selector': (st_parsed or {}).get('per_selector', {})}
    if not selftest['pass']: all_passed = False

    blocked = sum(1 for r in results if r['result'] == 'BLOCKED')
    total_duration = round(time.monotonic() - total_start, 1)
    print("\n" + "=" * 60)
    print(f"RESULT: {blocked}/{len(MUTATIONS)} blocked, sequence {'PASS' if seq_ok else 'FAIL'}, "
          f"selftest {'PASS' if selftest['pass'] else 'FAIL'}")
    print("=" * 60)

    report = {
        "report_type": "MUTATION_TEST_REPORT", "version": args.version, "build_id": args.build_id,
        "generated_at": _utc(), "total_mutations": len(MUTATIONS), "blocked": blocked,
        "false_green": sum(1 for r in results if r['result'] == 'FALSE_GREEN'),
        "error_count": sum(1 for r in results if r['result'] in ('ERROR', 'WRONG_CODE', 'HITS_MISMATCH')),
        "sequence_pass": seq_ok, "normal_before_exit": nb_rc, "normal_after_exit": na_rc,
        "normal_before_log": "evidence/logs/normal_before.stdout.log",
        "normal_after_log": "evidence/logs/normal_after.stdout.log",
        "normal_before_stdout_sha256": sha256_text(nb_out),
        "normal_after_stdout_sha256": sha256_text(na_out),
        "selector_selftest": selftest,
        "total_duration_seconds": total_duration, "results": results,
    }
    report['stable_signature'] = stable_signature(report)

    if args.write_report:
        (ORIGIN / 'mutation_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Report written: {ORIGIN / 'mutation_report.json'}")
        sys.exit(0 if (all_passed and blocked == len(MUTATIONS)) else 1)
    else:
        bundled_path = ORIGIN / 'mutation_report.json'
        if not bundled_path.exists():
            print("ERROR: no bundled mutation_report.json found"); sys.exit(1)
        bundled = json.loads(bundled_path.read_text())
        cand = json.dumps(report['stable_signature'], sort_keys=True)
        bund = json.dumps(bundled.get('stable_signature', {}), sort_keys=True)
        if cand == bund:
            print("Stable-signature replay match PASS ✓")
            sys.exit(0 if (all_passed and blocked == len(MUTATIONS)) else 1)
        print("ERROR: stable signature does not match bundled report")
        # emit a small diff hint
        for k in sorted(set(json.loads(cand).keys()) | set(json.loads(bund).keys())):
            cv, bv = json.loads(cand).get(k), json.loads(bund).get(k)
            if cv != bv and k != 'signatures':
                print(f"  {k}: candidate={cv} bundled={bv}")
        sys.exit(1)

if __name__ == "__main__":
    main()
