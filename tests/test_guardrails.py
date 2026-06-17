"""护栏与降级工具单元测试。

覆盖 BEAUTYPEACEAI_HARD_PROHIBITIONS_V1 中的可自动校验项（✅），
确保精装修未削弱护栏覆盖范围和语义。
"""
import pytest

from backend.app.guardrails import (
    apply_chat_guardrail,
    make_id,
    meta_fallback,
    meta_success,
    soften_content,
    soften_private,
    _CONTENT_SOFTEN_PAIRS,
    _PRIVATE_SOFTEN_PAIRS,
    _CHAT_SENSITIVE_WORDS,
)


# ──────────────────────────────────────────────────────────────────────
# meta 标签构造
# ──────────────────────────────────────────────────────────────────────
class TestMetaLabels:
    """验证三态标签语义，绝不假标（HARD_PROHIBITIONS #13）。"""

    def test_meta_success_is_coze(self):
        m = meta_success()
        assert m["source"] == "coze"
        assert m["confidence_label"] == "扣子知识库+模型生成"
        assert m["degraded"] is False

    def test_meta_fallback_is_local(self):
        m = meta_fallback()
        assert m["source"] == "local_fallback"
        assert m["confidence_label"] == "本地模板(降级)"
        assert m["degraded"] is True
        assert m["quality_score"] == 60

    def test_meta_labels_never_mismatched(self):
        """真实生成绝不标 degraded=True，降级绝不标 source=coze。"""
        s = meta_success()
        f = meta_fallback()
        assert not (s["degraded"] and s["source"] == "coze")  # 真实不降级
        assert not (not f["degraded"] and f["source"] == "local_fallback")  # 降级必须标 degraded


# ──────────────────────────────────────────────────────────────────────
# content 软化词表完整性
# ──────────────────────────────────────────────────────────────────────
class TestSoftenContent:
    """验证 content 护栏词表覆盖（医疗/夸大/绝对化/收益）。"""

    @pytest.mark.parametrize("bad,good", _CONTENT_SOFTEN_PAIRS)
    def test_each_pair_replaced(self, bad: str, good: str):
        result = soften_content(f"测试{bad}文案")
        assert bad not in result
        assert good in result

    def test_empty_input(self):
        assert soften_content("") == ""
        assert soften_content(None) == ""  # type: ignore

    def test_medical_terms(self):
        text = "这个方案能根治皮肤问题，治愈率百分百"
        result = soften_content(text)
        assert "根治" not in result
        assert "百分百" not in result
        assert "调理改善" in result

    def test_income_promise(self):
        text = "保证赚钱，稳赚不赔，包回本"
        result = soften_content(text)
        assert "保证赚钱" not in result
        assert "稳赚" not in result
        assert "包回本" not in result


# ──────────────────────────────────────────────────────────────────────
# private 软化词表完整性
# ──────────────────────────────────────────────────────────────────────
class TestSoftenPrivate:
    """验证 private 护栏词表覆盖（紧迫逼单/贬低同行/疗效承诺）。"""

    @pytest.mark.parametrize("bad,good", _PRIVATE_SOFTEN_PAIRS)
    def test_each_pair_replaced(self, bad: str, good: str):
        result = soften_private(f"话术{bad}内容")
        assert bad not in result
        assert good in result

    def test_urgency_pressure(self):
        text = "限时优惠，最后一个名额，错过没有了"
        result = soften_private(text)
        assert "限时" not in result
        assert "最后一个名额" not in result
        assert "错过没有了" not in result

    def test_competitor_bashing(self):
        text = "隔壁家差，别家骗人，同行垃圾"
        result = soften_private(text)
        assert "隔壁家差" not in result
        assert "别家骗人" not in result


# ──────────────────────────────────────────────────────────────────────
# chat 医疗免责追加
# ──────────────────────────────────────────────────────────────────────
class TestChatGuardrail:
    """验证 chat 敏感词免责只追加一次。"""

    @pytest.mark.parametrize("word", _CHAT_SENSITIVE_WORDS)
    def test_sensitive_word_triggers_disclaimer(self, word: str):
        answer = apply_chat_guardrail(f"关于{word}的问题", "这是一般建议")
        assert "⚠️ 内容仅供参考" in answer

    def test_no_sensitive_no_disclaimer(self):
        answer = apply_chat_guardrail("门店怎么引流", "建议做好线上内容")
        assert "⚠️ 内容仅供参考" not in answer

    def test_disclaimer_only_once(self):
        msg = "关于祛斑的问题"
        answer = "建议去专业机构"
        answer = apply_chat_guardrail(msg, answer)
        count_before = answer.count("⚠️ 内容仅供参考")
        # 再次调用不应重复追加
        answer = apply_chat_guardrail(msg, answer)
        count_after = answer.count("⚠️ 内容仅供参考")
        assert count_before == count_after == 1

    def test_empty_input(self):
        result = apply_chat_guardrail("", "")
        assert "⚠️" not in result


# ──────────────────────────────────────────────────────────────────────
# ID 生成
# ──────────────────────────────────────────────────────────────────────
class TestMakeId:
    def test_prefix(self):
        assert make_id("content").startswith("content_")
        assert make_id("msg").startswith("msg_")
        assert make_id("private").startswith("private_")

    def test_uniqueness(self):
        ids = {make_id("test") for _ in range(100)}
        assert len(ids) == 100
