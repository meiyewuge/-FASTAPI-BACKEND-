"""测试配置加载与校验。"""

import os
import pytest
from search_router.config import SearchRouterConfig, _str_to_bool, _str_to_float, _str_to_int


class TestStrConverters:
    """字符串转 bool / float / int。"""

    def test_str_to_bool_true(self):
        """各种 true 写法。"""
        assert _str_to_bool("true") is True
        assert _str_to_bool("True") is True
        assert _str_to_bool("1") is True
        assert _str_to_bool("yes") is True
        assert _str_to_bool("on") is True

    def test_str_to_bool_false(self):
        """各种 false 写法。"""
        assert _str_to_bool("false") is False
        assert _str_to_bool("0") is False
        assert _str_to_bool("no") is False
        assert _str_to_bool("off") is False

    def test_str_to_bool_default(self):
        """None 时返回默认值。"""
        assert _str_to_bool(None, True) is True
        assert _str_to_bool(None, False) is False

    def test_str_to_float(self):
        """字符串转 float。"""
        assert _str_to_float("2.0", 0.0) == 2.0
        assert _str_to_float("30.5", 0.0) == 30.5
        assert _str_to_float(None, 99.9) == 99.9
        assert _str_to_float("invalid", 1.0) == 1.0

    def test_str_to_int(self):
        """字符串转 int。"""
        assert _str_to_int("20", 0) == 20
        assert _str_to_int("10", 0) == 10
        assert _str_to_int(None, 5) == 5
        assert _str_to_int("invalid", 7) == 7


class TestSearchRouterConfig:
    """SearchRouterConfig 配置测试。"""

    def test_defaults_dry_run_true(self):
        """SEARCH_ROUTER_DRY_RUN 默认 true。"""
        # 清除环境变量确保使用默认值
        old_val = os.environ.pop("SEARCH_ROUTER_DRY_RUN", None)
        try:
            cfg = SearchRouterConfig()
            assert cfg.dry_run is True
        finally:
            if old_val is not None:
                os.environ["SEARCH_ROUTER_DRY_RUN"] = old_val

    def test_defaults_mock_enabled_true(self):
        """PROVIDER_MOCK_ENABLED 默认 true。"""
        cfg = SearchRouterConfig()
        assert cfg.provider_mock_enabled is True

    def test_defaults_real_providers_false(self):
        """真实 Provider 默认 false。"""
        cfg = SearchRouterConfig()
        assert cfg.provider_bocha_enabled is False
        assert cfg.provider_glm_search_enabled is False
        assert cfg.provider_tavily_enabled is False

    def test_defaults_glm_enhancer_false(self):
        """GLM_ENHANCER_ENABLED 默认 false。"""
        cfg = SearchRouterConfig()
        assert cfg.glm_enhancer_enabled is False

    def test_cost_thresholds(self):
        """成本阈值：¥2 / ¥30 / ¥300。"""
        cfg = SearchRouterConfig()
        assert cfg.cost_limit_single_task == 2.0
        assert cfg.cost_limit_daily == 30.0
        assert cfg.cost_limit_monthly == 300.0

    def test_max_search_results_20(self):
        """单任务最大搜索结果 20。"""
        cfg = SearchRouterConfig()
        assert cfg.max_search_results == 20

    def test_max_candidate_cards_10(self):
        """单任务最大候选卡 10。"""
        cfg = SearchRouterConfig()
        assert cfg.max_candidate_cards == 10

    def test_should_use_mock_when_dry_run(self):
        """dry_run=true 时强制走 Mock。"""
        cfg = SearchRouterConfig(dry_run=True, provider_bocha_enabled=True)
        assert cfg.should_use_mock() is True

    def test_should_not_use_mock_when_real_enabled(self):
        """dry_run=false 且有真实 Provider 启用时走真实。"""
        cfg = SearchRouterConfig(dry_run=False, provider_bocha_enabled=True)
        assert cfg.should_use_mock() is False

    def test_should_use_real_enhancer_triple_lock(self):
        """三锁判断：三者同时满足才允许真实增强。"""
        # 三锁全开
        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        assert cfg.should_use_real_enhancer() is True

        # 缺一不可
        cfg = SearchRouterConfig(
            dry_run=True,  # dry_run=true
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=True,
        )
        assert cfg.should_use_real_enhancer() is False

        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=False,  # 未启用
            glm_enhancer_enabled=True,
        )
        assert cfg.should_use_real_enhancer() is False

        cfg = SearchRouterConfig(
            dry_run=False,
            provider_glm_search_enabled=True,
            glm_enhancer_enabled=False,  # 增强未启用
        )
        assert cfg.should_use_real_enhancer() is False

    def test_validate_dry_run_forces_real_providers_off(self):
        """dry_run=true 时真实 Provider 必须关闭。"""
        cfg = SearchRouterConfig(dry_run=True, provider_bocha_enabled=True)
        errors = cfg.validate()
        assert any("provider_bocha_enabled" in e for e in errors)

    def test_validate_cost_threshold_logic(self):
        """成本阈值逻辑关系校验。"""
        # single_task >= daily
        cfg = SearchRouterConfig(
            dry_run=False,
            cost_limit_single_task=30.0,
            cost_limit_daily=30.0,
        )
        errors = cfg.validate()
        assert any("cost_limit_single_task" in e for e in errors)

        # daily >= monthly
        cfg = SearchRouterConfig(
            dry_run=False,
            cost_limit_daily=300.0,
            cost_limit_monthly=300.0,
        )
        errors = cfg.validate()
        assert any("cost_limit_daily" in e for e in errors)

    def test_validate_valid_config(self):
        """合法配置 validate 返回空列表。"""
        cfg = SearchRouterConfig()
        errors = cfg.validate()
        assert errors == []
        assert cfg.is_valid() is True

    def test_to_dict_safe_desensitizes_keys(self):
        """to_dict(safe=True) 对 API Key 脱敏。"""
        cfg = SearchRouterConfig(bocha_api_key="sk-test1234567890abcd")
        d = cfg.to_dict(safe=True)
        assert "sk-t" in d["bocha_api_key"]
        assert "****" in d["bocha_api_key"]
        assert "test1234567890abcd" not in d["bocha_api_key"]

    def test_to_dict_safe_desensitizes_zhipu_key(self):
        """to_dict(safe=True) 对 ZHIPU_API_KEY 脱敏。"""
        cfg = SearchRouterConfig(zhipu_api_key="sk-zhipu1234567890abcd")
        d = cfg.to_dict(safe=True)
        assert "sk-z" in d["zhipu_api_key"]
        assert "****" in d["zhipu_api_key"]
        assert "zhipu1234567890abcd" not in d["zhipu_api_key"]

    def test_to_dict_unsafe_shows_keys(self):
        """to_dict(safe=False) 不脱敏。"""
        cfg = SearchRouterConfig(bocha_api_key="sk-test1234567890abcd")
        d = cfg.to_dict(safe=False)
        assert d["bocha_api_key"] == "sk-test1234567890abcd"

    def test_from_env_reads_zhipu_api_key(self):
        """from_env() 读取 ZHIPU_API_KEY。"""
        old = os.environ.get("ZHIPU_API_KEY")
        old_glm = os.environ.get("GLM_API_KEY")
        try:
            os.environ["ZHIPU_API_KEY"] = "sk-zhipu-test-key-1234567890"
            os.environ.pop("GLM_API_KEY", None)
            cfg = SearchRouterConfig.from_env()
            assert cfg.zhipu_api_key == "sk-zhipu-test-key-1234567890"
        finally:
            if old is not None:
                os.environ["ZHIPU_API_KEY"] = old
            else:
                os.environ.pop("ZHIPU_API_KEY", None)
            if old_glm is not None:
                os.environ["GLM_API_KEY"] = old_glm
            else:
                os.environ.pop("GLM_API_KEY", None)

    def test_from_env_zhipu_fallback_glm(self, tmp_path, monkeypatch):
        """ZHIPU_API_KEY 未设置时 fallback 到 GLM_API_KEY。

        使用 tmp_path 创建隔离的测试 env 文件，monkeypatch 确保进程
        中不存在 ZHIPU_API_KEY / GLM_API_KEY，不接触真实 .env。
        """
        # 确保环境变量不存在（monkeypatch 自动恢复）
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
        monkeypatch.delenv("GLM_API_KEY", raising=False)

        # 在 tmp_path 中创建隔离的测试 env 文件（占位值，非真实 Key）
        isolated_env = tmp_path / "isolated.env"
        test_glm_key = "sk-glm-fake-test-placeholder-key-0000"
        isolated_env.write_text(f"GLM_API_KEY={test_glm_key}\n", encoding="utf-8")

        # 通过 env_file 参数加载隔离 env，不调用无参数 from_env()
        cfg = SearchRouterConfig.from_env(env_file=str(isolated_env))
        assert cfg.zhipu_api_key == test_glm_key

    def test_from_env_zhipu_takes_priority_over_glm(self):
        """ZHIPU_API_KEY 优先于 GLM_API_KEY。"""
        old_zhipu = os.environ.get("ZHIPU_API_KEY")
        old_glm = os.environ.get("GLM_API_KEY")
        try:
            os.environ["ZHIPU_API_KEY"] = "sk-zhipu-primary-key"
            os.environ["GLM_API_KEY"] = "sk-glm-deprecated-key"
            cfg = SearchRouterConfig.from_env()
            assert cfg.zhipu_api_key == "sk-zhipu-primary-key"
        finally:
            if old_zhipu is not None:
                os.environ["ZHIPU_API_KEY"] = old_zhipu
            else:
                os.environ.pop("ZHIPU_API_KEY", None)
            if old_glm is not None:
                os.environ["GLM_API_KEY"] = old_glm
            else:
                os.environ.pop("GLM_API_KEY", None)

    def test_from_env_reads_env_vars(self):
        """from_env() 读取环境变量。"""
        old = os.environ.get("SEARCH_ROUTER_DRY_RUN")
        try:
            os.environ["SEARCH_ROUTER_DRY_RUN"] = "false"
            cfg = SearchRouterConfig.from_env()
            assert cfg.dry_run is False
        finally:
            if old is not None:
                os.environ["SEARCH_ROUTER_DRY_RUN"] = old
            else:
                os.environ.pop("SEARCH_ROUTER_DRY_RUN", None)
