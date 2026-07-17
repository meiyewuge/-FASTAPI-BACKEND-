#!/usr/bin/env python3
"""
build_release.py - V1.3A.9-R8 single build entry.

Every report is derived from REAL subprocess results — no hardcoded PASS / counts.
Each step records: argv command, UTC start/end, duration_ms, exit code, and the
SHA-256 of its captured log. Any failing step aborts before a Release ZIP is made.

Order (work order §7):
  1 snapshot input baseline manifest (for change evidence)
  2 main/smoke/vendor/fault tests (real counts parsed)
  3 mutation tests --write-report --build-id <id>   (13/13 real)
  4 machine/security/fault reports from actual results
  5 verify required deliverables present
  6 regenerate manifest LAST (exclude manifest.json, mutation_report.json, evidence/)
  7 final Truth Gate (manifest closure 0/0/0)
  8 --package -> final ZIP

Usage:
  python3 build_release.py --release-version V1.3A.9-R8 --package
"""
import sys, os, re, json, subprocess, hashlib, time, uuid, zipfile, argparse
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST_EXCLUDED = ['manifest.json', 'mutation_report.json', 'build_execution_report.json']
WALK_EXCLUDED_DIRS = {'__pycache__', '.pytest_cache', '.venv', '.git', 'evidence'}

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''): h.update(chunk)
    return h.hexdigest()

def sha256_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def utc():
    return datetime.now(timezone.utc).isoformat()

def parse_unittest(out, err):
    """Return (ran, ok) from unittest -v output."""
    text = (out or '') + "\n" + (err or '')
    m = re.search(r'Ran (\d+) tests?', text)
    ran = int(m.group(1)) if m else 0
    ok = bool(re.search(r'\nOK', text)) and 'FAILED' not in text
    return ran, ok

STEPS = []
def run_step(name, cmd, timeout=1200):
    started = utc(); t0 = time.monotonic()
    r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, timeout=timeout)
    dt = round((time.monotonic() - t0) * 1000, 1)
    log = (r.stdout or '') + (r.stderr or '')
    STEPS.append({'name': name, 'command': cmd, 'started_at': started, 'ended_at': utc(),
                  'duration_ms': dt, 'exit_code': r.returncode, 'log_sha256': sha256_text(log)})
    print(f"[{name}] exit={r.returncode} ({dt:.0f}ms)")
    return r

def _list_tracked():
    out = []
    for root, dirs, filenames in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in WALK_EXCLUDED_DIRS]
        for fname in sorted(filenames):
            rel = str(Path(root) / fname).replace(str(BASE) + '/', '')
            if rel in MANIFEST_EXCLUDED: continue
            if fname.endswith('.db') or fname.endswith('.pyc'): continue
            out.append(rel)
    return out

def regenerate_manifest():
    files = {}
    for root, dirs, filenames in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in WALK_EXCLUDED_DIRS]
        for fname in sorted(filenames):
            fpath = Path(root) / fname
            rel = str(fpath).replace(str(BASE) + '/', '')
            if rel in MANIFEST_EXCLUDED: continue
            if fname.endswith('.db') or fname.endswith('.pyc'): continue
            files[rel] = sha256_file(fpath)
    manifest = {'excluded_generated_files': [{'path': e, 'reason': 'generated/volatile'} for e in MANIFEST_EXCLUDED],
                'files': files}
    (BASE / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return len(files)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--release-version', default='V1.3A.9-R8')
    ap.add_argument('--package', action='store_true')
    ap.add_argument('--build-id', default=str(uuid.uuid4()))
    args = ap.parse_args()

    for k, v in {'DM_VAULT_MASTER_KEY': 'test_master_key_at_least_16_chars_long',
                 'DM_CALLER_SIGNING_KEY': 'test_signing_key_at_least_16_chars',
                 'DM_SERVICE_PRINCIPAL_SECRET': 'test_service_secret',
                 'DM_PLATFORM_RECOVERY_SECRET': 'test_platform_secret_different',
                 'DM_PLATFORM_RECOVERY_SIGNING_KEY': 'test_recovery_signing_key_16chars'}.items():
        os.environ.setdefault(k, v)

    print("=" * 60); print(f"BUILD {args.release_version}  build_id={args.build_id}"); print("=" * 60)
    build = {'report_type': 'BUILD_EXECUTION_REPORT', 'version': args.release_version,
             'build_id': args.build_id, 'start_time': utc(), 'steps': STEPS}

    # 1: load the SEALED R7 baseline manifest (P0-6): change evidence must be vs
    #    the frozen R7 input, never vs the live/already-R8 output dir. Then
    #    regenerate an EARLY manifest so the mutation runner's internal
    #    normal-before/after gate passes; regenerated again as the LAST step (6).
    r7_baseline_path = BASE / 'r7_baseline_manifest.json'
    if not r7_baseline_path.exists():
        print("FATAL: r7_baseline_manifest.json (sealed R7 baseline) missing"); sys.exit(1)
    baseline = json.loads(r7_baseline_path.read_text()).get('files', {})
    baseline_source = "r7_baseline_manifest.json (R7 SHA 12c7bdf68a21d77cbd5046c12e5ba9e8f9caba39b9ac3030ce387232eee41eb3)"
    regenerate_manifest()

    # 2: tests (real counts)
    r_main = run_step('main_tests', [sys.executable, '-m', 'unittest', 'tests.run_tests', '-v'])
    r_smoke = run_step('smoke_tests', [sys.executable, '-m', 'unittest', 'tests.test_repo_smoke', '-v'])
    r_vendor = run_step('vendor_tests', [sys.executable, '-m', 'unittest', 'discover', '-s',
                        str(BASE / 'vendor' / 'dm_customer_holdings' / 'tests'), '-v'])
    r_fault = run_step('fault_injection', [sys.executable, '-m', 'unittest', 'tests.test_restore_fault_injection', '-v'])
    main_ran, main_ok = parse_unittest(r_main.stdout, r_main.stderr)
    smoke_ran, smoke_ok = parse_unittest(r_smoke.stdout, r_smoke.stderr)
    vendor_ran, vendor_ok = parse_unittest(r_vendor.stdout, r_vendor.stderr)
    fault_ran, fault_ok = parse_unittest(r_fault.stdout, r_fault.stderr)
    for label, r in [('main', r_main), ('smoke', r_smoke), ('vendor', r_vendor), ('fault', r_fault)]:
        if r.returncode != 0:
            print(f"FATAL: {label} tests failed"); sys.exit(1)

    # 3: mutation tests --write-report (13/13 real)
    r_mut = run_step('mutation_tests', [sys.executable, 'run_mutation_tests.py', '--write-report',
                     '--build-id', args.build_id, '--version', args.release_version], timeout=1800)
    if r_mut.returncode != 0:
        print("FATAL: mutation tests did not fully pass"); sys.exit(1)
    mutation_report = json.loads((BASE / 'mutation_report.json').read_text())

    # 4: ResourceWarning sweep (P0-2) — real count under PYTHONWARNINGS=always
    rw_total = 0
    rw_env = dict(os.environ, PYTHONWARNINGS='always')
    for cmd in [[sys.executable, 'run_truth_gate.py'],
                [sys.executable, '-m', 'unittest', 'tests.run_tests'],
                [sys.executable, '-m', 'unittest', 'tests.test_repo_smoke'],
                [sys.executable, '-m', 'unittest', 'tests.test_restore_fault_injection']]:
        rr = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, timeout=300, env=rw_env)
        rw_total += (rr.stdout + rr.stderr).count('ResourceWarning')

    # 4b: reports from actual results
    machine = {'report_type': 'MACHINE_TEST_REPORT', 'version': args.release_version, 'build_id': args.build_id,
               'python_version': sys.version.split()[0],
               'main_tests': {'ran': main_ran, 'ok': main_ok},
               'repository_smoke': {'ran': smoke_ran, 'ok': smoke_ok},
               'vendor_holdings': {'ran': vendor_ran, 'ok': vendor_ok},
               'restore_fault_injection': {'ran': fault_ran, 'ok': fault_ok},
               'total_base_tests': main_ran + smoke_ran + vendor_ran,
               'mutation_blocked': f"{mutation_report['blocked']}/{mutation_report['total_mutations']}",
               'mutation_sequence_pass': mutation_report['sequence_pass'],
               'selector_selftest_pass': mutation_report['selector_selftest']['pass'],
               'resource_warnings': rw_total}
    (BASE / 'machine_test_report.json').write_text(json.dumps(machine, indent=2, ensure_ascii=False))
    if rw_total != 0:
        print(f"FATAL: ResourceWarning count {rw_total} != 0"); sys.exit(1)

    # security invariants derived from the LIVE vault detector's 1..24 items (P0-7)
    r_vault = run_step('vault_detector', [sys.executable, 'run_truth_gate.py', '--checks', 'vault'])
    vault_result = None
    for line in r_vault.stdout.splitlines():
        if line.startswith('RESULT_JSON: '):
            vault_result = json.loads(line[len('RESULT_JSON: '):])
    items = {str(it['test_id']): it for it in (vault_result or {}).get('details', [])}
    expected_keys = {str(i) for i in range(1, 25)}
    key_set_ok = set(items.keys()) == expected_keys
    all_pass = key_set_ok and all(items[k]['status'] == 'PASS' for k in expected_keys)
    security = {'report_type': 'SECURITY_INVARIANTS_REPORT', 'version': args.release_version, 'build_id': args.build_id,
                'source': 'live run_truth_gate.py --checks vault',
                'total_invariants': 24, 'key_set_is_1_to_24': key_set_ok, 'all_held': all_pass,
                'invariants': {k: {'expected': items[k]['expected'], 'observed': items[k]['observed'],
                                   'status': items[k]['status'], 'failure_code': items[k].get('failure_code')}
                               for k in sorted(expected_keys, key=int)} if key_set_ok else {},
                'raw_detector_status': (vault_result or {}).get('status')}
    (BASE / 'security_invariants_report.json').write_text(json.dumps(security, indent=2, ensure_ascii=False))
    if not all_pass:
        print(f"FATAL: security invariants not 1..24 all-PASS (key_set_ok={key_set_ok})"); sys.exit(1)

    fault_report = {'report_type': 'RESTORE_FAULT_INJECTION_REPORT', 'version': args.release_version,
                    'build_id': args.build_id, 'ran': fault_ran, 'ok': fault_ok, 'exit_code': r_fault.returncode}
    (BASE / 'restore_fault_injection_report.json').write_text(json.dumps(fault_report, indent=2, ensure_ascii=False))

    # change evidence vs SEALED R7 baseline (P0-6): full before/after SHAs
    changed = {}
    for rel in sorted(baseline.keys()):
        fp = BASE / rel
        cur = sha256_file(fp) if fp.exists() else None
        if cur != baseline.get(rel):
            changed[rel] = {'baseline_sha': baseline.get(rel), 'current_sha': cur,
                            'changed': True, 'present': fp.exists()}
    new_files = sorted(set(f for f in _list_tracked() if f not in baseline))
    (BASE / 'change_evidence.json').write_text(json.dumps(
        {'report_type': 'CHANGE_EVIDENCE', 'version': args.release_version, 'build_id': args.build_id,
         'baseline_source': baseline_source, 'changed_vs_r7_baseline': changed,
         'changed_count': len(changed), 'new_files': new_files}, indent=2, ensure_ascii=False))

    # 5: verify required deliverables present
    for req in ['.env.example', '.env.recovery.example', 'PROVENANCE.md', 'requirements-lock.txt',
                'r7_baseline_manifest.json', 'mutation_report.json',
                'security_invariants_report.json', 'machine_test_report.json',
                'restore_fault_injection_report.json', 'change_evidence.json']:
        if not (BASE / req).exists():
            print(f"FATAL: required deliverable missing: {req}"); sys.exit(1)

    # 5b: single build_id must be present and identical across every formal report (P0-5)
    id_reports = ['machine_test_report.json', 'mutation_report.json', 'security_invariants_report.json',
                  'restore_fault_injection_report.json', 'change_evidence.json']
    seen = {}
    for rep in id_reports:
        bid = json.loads((BASE / rep).read_text()).get('build_id')
        seen[rep] = bid
    if any(v != args.build_id for v in seen.values()):
        print(f"FATAL: build_id mismatch across reports: {seen}"); sys.exit(1)
    print(f"build_id consistent across {len(id_reports)} reports: {args.build_id}")

    # 6: regenerate manifest LAST
    n = regenerate_manifest()
    print(f"manifest.json regenerated ({n} files)")

    # 7: final Truth Gate (manifest closure)
    r_gate = run_step('final_truth_gate', [sys.executable, 'run_truth_gate.py'])
    if r_gate.returncode != 0:
        print("FATAL: final truth gate failed"); sys.exit(1)

    build['end_time'] = utc()
    build['all_passed'] = True
    (BASE / 'build_execution_report.json').write_text(json.dumps(build, indent=2, ensure_ascii=False))
    print("\n" + "=" * 60); print("BUILD COMPLETE — all steps passed"); print("=" * 60)

    # 8: package
    if args.package:
        vtag = args.release_version.replace('.', '_').replace('-', '_')  # V1_3A_9_R8_R1
        zip_name = f"ZHIPU_DM_DAILY_LOOP_BATCH1_{vtag}_EVIDENCE_INTEGRITY_FINAL_CLOSURE.zip"
        zip_path = BASE.parent / zip_name
        arc_root = f"dm_daily_loop_batch1_{vtag.lower()}"
        if zip_path.exists(): zip_path.unlink()
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, dirs, filenames in os.walk(BASE):
                dirs[:] = [d for d in dirs if d not in ('__pycache__', '.pytest_cache', '.venv', '.git')]
                for fn in sorted(filenames):
                    if fn.endswith('.pyc') or fn.endswith('.db'): continue
                    fp = Path(root) / fn
                    rel = str(fp).replace(str(BASE) + '/', '')
                    z.write(fp, f"{arc_root}/{rel}")
        print(f"Release ZIP: {zip_path}")
        print(f"ZIP SHA-256: {sha256_file(zip_path)}")

if __name__ == "__main__":
    main()
