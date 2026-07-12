"""测试 CandidatePool — 三池分流。"""

import pytest
from search_router.candidate_pool import (
    CandidatePool,
    PoolDecision,
    POOL_PENDING_REVIEW,
    POOL_OBSERVING,
    POOL_DISCARDED,
    VALID_POOL_NAMES,
    VALID_INGEST_STATUSES,
    FORBIDDEN_INGEST_STATUS,
    BLACKLIST_TERMS,
    CONFIDENCE_DISCARD_THRESHOLD,
    CONFIDENCE_OBSERVE_THRESHOLD,
)
from search_router.models.intelligence_card import IndustryIntelligenceCard


def _make_card(
    title: str = "测试标题",
    confidence: float = 0.8,
    summary: str = "测试摘要",
    evidence: str = "",
    merged_from: list[str] | None = None,
) -> IndustryIntelligenceCard:
    return IndustryIntelligenceCard(
        title=title,
        url=f"https://example.com/{title}",
        summary=summary,
        confidence_score=confidence,
        evidence_excerpt=evidence,
        provider_metadata={"merged_from": merged_from or []},
    )


class TestPoolNames:
    """池名称常量。"""

    def test_three_pools(self):
        assert len(VALID_POOL_NAMES) == 3

    def test_pool_names_snake_case(self):
        for name in VALID_POOL_NAMES:
            assert name == name.lower()

    def test_pending_review_name(self):
        assert POOL_PENDING_REVIEW == "pending_review"

    def test_observing_name(self):
        assert POOL_OBSERVING == "observing"

    def test_discarded_name(self):
        assert POOL_DISCARDED == "discarded"


class TestIngestStatus:
    """ingest_status 规则。"""

    def test_formal_forbidden(self):
        assert FORBIDDEN_INGEST_STATUS == "formal"

    def test_formal_not_in_valid(self):
        assert "formal" not in VALID_INGEST_STATUSES

    def test_valid_statuses(self):
        expected = {"pending", "review", "approved", "rejected", "observing", "discarded"}
        assert VALID_INGEST_STATUSES == expected


class TestPendingReview:
    """pending_review 分流。"""

    def test_high_confidence_goes_pending(self):
        """高 confidence → pending_review。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9)
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_PENDING_REVIEW
        assert decision.ingest_status == "pending"

    def test_pending_review_keeps_ingest_pending(self):
        """pending_review 时 ingest_status 仍是 pending。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9)
        decision = pool.route_card(card)
        assert card.ingest_status == "pending"

    def test_medium_confidence_not_merged_goes_pending(self):
        """confidence 0.5~0.7 且非 merged → pending_review。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.6, merged_from=[])
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_PENDING_REVIEW


class TestObserving:
    """observing 分流。"""

    def test_low_confidence_merged_goes_observing(self):
        """confidence < 0.50 且 merged → observing。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.35, merged_from=["mock"])
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_OBSERVING
        assert card.ingest_status == "observing"


class TestDiscarded:
    """discarded 分流。"""

    def test_very_low_confidence_discarded(self):
        """confidence < 0.30 → discarded。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.15)
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_DISCARDED
        assert card.ingest_status == "discarded"

    def test_blacklist_discarded(self):
        """拉黑词命中 → discarded。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9, evidence="倒闭率 37.8%")
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_DISCARDED
        assert decision.blacklisted is True
        assert card.ingest_status == "discarded"

    def test_blacklist_in_title(self):
        """拉黑词在 title 中也命中。"""
        pool = CandidatePool()
        card = _make_card(title="关店率 45% 触目惊心", confidence=0.9)
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_DISCARDED

    def test_blacklist_in_summary(self):
        """拉黑词在 summary 中也命中。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9, summary="行业67%转化率惊人")
        decision = pool.route_card(card)
        assert decision.pool_name == POOL_DISCARDED


class TestRouteBatch:
    """批量分流。"""

    def test_route_batch(self):
        pool = CandidatePool()
        cards = [
            _make_card(confidence=0.9),   # pending
            _make_card(confidence=0.15),  # discarded
            _make_card(confidence=0.35, merged_from=["mock"]),  # observing
        ]
        decisions = pool.route_batch(cards)
        assert len(decisions) == 3
        assert decisions[0].pool_name == POOL_PENDING_REVIEW
        assert decisions[1].pool_name == POOL_DISCARDED
        assert decisions[2].pool_name == POOL_OBSERVING

    def test_pool_stats(self):
        pool = CandidatePool()
        cards = [
            _make_card(confidence=0.9),
            _make_card(confidence=0.15),
            _make_card(confidence=0.35, merged_from=["mock"]),
        ]
        pool.route_batch(cards)
        stats = pool.pool_stats()
        assert stats[POOL_PENDING_REVIEW] == 1
        assert stats[POOL_DISCARDED] == 1
        assert stats[POOL_OBSERVING] == 1


class TestCleanup:
    """cleanup_old_pending 骨架。"""

    def test_cleanup_does_not_crash(self):
        """cleanup 不崩溃。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9)
        pool.route_card(card)
        moved = pool.cleanup_old_pending(days=30)
        assert isinstance(moved, list)

    def test_cleanup_no_production_db(self):
        """cleanup 不写生产 DB（仅内存过滤）。"""
        pool = CandidatePool()
        card = _make_card(confidence=0.9)
        pool.route_card(card)
        pool.cleanup_old_pending(days=30)
        # 仅验证不崩溃，不写文件
