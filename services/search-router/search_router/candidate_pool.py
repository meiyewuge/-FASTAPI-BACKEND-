"""CandidatePool — 三池分流 + 候选池管理。

三池:
    pending_review — 待审核（默认）
    observing — 观察池
    discarded — 丢弃池

分流规则:
    confidence_score < 0.30 → discarded
    命中拉黑数据 → discarded
    confidence_score < 0.50 且重复/merged → observing
    其他 → pending_review

铁律:
    pool_name 是 pending_review（不是 ingest_status）
    ingest_status 仍然必须是 pending
    禁止 formal

合法 ingest_status: pending / review / approved / rejected / observing / discarded
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from search_router.models.intelligence_card import IndustryIntelligenceCard


# ── 池名称 ────────────────────────────────────────────

POOL_PENDING_REVIEW = "pending_review"
POOL_OBSERVING = "observing"
POOL_DISCARDED = "discarded"

VALID_POOL_NAMES = {POOL_PENDING_REVIEW, POOL_OBSERVING, POOL_DISCARDED}

# 合法 ingest_status（formal 禁止）
VALID_INGEST_STATUSES = {"pending", "review", "approved", "rejected", "observing", "discarded"}
FORBIDDEN_INGEST_STATUS = "formal"

# 阈值
CONFIDENCE_DISCARD_THRESHOLD = 0.30
CONFIDENCE_OBSERVE_THRESHOLD = 0.50

# 拉黑词
BLACKLIST_TERMS: list[str] = [
    "37.8%",
    "30 多万家",
    "30多万家",
    "45%死卡率",
    "45% 死卡率",
    "67%转化率",
    "67% 转化率",
    "倒闭率 37.8%",
    "关店率 45%",
]

# 医美转门店关键词
MEDICAL_TO_STORE_KEYWORDS: list[str] = [
    "门店运营",
    "门店建议",
    "生活美容门店",
    "到店",
    "拓客",
    "转化",
    "复购",
]


def _check_blacklist(card: IndustryIntelligenceCard) -> bool:
    """检查是否命中拉黑词。"""
    text = f"{card.title} {card.summary} {card.evidence_excerpt}"
    for term in BLACKLIST_TERMS:
        if term in text:
            return True
    return False


def _check_merged_from(card: IndustryIntelligenceCard) -> bool:
    """检查是否来自 merged 结果。"""
    merged_from = card.provider_metadata.get("merged_from", [])
    return len(merged_from) > 0


@dataclass
class PoolDecision:
    """池分流决策。"""
    pool_name: str = POOL_PENDING_REVIEW
    reason: str = ""
    ingest_status: str = "pending"
    blacklisted: bool = False

    def to_dict(self) -> dict:
        return {
            "pool_name": self.pool_name,
            "reason": self.reason,
            "ingest_status": self.ingest_status,
            "blacklisted": self.blacklisted,
        }


class CandidatePool:
    """候选池管理器。

    route_card(card) → PoolDecision
    route_batch(cards) → list[PoolDecision]
    cleanup_old_pending(days=30) → 内存过滤骨架（不写生产 DB）
    """

    def __init__(self) -> None:
        self._pending_review: list[IndustryIntelligenceCard] = []
        self._observing: list[IndustryIntelligenceCard] = []
        self._discarded: list[IndustryIntelligenceCard] = []

    @property
    def pending_review(self) -> list[IndustryIntelligenceCard]:
        return list(self._pending_review)

    @property
    def observing(self) -> list[IndustryIntelligenceCard]:
        return list(self._observing)

    @property
    def discarded(self) -> list[IndustryIntelligenceCard]:
        return list(self._discarded)

    def route_card(self, card: IndustryIntelligenceCard) -> PoolDecision:
        """对单条 card 做池分流决策。

        规则:
            1. 命中拉黑 → discarded
            2. confidence < 0.30 → discarded
            3. confidence < 0.50 且 merged → observing
            4. 其他 → pending_review
        """
        # 检查拉黑
        if _check_blacklist(card):
            decision = PoolDecision(
                pool_name=POOL_DISCARDED,
                reason="命中拉黑词",
                ingest_status="discarded",
                blacklisted=True,
            )
            self._discarded.append(card)
            card.ingest_status = "discarded"
            card.ingest_reason = "命中拉黑词，自动丢弃"
            return decision

        # confidence < 0.30 → discarded
        if card.confidence_score < CONFIDENCE_DISCARD_THRESHOLD:
            decision = PoolDecision(
                pool_name=POOL_DISCARDED,
                reason=f"confidence_score={card.confidence_score} < {CONFIDENCE_DISCARD_THRESHOLD}",
                ingest_status="discarded",
            )
            self._discarded.append(card)
            card.ingest_status = "discarded"
            card.ingest_reason = f"置信度过低 ({card.confidence_score})，自动丢弃"
            return decision

        # confidence < 0.50 且 merged → observing
        if card.confidence_score < CONFIDENCE_OBSERVE_THRESHOLD and _check_merged_from(card):
            decision = PoolDecision(
                pool_name=POOL_OBSERVING,
                reason=f"confidence_score={card.confidence_score} < {CONFIDENCE_OBSERVE_THRESHOLD} 且来自 merged 结果",
                ingest_status="observing",
            )
            self._observing.append(card)
            card.ingest_status = "observing"
            card.ingest_reason = "置信度偏低且来自合并结果，放入观察池"
            return decision

        # 默认 → pending_review
        decision = PoolDecision(
            pool_name=POOL_PENDING_REVIEW,
            reason="通过基础筛选，进入待审核池",
            ingest_status="pending",
        )
        self._pending_review.append(card)
        # ingest_status 保持 pending
        if card.ingest_status not in VALID_INGEST_STATUSES or card.ingest_status == FORBIDDEN_INGEST_STATUS:
            card.ingest_status = "pending"
        if not card.ingest_reason:
            card.ingest_reason = "外部搜索结果默认进入待审候选池"
        return decision

    def route_batch(
        self, cards: list[IndustryIntelligenceCard]
    ) -> list[PoolDecision]:
        """批量池分流。"""
        return [self.route_card(card) for card in cards]

    def cleanup_old_pending(self, days: int = 30) -> list[IndustryIntelligenceCard]:
        """清理超时 pending_review 项（内存过滤骨架）。

        将 fetched_at 超过 days 天的 pending_review 项移到 observing。
        不写生产 DB。
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        threshold = now.timestamp() - (days * 86400)
        kept: list[IndustryIntelligenceCard] = []
        moved: list[IndustryIntelligenceCard] = []
        for card in self._pending_review:
            try:
                fetched = datetime.fromisoformat(card.fetched_at) if card.fetched_at else now
                if fetched.timestamp() < threshold:
                    card.ingest_status = "observing"
                    card.ingest_reason = f"超过 {days} 天未审核，移入观察池"
                    self._observing.append(card)
                    moved.append(card)
                else:
                    kept.append(card)
            except (ValueError, TypeError):
                kept.append(card)
        self._pending_review = kept
        return moved

    def pool_stats(self) -> dict[str, int]:
        """各池数量统计。"""
        return {
            POOL_PENDING_REVIEW: len(self._pending_review),
            POOL_OBSERVING: len(self._observing),
            POOL_DISCARDED: len(self._discarded),
        }
