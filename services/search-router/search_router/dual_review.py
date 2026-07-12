"""DualReviewGate — 高风险双审核门控。

高风险分类一律双审核:
    legal_policy
    efficacy_claim
    ingredient_safety
    medical_aesthetic

另外:
    commercial_claim + confidence_score >= 0.50 → 需要双审核

高风险要求:
    confidence_score >= 0.70

medical_aesthetic 规则:
    禁止转门店建议
    检测关键词: 门店运营 / 门店建议 / 生活美容门店 / 到店 / 拓客 / 转化 / 复购

legal_policy 规则:
    必须优先要求官方来源
    .gov.cn 通过
    非官方来源需要 needs_official_source=True 或 reject_reason
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from search_router.industry.industry_mapper import is_legal_policy_official_source
from search_router.industry.risk_classifier import needs_high_standard_review
from search_router.models.intelligence_card import IndustryIntelligenceCard


# 高风险分类（一律双审核）
HIGH_RISK_CATEGORIES = {
    "legal_policy",
    "efficacy_claim",
    "ingredient_safety",
    "medical_aesthetic",
}

# commercial_claim 需双审核的 confidence 阈值
COMMERCIAL_CLAIM_REVIEW_THRESHOLD = 0.50

# 高风险 confidence 要求
HIGH_RISK_CONFIDENCE_THRESHOLD = 0.70

# 医美转门店关键词
MEDICAL_TO_STORE_KEYWORDS = [
    "门店运营",
    "门店建议",
    "生活美容门店",
    "到店",
    "拓客",
    "转化",
    "复购",
]


@dataclass
class ReviewDecision:
    """审核决策。"""
    needs_review: bool = False
    review_type: str = "none"  # "none" / "dual" / "standard"
    risk_category: str = ""
    confidence_score: float = 0.0
    rejected: bool = False
    reject_reason: str = ""
    needs_official_source: bool = False
    medical_store_advice_detected: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "needs_review": self.needs_review,
            "review_type": self.review_type,
            "risk_category": self.risk_category,
            "confidence_score": round(self.confidence_score, 3),
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "needs_official_source": self.needs_official_source,
            "medical_store_advice_detected": self.medical_store_advice_detected,
            "warnings": list(self.warnings),
        }


@dataclass
class ApprovalDecision:
    """审批决策。"""
    approved: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


class DualReviewGate:
    """高风险双审核门控。"""

    def check(self, card: IndustryIntelligenceCard) -> ReviewDecision:
        """检查单条 card 是否需要双审核。

        规则:
            1. 高风险分类 → 双审核
            2. commercial_claim + confidence >= 0.50 → 双审核
            3. 高风险 confidence < 0.70 → 拒绝或标记
            4. medical_aesthetic 转门店建议 → 拦截
            5. legal_policy 非官方来源 → needs_official_source=True
        """
        risk = card.risk_category
        confidence = card.confidence_score
        warnings: list[str] = []
        rejected = False
        reject_reason = ""
        needs_official_source = False
        medical_store_advice_detected = False
        needs_review = False
        review_type = "none"

        # 检查医美转门店建议
        if risk == "medical_aesthetic":
            text = f"{card.title} {card.summary} {card.applicable_scenario} {card.suggested_action}"
            for kw in MEDICAL_TO_STORE_KEYWORDS:
                if kw in text:
                    medical_store_advice_detected = True
                    warnings.append(f"医美内容检测到门店建议关键词: '{kw}'")
                    rejected = True
                    reject_reason = "医美内容禁止自动转为生活美容门店建议"
                    break

        # legal_policy 官方来源检查
        if risk == "legal_policy":
            if not is_legal_policy_official_source(card.url):
                needs_official_source = True
                warnings.append("法规政策类内容应优先引用官方来源（.gov.cn），当前来源非官方")

        # 高风险分类 → 双审核
        if risk in HIGH_RISK_CATEGORIES:
            needs_review = True
            review_type = "dual"
            # 高风险 confidence 要求
            if confidence < HIGH_RISK_CONFIDENCE_THRESHOLD and not rejected:
                rejected = True
                reject_reason = (
                    f"高风险分类 {risk} 要求 confidence_score >= {HIGH_RISK_CONFIDENCE_THRESHOLD}，"
                    f"当前 {confidence}"
                )

        # commercial_claim + confidence >= 0.50 → 双审核
        if risk == "commercial_claim" and confidence >= COMMERCIAL_CLAIM_REVIEW_THRESHOLD:
            needs_review = True
            review_type = "dual"

        return ReviewDecision(
            needs_review=needs_review,
            review_type=review_type,
            risk_category=risk,
            confidence_score=confidence,
            rejected=rejected,
            reject_reason=reject_reason,
            needs_official_source=needs_official_source,
            medical_store_advice_detected=medical_store_advice_detected,
            warnings=warnings,
        )

    def check_batch(
        self, cards: list[IndustryIntelligenceCard]
    ) -> list[ReviewDecision]:
        """批量检查。"""
        return [self.check(card) for card in cards]

    def validate_for_approval(self, card: IndustryIntelligenceCard) -> ApprovalDecision:
        """审批前验证。

        检查:
            1. ingest_status 不是 formal
            2. 高风险 confidence >= 0.70
            3. 医美无门店建议
            4. legal_policy 官方来源（或已标注 needs_official_source）
            5. 必填字段不空
        """
        warnings: list[str] = []

        # 禁止 formal
        if card.ingest_status == "formal":
            return ApprovalDecision(
                approved=False,
                reason="ingest_status 禁止为 formal",
                warnings=["ingest_status=formal 被禁止"],
            )

        # 必填字段
        if not card.title:
            warnings.append("title 为空")
        if not card.url:
            warnings.append("url 为空")

        risk = card.risk_category
        confidence = card.confidence_score

        # 高风险 confidence 检查
        if risk in HIGH_RISK_CATEGORIES:
            if confidence < HIGH_RISK_CONFIDENCE_THRESHOLD:
                return ApprovalDecision(
                    approved=False,
                    reason=f"高风险分类 {risk} 要求 confidence >= {HIGH_RISK_CONFIDENCE_THRESHOLD}",
                    warnings=warnings,
                )

        # 医美转门店检查
        if risk == "medical_aesthetic":
            text = f"{card.title} {card.summary} {card.applicable_scenario} {card.suggested_action}"
            for kw in MEDICAL_TO_STORE_KEYWORDS:
                if kw in text:
                    return ApprovalDecision(
                        approved=False,
                        reason=f"医美内容检测到门店建议关键词: '{kw}'",
                        warnings=warnings,
                    )

        # legal_policy 官方来源检查
        if risk == "legal_policy":
            if not is_legal_policy_official_source(card.url):
                return ApprovalDecision(
                    approved=False,
                    reason="法规政策类内容需要官方来源（.gov.cn）",
                    warnings=warnings,
                )

        if warnings:
            return ApprovalDecision(
                approved=True,
                reason="通过验证（有警告）",
                warnings=warnings,
            )

        return ApprovalDecision(
            approved=True,
            reason="通过验证",
            warnings=[],
        )
