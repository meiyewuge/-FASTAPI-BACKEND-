#!/usr/bin/env python3
"""Run the C1-B API matrix + regression suites and emit CLAUDE_C1_B_API_TEST_REPORT.json.

No hand-written results: each gate is a real subprocess whose exit code and
parsed counts are recorded. The API matrix writes structured per-case evidence
via DM_C1B_EVIDENCE_PATH.
"""
import os, sys, json, re, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BUILD_ID = os.environ.get('DM_C1B_BUILD_ID', 'c1b-adhoc')


def utc():
    return datetime.now(timezone.utc).isoformat()


def parse_unittest(text):
    m = re.search(r'Ran (\d+) tests?', text)
    ran = int(m.group(1)) if m else 0
    ok = bool(re.search(r'\nOK', text)) and 'FAILED' not in text
    return ran, ok


def run(name, cmd, env):
    r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True, timeout=1800, env=env)
    text = (r.stdout or '') + (r.stderr or '')
    ran, _unit_ok = parse_unittest(text)
    # exit code is authoritative (Truth Gate is not unittest output); ran is
    # informational for the unittest-based steps.
    return {'name': name, 'command': cmd, 'exit_code': r.returncode,
            'ran': ran, 'ok': r.returncode == 0}, text


def main():
    env = dict(os.environ,
               PYTHONWARNINGS='always',
               DM_VAULT_MASTER_KEY='test_master_key_at_least_16_chars_long',
               DM_CALLER_SIGNING_KEY='test_signing_key_at_least_16_chars',
               DM_SERVICE_PRINCIPAL_SECRET='test_service_secret',
               DM_ADAPTER_SHARED_SECRET='test_adapter_shared_secret_16c',
               DM_PLATFORM_RECOVERY_SECRET='test_platform_secret_different',
               DM_PLATFORM_RECOVERY_SIGNING_KEY='test_recovery_signing_key_16chars')

    matrix_evidence = BASE / 'evidence' / 'c1b_api_matrix.json'
    matrix_evidence.parent.mkdir(parents=True, exist_ok=True)
    env['DM_C1B_EVIDENCE_PATH'] = str(matrix_evidence)

    steps = []
    api_step, api_log = run('c1b_api_matrix',
                            [sys.executable, '-m', 'unittest', 'tests.test_c1b_api', '-v'], env)
    steps.append(api_step)
    fastapi_step, _ = run('c1b_fastapi_integration',
                          [sys.executable, '-m', 'unittest', 'tests.test_c1b_fastapi_integration', '-v'], env)
    steps.append(fastapi_step)
    golden_step, _ = run('c1b_golden_vectors',
                         [sys.executable, '-m', 'unittest', 'tests.test_c1b_golden_vectors', '-v'], env)
    steps.append(golden_step)
    # regression (item 13): frozen suites unchanged by C1-B-R1 on the R1b baseline
    for name, cmd in [
        ('regression_truth_gate', [sys.executable, 'run_truth_gate.py']),
        ('regression_main_tests', [sys.executable, '-m', 'unittest', 'tests.run_tests']),
        ('regression_smoke', [sys.executable, '-m', 'unittest', 'tests.test_repo_smoke']),
        ('regression_vendor', [sys.executable, '-m', 'unittest', 'discover', '-s', 'vendor/dm_customer_holdings/tests']),
        ('regression_fault_injection', [sys.executable, '-m', 'unittest', 'tests.test_restore_fault_injection', '-v']),
    ]:
        st, _ = run(name, cmd, env)
        steps.append(st)

    matrix = json.loads(matrix_evidence.read_text()) if matrix_evidence.exists() else {}
    all_ok = all(s['exit_code'] == 0 for s in steps)
    report = {
        'report_type': 'CLAUDE_C1_B_API_TEST_REPORT',
        'version': 'V1.3A.9-R8-R2B-R1B-C1B-R1',
        'protocol': 'dm-s2s-v2',
        'build_id': BUILD_ID,
        'generated_at': utc(),
        'python': sys.version.split()[0],
        'holds': {'IDENTITY_SOURCE_HOLD': True, 'RECOVERY_HOLD': True,
                  'EXTERNAL_FACADE': 'NOT_MOUNTED', 'DOCKER_RUNTIME': 'NOT_EXECUTED_NO_REGISTRY_EGRESS'},
        'matrix_total': matrix.get('total'),
        'matrix_passed': matrix.get('passed'),
        'matrix_cases': matrix.get('cases', []),
        'steps': steps,
        'all_pass': all_ok,
        'verdict': 'PASS' if all_ok else 'FAIL',
    }
    out = BASE.parent / 'CLAUDE_C1_B_API_TEST_REPORT.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"verdict={report['verdict']} matrix={report['matrix_passed']}/{report['matrix_total']}")
    for s in steps:
        print(f"  {s['name']}: exit={s['exit_code']} ran={s['ran']} ok={s['ok']}")
    print(f"report: {out}")
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
