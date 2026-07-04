"""模型新增事实拦截（W3 必测项 #6）。

铁律：模型零事实产出，事实只能来自 used_materials。
模型输出若引入 used_materials 中不存在的"事实标记"（数字串/报告编号），
即视为新增事实 → 该版 blocked_new_fact，不进候选。

mock 级实现（骨架联调用）：
- 抽取输出中的数字串与编号 token；
- 任一 token 未在任何素材 content / id 中出现 → 判定为新增事实。
正式 G3 事实引用门（W4）将以更严格的规则替换本启发式。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# 数字串（≥2 位，含小数/百分比）与报告编号（字母数字混合 ≥6 位）
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?%?")
_CODE_RE = re.compile(r"[A-Za-z]{2,}\d{4,}[A-Za-z0-9\-]*")


def _material_corpus(materials: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for m in materials:
        parts.append(str(m.get("content", "")))
        parts.append(str(m.get("id", "")))
    return "\n".join(parts)


def detect_new_facts(text: str, materials: List[Dict[str, Any]]) -> List[str]:
    """返回输出中未被素材覆盖的事实 token 列表（空=无新增事实）。"""
    corpus = _material_corpus(materials)
    new_facts: List[str] = []
    for token in set(_CODE_RE.findall(text or "")):
        if token not in corpus:
            new_facts.append(token)
    for token in set(_NUMERIC_RE.findall(text or "")):
        # 单独 1 位数字噪声大，跳过；≥2 位或带 % 才判定
        if len(token.rstrip("%")) < 2:
            continue
        if token not in corpus and token.rstrip("%") not in corpus:
            new_facts.append(token)
    return sorted(new_facts)
