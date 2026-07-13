"""测试日志脱敏功能。"""

import io
import logging
import pytest
from search_router.logger import (
    desensitize_key,
    desensitize_url,
    set_desensitize,
    is_desensitize_enabled,
    setup_logger,
    DesensitizeFilter,
)


class TestDesensitizeKey:
    """API Key 脱敏。"""

    def setup_method(self):
        """每个测试前确保脱敏开启。"""
        set_desensitize(True)

    def test_long_key_desensitized(self):
        """长 Key 前4后4可见，中间 ****。"""
        result = desensitize_key("sk-x8k9z1234567890abcd")
        assert result == "sk-x****abcd"
        assert "1234567890" not in result

    def test_short_key_desensitized(self):
        """短 Key（<=8）只保留首字符。"""
        result = desensitize_key("abc12345")
        assert result == "a***"
        assert "bc12345" not in result

    def test_empty_key(self):
        """空 Key 返回空字符串。"""
        assert desensitize_key("") == ""
        assert desensitize_key(None) == ""

    def test_desensitize_disabled(self):
        """关闭脱敏时返回原始 Key。"""
        set_desensitize(False)
        result = desensitize_key("sk-x8k9z1234567890abcd")
        assert result == "sk-x8k9z1234567890abcd"
        set_desensitize(True)  # 恢复

    def test_key_with_whitespace(self):
        """Key 前后空白被 strip。"""
        result = desensitize_key("  sk-x8k9z1234567890abcd  ")
        assert result == "sk-x****abcd"


class TestDesensitizeUrl:
    """URL 脱敏。"""

    def setup_method(self):
        """每个测试前确保脱敏开启。"""
        set_desensitize(True)

    def test_url_with_token_desensitized(self):
        """URL 中 token 参数被脱敏。"""
        url = "https://api.example.com/search?q=test&token=abc123secret"
        result = desensitize_url(url)
        assert "token=***" in result
        assert "abc123secret" not in result
        assert "q=test" in result

    def test_url_with_api_key_desensitized(self):
        """URL 中 api_key 参数被脱敏。"""
        url = "https://api.example.com/path?key=sk-secret123&format=json"
        result = desensitize_url(url)
        assert "key=***" in result
        assert "sk-secret123" not in result
        assert "format=json" in result

    def test_url_without_sensitive_params(self):
        """无敏感参数的 URL 不变。"""
        url = "https://api.example.com/search?q=美业AI&page=1"
        result = desensitize_url(url)
        assert result == url

    def test_url_multiple_sensitive_params(self):
        """多个敏感参数都被脱敏。"""
        url = "https://api.example.com/data?token=abc&api_key=xyz&secret=123&q=test"
        result = desensitize_url(url)
        assert "token=***" in result
        assert "api_key=***" in result
        assert "secret=***" in result
        assert "q=test" in result

    def test_url_empty(self):
        """空 URL 返回空字符串。"""
        assert desensitize_url("") == ""
        assert desensitize_url(None) == ""

    def test_url_desensitize_disabled(self):
        """关闭脱敏时 URL 不变。"""
        set_desensitize(False)
        url = "https://api.example.com/search?token=secret"
        result = desensitize_url(url)
        assert result == url
        set_desensitize(True)

    def test_sensitive_param_case_insensitive(self):
        """敏感参数名不区分大小写。"""
        url = "https://api.example.com/path?TOKEN=secret123&q=test"
        result = desensitize_url(url)
        assert "TOKEN=***" in result or "token=***" in result.lower()
        assert "secret123" not in result


class TestSetupLogger:
    """日志器初始化。"""

    def test_setup_logger_returns_logger(self):
        """setup_logger 返回 Logger 实例。"""
        logger = setup_logger("test_logger_1", "DEBUG", True)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger_1"
        assert logger.level == logging.DEBUG

    def test_setup_logger_no_duplicate_handlers(self):
        """重复初始化不添加重复 handler。"""
        logger1 = setup_logger("test_logger_2", "INFO", True)
        handler_count_1 = len(logger1.handlers)
        logger2 = setup_logger("test_logger_2", "INFO", True)
        assert logger1 is logger2
        assert len(logger2.handlers) == handler_count_1

    def test_setup_logger_sets_desensitize(self):
        """setup_logger 设置脱敏开关。"""
        set_desensitize(False)
        setup_logger("test_logger_3", "INFO", True)
        assert is_desensitize_enabled() is True

        setup_logger("test_logger_4", "INFO", False)
        assert is_desensitize_enabled() is False
        set_desensitize(True)  # 恢复默认


class TestDesensitizeFilter:
    """日志脱敏过滤器。"""

    def test_filter_desensitizes_url_in_message(self):
        """日志消息中的 URL 被脱敏。"""
        set_desensitize(True)
        f = DesensitizeFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Calling https://api.example.com/search?token=secret123",
            args=None, exc_info=None,
        )
        f.filter(record)
        assert "secret123" not in str(record.msg)
        assert "***" in str(record.msg)

    def test_filter_desensitizes_key_in_message(self):
        """日志消息中的 API Key 被脱敏。"""
        set_desensitize(True)
        f = DesensitizeFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Using API key: sk-x8k9z1234567890abcd",
            args=None, exc_info=None,
        )
        f.filter(record)
        assert "1234567890abcd" not in str(record.msg)
        assert "****" in str(record.msg)

    def test_filter_passes_normal_message(self):
        """正常日志消息不被修改。"""
        set_desensitize(True)
        f = DesensitizeFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Search completed with 5 results",
            args=None, exc_info=None,
        )
        f.filter(record)
        assert "Search completed with 5 results" in str(record.msg)


class TestSetupLoggerDesensitization:
    """setup_logger 真实输出脱敏测试。"""

    def setup_method(self):
        """每个测试前确保脱敏开启。"""
        set_desensitize(True)

    def _get_logger_with_stream(self, name: str, desensitize: bool = True):
        """创建带 StreamHandler + StringIO 的 logger，返回 (logger, stream)。"""
        # 清除已注册的 logger
        logging.getLogger(name).handlers.clear()
        logger = setup_logger(name, "INFO", desensitize=desensitize)
        stream = io.StringIO()
        # 把 handler 的 stream 替换为 StringIO
        for h in logger.handlers:
            h.stream = stream
        return logger, stream

    def test_real_logger_desensitizes_api_key(self):
        """setup_logger 后，真实 logger 输出中的 API Key 被自动脱敏。"""
        logger, stream = self._get_logger_with_stream("test_real_key_desens")
        logger.info("Using API key: sk-x8k9z1234567890abcd")
        output = stream.getvalue()
        assert "1234567890abcd" not in output
        assert "****" in output

    def test_real_logger_desensitizes_url_token(self):
        """setup_logger 后，真实 logger 输出中的 URL token 被自动脱敏。"""
        logger, stream = self._get_logger_with_stream("test_real_url_desens")
        logger.info("Calling https://api.example.com/search?token=secret123xyz")
        output = stream.getvalue()
        assert "secret123xyz" not in output
        assert "***" in output

    def test_real_logger_preserves_normal_message(self):
        """setup_logger 后，正常日志消息不被修改。"""
        logger, stream = self._get_logger_with_stream("test_real_normal")
        logger.info("Search completed with 5 results")
        output = stream.getvalue()
        assert "Search completed with 5 results" in output
        assert "***" not in output

    def test_real_logger_desensitize_false_no_filtering(self):
        """desensitize=False 时不脱敏。"""
        logger, stream = self._get_logger_with_stream("test_real_no_desens", desensitize=False)
        logger.info("Using API key: sk-x8k9z1234567890abcd")
        output = stream.getvalue()
        assert "sk-x8k9z1234567890abcd" in output

    def test_no_duplicate_filter_on_reinit(self):
        """重复 setup_logger 不重复添加 Filter。"""
        logger1 = setup_logger("test_no_dup_filter", "INFO", desensitize=True)
        filter_count_1 = sum(
            1 for f in logger1.handlers[0].filters
            if isinstance(f, DesensitizeFilter)
        ) if logger1.handlers else 0
        assert filter_count_1 == 1

        logger2 = setup_logger("test_no_dup_filter", "INFO", desensitize=True)
        assert logger1 is logger2
        filter_count_2 = sum(
            1 for f in logger2.handlers[0].filters
            if isinstance(f, DesensitizeFilter)
        ) if logger2.handlers else 0
        assert filter_count_2 == 1
