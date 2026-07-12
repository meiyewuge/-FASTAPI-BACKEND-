"""测试 DualReviewGate — 高风险双审核门控。"""

import pytest
from search_router.dual_review import (
    DualReviewGate,
    ReviewDecision,
    ApprovalDecision,
    HIGH_RISK_CATEGORIES,
    COMMERCIAL_CLAIM_REVIEW_THRESHOLD,
    HIGH_RISK_CONFIDENCE_THRESHOLD,
    MEDICAL_TO_STORE_KEYWORDS,
)
from search_router.models.intelligence_card import IndustryIntelligenceCard


def _make_card(
    title: str = "测试标题",
    confidence: float = 0.8,
    risk: str = "normal",
    url: str = "https://example.com/test",
    summary: str = "测试摘要",
    applicable_scenario: str = "",
    suggested_action: str = "",
) -> IndustryIntelligenceCard:
    return IndustryIntelligenceCard(
        title=title,
        url=url,
        summary=summary,
        confidence_score=confidence,
        risk_category=risk,
        applicable_scenario=applicable_scenario,
        suggested_action=suggested_action,
        ingest_status="pending",
    )


class TestHighRiskCategories:
    """高风险分类常量。"""

    def test_four_high_risk(self):
        assert len(HIGH_RISK_CATEGORIES) == 4

    def test_expected_categories(self):
        expected = {"legal_policy", "efficacy_claim", "ingredient_safety", "medical_aesthetic"}
        assert HIGH_RISK_CATEGORIES == expected


class TestDualReviewTrigger:
    """双审核触发。"""

    def test_legal_policy_triggers_review(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.8, risk="legal_policy",
                          url="https://nmpa.gov.cn/notice/1")
        decision = gate.check(card)
        assert decision.needs_review is True
        assert decision.review_type == "dual"

    def test_efficacy_claim_triggers_review(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.8, risk="efficacy_claim")
        decision = gate.check(card)
        assert decision.needs_review is True
        assert decision.review_type == "dual"

    def test_ingredient_safety_triggers_review(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.8, risk="ingredient_safety")
        decision = gate.check(card)
        assert decision.needs_review is True
        assert decision.review_type == "dual"

    def test_medical_aesthetic_triggers_review(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.8, risk="medical_aesthetic")
        decision = gate.check(card)
        assert decision.needs_review is True
        assert decision.review_type == "dual"

    def test_commercial_claim_high_confidence_triggers(self):
        """commercial_claim + confidence >= 0.50 → 双审核。"""
        gate = DualReviewGate()
        card = _make_card(confidence=0.6, risk="commercial_claim")
        decision = gate.check(card)
        assert decision.needs_review is True
        assert decision.review_type == "dual"

    def test_commercial_claim_low_confidence_no_review(self):
        """commercial_claim + confidence < 0.50 → 不需双审核。"""
        gate = DualReviewGate()
        card = _make_card(confidence=0.3, risk="commercial_claim")
        decision = gate.check(card)
        assert decision.needs_review is False

    def test_normal_no_review(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.9, risk="normal")
        decision = gate.check(card)
        assert decision.needs_review is False


class TestHighRiskConfidence:
    """高风险 confidence 要求。"""

    def test_high_risk_low_confidence_rejected(self):
        """高风险 confidence < 0.70 → 拒绝。"""
        gate = DualReviewGate()
        card = _make_card(confidence=0.5, risk="efficacy_claim")
        decision = gate.check(card)
        assert decision.rejected is True
        assert "0.70" in decision.reject_reason or "0.7" in decision.reject_reason

    def test_high_risk_high_confidence_passes(self):
        """高风险 confidence >= 0.70 → 通过（需双审核但不拒绝）。"""
        gate = DualReviewGate()
        card = _make_card(confidence=0.75, risk="efficacy_claim")
        decision = gate.check(card)
        assert decision.rejected is False
        assert decision.needs_review is True


class TestMedicalAesthetic:
    """医美规则。"""

    def test_medical_store_advice_blocked(self):
        """医美转门店建议被拦截。"""
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="medical_aesthetic",
            applicable_scenario="建议用于门店运营优化",
        )
        decision = gate.check(card)
        assert decision.rejected is True
        assert decision.medical_store_advice_detected is True
        assert "门店" in decision.reject_reason or "门店建议" in decision.reject_reason

    def test_medical_store_advice_in_suggested_action(self):
        """suggested_action 中的门店建议也被检测。"""
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="medical_aesthetic",
            suggested_action="建议到店推广拓客",
        )
        decision = gate.check(card)
        assert decision.rejected is True

    def test_medical_no_store_advice_passes(self):
        """医美内容不含门店建议 → 通过。"""
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="medical_aesthetic",
            applicable_scenario="仅做趋势观察参考",
            url="https://example.com/medical",
        )
        decision = gate.check(card)
        assert decision.rejected is False

    def test_medical_keywords_list(self):
        """门店建议关键词列表完整。"""
        expected = {"门店运营", "门店建议", "生活美容门店", "到店", "拓客", "转化", "复购"}
        assert set(MEDICAL_TO_STORE_KEYWORDS) == expected


class TestLegalPolicy:
    """legal_policy 规则。"""

    def test_gov_cn_source_ok(self):
        """.gov.cn 来源通过。"""
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="legal_policy",
            url="https://nmpa.gov.cn/notice/123",
        )
        decision = gate.check(card)
        assert decision.needs_official_source is False

    def test_non_gov_source_needs_official(self):
        """非 .gov.cn 来源 needs_official_source=True。"""
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="legal_policy",
            url="https://example.com/news",
        )
        decision = gate.check(card)
        assert decision.needs_official_source is True

    def test_non_gov_source_warning(self):
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.8,
            risk="legal_policy",
            url="https://example.com/news",
        )
        decision = gate.check(card)
        assert len(decision.warnings) > 0


class TestCheckBatch:
    """批量检查。"""

    def test_check_batch(self):
        gate = DualReviewGate()
        cards = [
            _make_card(confidence=0.8, risk="normal"),
            _make_card(confidence=0.8, risk="efficacy_claim"),
            _make_card(confidence=0.5, risk="efficacy_claim"),
        ]
        decisions = gate.check_batch(cards)
        assert len(decisions) == 3
        assert decisions[0].needs_review is False
        assert decisions[1].needs_review is True
        assert decisions[2].rejected is True


class TestValidateForApproval:
    """审批验证。"""

    def test_approval_success(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.9, risk="normal")
        decision = gate.validate_for_approval(card)
        assert decision.approved is True

    def test_approval_reject_formal(self):
        """禁止 formal。"""
        gate = DualReviewGate()
        card = _make_card(confidence=0.9, risk="normal")
        card.ingest_status = "formal"
        decision = gate.validate_for_approval(card)
        assert decision.approved is False
        assert "formal" in decision.reason

    def test_approval_reject_high_risk_low_confidence(self):
        gate = DualReviewGate()
        card = _make_card(confidence=0.5, risk="efficacy_claim")
        decision = gate.validate_for_approval(card)
        assert decision.approved is False

    def test_approval_reject_medical_store_advice(self):
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.9,
            risk="medical_aesthetic",
            applicable_scenario="建议门店运营",
        )
        decision = gate.validate_for_approval(card)
        assert decision.approved is False

    def test_approval_reject_legal_non_gov(self):
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.9,
            risk="legal_policy",
            url="https://example.com/news",
        )
        decision = gate.validate_for_approval(card)
        assert decision.approved is False

    def test_approval_pass_legal_gov(self):
        gate = DualReviewGate()
        card = _make_card(
            confidence=0.9,
            risk="legal_policy",
            url="https://nmpa.gov.cn/notice/1",
        )
        decision = gate.validate_for_approval(card)
        assert decision.approved is True
