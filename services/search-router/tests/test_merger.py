"""测试 ResultMerger — 跨 Provider 4 层去重合并。"""

import pytest
from search_router.merger import (
    ResultMerger,
    MergeResult,
    _normalize_url,
    _text_2grams,
    _jaccard_similarity,
    _content_fingerprint,
    _source_rank,
    _get_merged_from,
)
from search_router.models.search_response import SearchResult


def _make_result(
    title: str = "测试标题",
    url: str = "https://example.com/test",
    summary: str = "测试摘要",
    provider: str = "mock",
    confidence: float = 0.5,
) -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        title=title,
        url=url,
        summary=summary,
        provider=provider,
        confidence_score=confidence,
    )


class TestUrlNormalize:
    """URL 规范化。"""

    def test_strip_query(self):
        assert _normalize_url("https://example.com/path?q=1") == "example.com/path"

    def test_strip_fragment(self):
        assert _normalize_url("https://example.com/path#section") == "example.com/path"

    def test_strip_trailing_slash(self):
        assert _normalize_url("https://example.com/path/") == "example.com/path"

    def test_strip_protocol(self):
        assert _normalize_url("https://example.com/path") == "example.com/path"
        assert _normalize_url("http://example.com/path") == "example.com/path"

    def test_empty_url(self):
        assert _normalize_url("") == ""


class TestJaccardSimilarity:
    """标题相似度 Jaccard。"""

    def test_identical_titles(self):
        sim = _jaccard_similarity("美业数字化转型趋势", "美业数字化转型趋势")
        assert sim == 1.0

    def test_similar_titles(self):
        sim = _jaccard_similarity("美业数字化转型趋势报告", "美业数字化转型趋势报告分析")
        assert sim > 0.8

    def test_different_titles(self):
        sim = _jaccard_similarity("美业数字化转型趋势", "化妆品成分安全检测标准")
        assert sim < 0.3

    def test_empty_text(self):
        assert _jaccard_similarity("", "测试") == 0.0
        assert _jaccard_similarity("测试", "") == 0.0


class TestContentFingerprint:
    """内容指纹 MD5。"""

    def test_same_content_same_fp(self):
        assert _content_fingerprint("这是一段测试内容") == _content_fingerprint("这是一段测试内容")

    def test_different_content_diff_fp(self):
        assert _content_fingerprint("内容A") != _content_fingerprint("内容B")

    def test_empty_content(self):
        assert _content_fingerprint("") == ""

    def test_long_content_truncated(self):
        """Fix 5: SHA256 of full content — changes after 500 chars ARE detected."""
        long_a = "A" * 600 + "B" * 100
        long_b = "A" * 600 + "C" * 100
        assert _content_fingerprint(long_a) != _content_fingerprint(long_b)


class TestUrlExactDedup:
    """层 1: URL 精确去重。"""

    def test_same_url_dedup(self):
        """相同 URL 去重，保留高 confidence。"""
        r1 = _make_result(url="https://example.com/a", confidence=0.3, provider="mock")
        r2 = _make_result(url="https://example.com/a", confidence=0.8, provider="bocha")
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1
        assert result.results[0].confidence_score == 0.8

    def test_different_url_no_dedup(self):
        """不同 URL + 不同标题 + 不同摘要 不去重。"""
        r1 = _make_result(
            title="美业数字化转型趋势",
            url="https://example.com/a",
            summary="美业数字化转型加速",
        )
        r2 = _make_result(
            title="化妆品成分安全检测标准",
            url="https://example.com/b",
            summary="成分安全检测规范更新",
        )
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 2
        assert result.merged_count == 0


class TestUrlNormalizedDedup:
    """层 2: URL 规范化去重。"""

    def test_query_stripped_dedup(self):
        """去 query 后相同 URL 去重。"""
        r1 = _make_result(url="https://example.com/path?q=1", confidence=0.3, provider="mock")
        r2 = _make_result(url="https://example.com/path?q=2", confidence=0.8, provider="bocha")
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1

    def test_protocol_stripped_dedup(self):
        """去协议后相同 URL 去重。"""
        r1 = _make_result(url="http://example.com/path", confidence=0.3, provider="mock")
        r2 = _make_result(url="https://example.com/path", confidence=0.8, provider="bocha")
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1

    def test_trailing_slash_dedup(self):
        """去 trailing slash 后相同 URL 去重。"""
        r1 = _make_result(url="https://example.com/path/", confidence=0.3, provider="mock")
        r2 = _make_result(url="https://example.com/path", confidence=0.8, provider="bocha")
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1


class TestTitleJaccardDedup:
    """层 3: 标题相似度去重。"""

    def test_high_similarity_dedup(self):
        """标题 Jaccard > 0.8 去重。"""
        r1 = _make_result(
            title="美业数字化转型趋势报告",
            url="https://example.com/a",
            confidence=0.3, provider="mock",
            summary="摘要A",
        )
        r2 = _make_result(
            title="美业数字化转型趋势报告分析",
            url="https://example.com/b",
            confidence=0.8, provider="bocha",
            summary="摘要B",
        )
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1

    def test_low_similarity_no_dedup(self):
        """标题 Jaccard < 0.8 + 不同内容 不去重。"""
        r1 = _make_result(
            title="美业数字化转型趋势",
            url="https://example.com/a",
            summary="美业数字化转型加速，AI驱动门店升级",
        )
        r2 = _make_result(
            title="化妆品成分安全检测标准",
            url="https://example.com/b",
            summary="成分安全检测规范更新，新增指标",
        )
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 2


class TestContentFingerprintDedup:
    """层 4: 内容指纹去重。"""

    def test_same_content_dedup(self):
        """前 500 字相同去重。"""
        r1 = _make_result(
            url="https://example.com/a",
            summary="这是一段相同的测试内容用于验证内容指纹去重",
            confidence=0.3, provider="mock",
        )
        r2 = _make_result(
            url="https://example.com/b",
            summary="这是一段相同的测试内容用于验证内容指纹去重",
            confidence=0.8, provider="bocha",
        )
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        assert result.merged_count == 1


class TestMergedFromTracking:
    """merged_from 信息追踪。"""

    def test_merged_from_recorded(self):
        """去重后 merged_from 记录被丢弃的 provider。"""
        r1 = _make_result(url="https://example.com/a", provider="mock", confidence=0.3)
        r2 = _make_result(url="https://example.com/a", provider="bocha", confidence=0.8)
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert len(result.results) == 1
        merged_from = result.results[0].raw.get("merged_from", [])
        assert "mock" in merged_from

    def test_no_merged_from_for_new(self):
        """新结果没有 merged_from。"""
        r = _make_result(url="https://example.com/a")
        merger = ResultMerger()
        result = merger.merge([r])
        assert result.results[0].raw.get("merged_from", []) == []


class TestSourceRankAndConfidence:
    """信源等级 + confidence 保留策略。"""

    def test_higher_rank_replaces(self):
        """高信源等级替换低信源等级。"""
        r1 = _make_result(url="https://example.com/a", provider="mock", confidence=0.9)
        r2 = _make_result(url="https://example.com/a", provider="bocha", confidence=0.1)
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert result.results[0].provider == "bocha"

    def test_same_rank_higher_confidence_replaces(self):
        """同等级时高 confidence 替换。"""
        r1 = _make_result(url="https://example.com/a", provider="mock", confidence=0.3)
        r2 = _make_result(url="https://example.com/a", provider="mock", confidence=0.8)
        merger = ResultMerger()
        result = merger.merge([r1, r2])
        assert result.results[0].confidence_score == 0.8


class TestEmptyInput:
    """空输入。"""

    def test_empty_list(self):
        merger = ResultMerger()
        result = merger.merge([])
        assert result.results == []
        assert result.merged_count == 0
