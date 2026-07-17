#!/usr/bin/env python3
"""
V1.3A.1 A5: assertion_linter.py — Rejects tautological assertions.

Fails if any test method:
- Has no assert statement
- Only has assertTrue(True) / assertFalse(False) / assertEqual(1, 1) tautologies
"""
import ast, sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / 'tests'

REAL_ASSERTS = {'assertEqual', 'assertNotEqual', 'assertTrue', 'assertFalse',
                'assertIsNone', 'assertIsNotNone', 'assertIn', 'assertNotIn',
                'assertRaises', 'assertIs', 'assertIsNot', 'assertIsInstance',
                'assertGreater', 'assertGreaterEqual', 'assertLess', 'assertLessEqual',
                'assertRegex', 'assertWarns', 'assertAlmostEqual', 'assertCountEqual',
                'assertDictEqual', 'assertListEqual', 'assertSetEqual', 'assertTupleEqual',
                'fail'}

def is_tautological(node):
    """Check if an assertion is tautological (always passes)."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        method = node.func.attr
        if method in ('assertTrue', 'assertFalse'):
            if node.args and isinstance(node.args[0], ast.Constant):
                val = node.args[0].value
                if method == 'assertTrue' and val is True:
                    return True
                if method == 'assertFalse' and val is False:
                    return True
        if method == 'assertEqual':
            if len(node.args) >= 2:
                left, right = node.args[0], node.args[1]
                if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
                    if left.value == right.value:
                        return True
    return False

def lint_tests():
    errors = []
    for py_file in sorted(TESTS_DIR.glob('*.py')):
        if py_file.name.startswith('_'): continue
        with open(py_file) as f:
            try: tree = ast.parse(f.read())
            except: continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                has_real_assert = False
                has_tautology = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Assert):
                        if isinstance(child.test, ast.Constant) and child.test.value is True:
                            has_tautology = True
                        else:
                            has_real_assert = True
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        if child.func.attr in REAL_ASSERTS:
                            if is_tautological(child):
                                has_tautology = True
                            else:
                                has_real_assert = True
                if not has_real_assert:
                    if has_tautology:
                        errors.append(f'{py_file.name}::{node.name}: only tautological assertions')
                    else:
                        errors.append(f'{py_file.name}::{node.name}: no real assertion found')
    return errors

if __name__ == '__main__':
    errors = lint_tests()
    if errors:
        print(f'FAIL: {len(errors)} test methods without real assertions')
        for e in errors: print(f'  X {e}')
        sys.exit(1)
    else:
        print('PASS: all test methods have real assertions')
    sys.exit(0)
