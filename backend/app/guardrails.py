"""护栏与降级工具 — 软化词表 / 敏感词检测 / 标签构造。

所有软化词表和判定规则均源自 BEAUTYPEACEAI_HARD_PROHIBITIONS_V1，
覆盖范围不得缩小，语义不得弱化。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# 真实标签三态（绝不假标）
# ──────────────────────────────────────────────────────────────────────
def meta_success(source: str = "coze", quality_score: int = 88) -> Dict[str, Any]:
    """Coze 真实生成成功时的标签元数据。"""
    return {
        "source": source,
        "confidence_label": "扣子知识库+模型生成",
        "confidence": "medium",
        "degraded": False,
        "quality_score": quality_score,
    }


def meta_fallback(quality_score: int = 60) -> Dict[str, Any]:
    """本地模板降级时的标签元数据。"""
    return {
        "source": "local_fallback",
        "confidence_label": "本地模板(降级)",
        "confidence": "low",
        "degraded": True,
        "quality_score": quality_score,
    }


def meta_guardrail_corrected(quality_score: int = 88) -> Dict[str, Any]:
    """Coze 真实生成但被后端追加合规修正时的标签元数据。"""
    return {
        "source": "coze",
        "confidence_label": "扣子知识库+模型生成(含合规修正)",
        "confidence": "medium",
        "degraded": False,
        "quality_score": quality_score,
    }


# ──────────────────────────────────────────────────────────────────────
# ID 生成
# ──────────────────────────────────────────────────────────────────────
def make_id(prefix: str) -> str:
    """生成带前缀的唯一 ID，如 content_abc123。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ──────────────────────────────────────────────────────────────────────
# content 护栏 — 医疗 / 夸大 / 绝对化 / 收益软化
# ──────────────────────────────────────────────────────────────────────
# 词表覆盖：医疗动词 + 绝对化用语 + 收益承诺（对应 HARD_PROHIBITIONS #1-4）
_CONTENT_SOFTEN_PAIRS: List[tuple] = [
    # 医疗化（#1）
    ("根治", "调理改善"), ("治愈", "改善"), ("治疗", "调理"),
    # 功效夸大 / 绝对化（#2）
    ("100%", "大多数情况"), ("百分百", "大多数情况"), ("绝对", "通常"),
    ("彻底", "明显"), ("永久", "长期"), ("特效", "明显效果"), ("立竿见影", "见效较快"),
    ("最有效", "较为有效"), ("最好的", "优质的"), ("天下第一", "领先"),
    # 收益承诺（#4）
    ("保证赚钱", "帮助经营"), ("稳赚", "有助于"), ("包回本", "辅助提升"),
]


def soften_content(text: str) -> str:
    """对 content 输出执行软化替换（医疗/夸大/绝对化/收益）。

    真实生成与降级模板均须经过此函数。
    """
    out = text or ""
    for bad, good in _CONTENT_SOFTEN_PAIRS:
        out = out.replace(bad, good)
    return out


# ──────────────────────────────────────────────────────────────────────
# private 护栏 — 不硬推 / 不贬同行 / 不紧迫逼单
# ──────────────────────────────────────────────────────────────────────
# 词表覆盖：紧迫逼单(#16) + 贬低同行(#15) + 疗效承诺(#3)
_PRIVATE_SOFTEN_PAIRS: List[tuple] = [
    # 紧迫逼单（#16）
    ("最后一个名额", "名额有限"), ("最后名额", "名额有限"),
    ("限时", "近期"), ("错过没有了", "欢迎随时了解"),
    # 贬低同行（#15）
    ("隔壁家差", "每家定位不同"), ("别家骗人", "建议综合判断"), ("同行垃圾", "每家各有特色"),
    # 疗效承诺（#3）
    ("保证治好", "帮助改善体验"), ("一定见效", "因人而异"), ("根治", "调理改善"),
]


def soften_private(text: str) -> str:
    """对 private 输出执行软化替换（不硬推/不贬同行/不紧迫逼单）。

    真实生成与降级模板均须经过此函数。
    """
    out = text or ""
    for bad, good in _PRIVATE_SOFTEN_PAIRS:
        out = out.replace(bad, good)
    return out


# ──────────────────────────────────────────────────────────────────────
# chat 护栏 — 医疗 / 敏感词追加免责（只追加一次）
# ──────────────────────────────────────────────────────────────────────
# 敏感词表（#1 医疗化关键词）
_CHAT_SENSITIVE_WORDS: List[str] = [
    "医美", "祛斑", "热玛吉", "水光", "治疗", "疼", "过敏", "睡眠",
]

_CHAT_SAFE_NOTE: str = "\n\n⚠️ 内容仅供参考，具体请遵医嘱或结合门店实际情况判断。"


def apply_chat_guardrail(message: str, answer: str) -> str:
    """医疗/敏感问题追加免责提示（只追加一次，真实/降级均生效）。

    判定逻辑：message 或 answer 中命中敏感词，且 answer 尚未含免责文本。
    """
    has_sensitive = (
        any(w in (message or "") for w in _CHAT_SENSITIVE_WORDS)
        or any(w in (answer or "") for w in _CHAT_SENSITIVE_WORDS)
    )
    if has_sensitive and _CHAT_SAFE_NOTE.strip() not in (answer or ""):
        answer = (answer or "") + _CHAT_SAFE_NOTE
    return answer
