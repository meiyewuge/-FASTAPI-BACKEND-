"""W3 草稿生成子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W3 条件施工许可。

本子包为纯库层：
- 只用注入的 model_router.ModelRouter（mock clients），不接真实模型/真实 9080；
- 不进 W4、不实现 G1-G6 正式裁决器；
- draft_candidate 停在候选态，publish_allowed / writes_approved 为无写入口常量 False。

模块：
- sentence_refs.py：句级溯源契约（G3 前置，非裁决器）
- new_fact_guard.py：模型新增事实拦截
- schemas.py：DraftCandidate / DraftVersion / 三版稿枚举
- generator.py：DraftGenerator（接线 model_router，产出三版稿）
"""
from .schemas import (
    DraftCandidate,
    DraftCandidateStatus,
    DraftVersion,
    DraftVersionKind,
    DraftVersionStatus,
)
from .sentence_refs import (
    SentenceAudit,
    SentenceRef,
    audit_sentences,
    classify_fact,
    split_sentences,
)
from .new_fact_guard import detect_new_facts
from .generator import DraftGenerator

__all__ = [
    "DraftCandidate",
    "DraftCandidateStatus",
    "DraftGenerator",
    "DraftVersion",
    "DraftVersionKind",
    "DraftVersionStatus",
    "SentenceAudit",
    "SentenceRef",
    "audit_sentences",
    "classify_fact",
    "detect_new_facts",
    "split_sentences",
]
