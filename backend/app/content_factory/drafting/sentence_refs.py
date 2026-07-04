"""source_refs 句级溯源契约（W3 · G3 前置契约，非 G3 裁决器）。

契约（W3 施工许可 二.6）：
- 每一句关键事实必须能映射到 source_ref；
- 没有 source_ref 的事实句不得进入正文——命中即整版拒绝（blocked_unsourced_fact）。

本模块是"契约 + 结构 + 可执行校验"，不是 G3 事实引用门本身：
- 事实句识别为 mock 级启发式（数字/检测/报告/数据等标记词），供骨架联调；
- 正式 G3 裁决器（W4）将以本契约的数据结构为输入，替换启发式为正式规则；
- 溯源匹配支持两种方式：素材 ID 内嵌引用（如 [dfd_fact_001]）或素材内容片段重合。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# ── 事实句启发式标记（mock 级，W4 由 G3 正式规则替换）────────────────
_FACT_MARKERS = ["检测", "报告", "数据", "编号", "临床", "研究", "功效", "成分", "试验"]
_DIGIT_RE = re.compile(r"\d")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？；\n]+")

# 素材内容片段重合判定的最小长度
_MIN_OVERLAP_CHARS = 8


@dataclass
class SentenceRef:
    """单句溯源记录。

    is_fact=True 的句子必须有非空 source_material_ids，否则该句为
    "无源事实句"，整版稿件不得进入候选。
    """

    sentence: str
    is_fact: bool
    source_material_ids: List[str] = field(default_factory=list)

    @property
    def is_unsourced_fact(self) -> bool:
        return self.is_fact and not self.source_material_ids


@dataclass
class SentenceAudit:
    """一版稿件的句级溯源审计结果。"""

    refs: List[SentenceRef] = field(default_factory=list)
    passed: bool = True
    violations: List[str] = field(default_factory=list)   # 无源事实句原文


def split_sentences(text: str) -> List[str]:
    """按中文句读切分，去空。"""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def classify_fact(sentence: str) -> bool:
    """事实句判定（mock 级启发式）：含数字或事实标记词。"""
    if _DIGIT_RE.search(sentence):
        return True
    return any(m in sentence for m in _FACT_MARKERS)


def attach_refs(sentence: str, materials: List[Dict[str, Any]]) -> List[str]:
    """把句子映射到素材 ID。

    匹配方式（命中任一即绑定）：
    1. 素材 ID 内嵌引用：句中出现素材 id 字符串；
    2. 内容片段重合：素材 content 的连续 ≥8 字片段出现在句中。
    """
    refs: List[str] = []
    for m in materials:
        mid = str(m.get("id", ""))
        content = str(m.get("content", ""))
        if mid and mid in sentence:
            refs.append(mid)
            continue
        if content and _overlaps(sentence, content):
            refs.append(mid)
    return refs


def _overlaps(sentence: str, content: str) -> bool:
    """素材内容是否与句子有 ≥_MIN_OVERLAP_CHARS 连续字符重合（滑窗）。"""
    if len(content) < _MIN_OVERLAP_CHARS:
        return bool(content and content in sentence)
    for i in range(len(content) - _MIN_OVERLAP_CHARS + 1):
        if content[i : i + _MIN_OVERLAP_CHARS] in sentence:
            return True
    return False


def audit_sentences(text: str, materials: List[Dict[str, Any]]) -> SentenceAudit:
    """执行句级溯源审计。

    任何 is_fact=True 且无 source_material_ids 的句子 → violations，
    audit.passed=False，整版稿件不得进入候选（调用方负责拦截）。
    """
    audit = SentenceAudit()
    for s in split_sentences(text):
        ref = SentenceRef(
            sentence=s,
            is_fact=classify_fact(s),
            source_material_ids=attach_refs(s, materials),
        )
        audit.refs.append(ref)
        if ref.is_unsourced_fact:
            audit.violations.append(s)
    audit.passed = not audit.violations
    return audit
