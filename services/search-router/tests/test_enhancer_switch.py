"""测试 GLM Enhancer 三锁判断 8 种组合（T2B）。

三锁：not dry_run 且 PROVIDER_GLM_SEARCH_ENABLED 且 GLM_ENHANCER_ENABLED。
只有 (dry_run=false, glm=true, enhancer=true) → True，其余 7 种 → False。
不接真实 Key、不联网、不真实调用 GLM。
"""

import itertools

import pytest

from search_router.config import SearchRouterConfig
from search_router.manager import should_use_real_enhancer


def _cfg(dry_run, glm, enhancer):
    return SearchRouterConfig(
        dry_run=dry_run,
        provider_glm_search_enabled=glm,
        glm_enhancer_enabled=enhancer,
    )


# 8 种组合逐一断言（参数化）
_COMBOS = list(itertools.product([True, False], repeat=3))  # (dry_run, glm, enhancer)


@pytest.mark.parametrize("dry_run,glm,enhancer", _COMBOS)
def test_eight_combinations(dry_run, glm, enhancer):
    expected = (not dry_run) and glm and enhancer
    assert should_use_real_enhancer(_cfg(dry_run, glm, enhancer)) is expected


def test_only_all_three_locks_open_returns_true():
    assert should_use_real_enhancer(_cfg(False, True, True)) is True


def test_dry_run_true_blocks_even_if_others_on():
    assert should_use_real_enhancer(_cfg(True, True, True)) is False


def test_glm_disabled_blocks():
    assert should_use_real_enhancer(_cfg(False, False, True)) is False


def test_enhancer_disabled_blocks():
    assert should_use_real_enhancer(_cfg(False, True, False)) is False


def test_exactly_one_combo_true_in_eight():
    results = [should_use_real_enhancer(_cfg(*c)) for c in _COMBOS]
    assert sum(results) == 1  # 8 种里只有 1 种为 True


def test_consistency_with_config_method():
    # 与 T1 config.should_use_real_enhancer() 行为一致
    for c in _COMBOS:
        cfg = _cfg(*c)
        assert should_use_real_enhancer(cfg) == cfg.should_use_real_enhancer()
