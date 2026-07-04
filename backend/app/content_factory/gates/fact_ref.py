"""G3 事实引用门 — 正式裁决接口（W4）。

设计依据：M1-W4 条件施工许可 三·G3 + 严禁 12。

关键纪律（许可明文）：
- W3 的启发式句级溯源（drafting.sentence_refs）**不得直接当正式 G3**；
- W4 必须建立"正式 G3 裁决接口"——本模块即该接口。

结构：
- FactRefAdjudicator：Protocol，正式 G3 裁决契约（真实规则实现它即可注入）；
- MockG3Adjudicator：骨架期默认实现，判两件事：
    (a) 句级溯源：每个事实句必须有 source_ref（W3 审计作为**输入信号之一**，
        经本正式接口封装，而非被当作 G3 本体）；
    (b) 检测数据完整性：凡做检测/数据宣称，必须齐备 体外法 + 报告编号 + 检测机构。

真实 G3（法规级）替换 MockG3Adjudicator 即可，pipeline 注入点不变。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from backend.app.content_factory.drafting.sentence_refs import audit_sentences

from .schemas import GateName, GateResult, GateVerdict

# 检测/数据宣称触发词
_DETECTION_CLAIM_MARKERS = ["检测", "检验", "测试", "试验", "临床", "功效评价"]
# 检测完整性三要素
_METHOD_MARKERS = ["体外", "人体", "斑贴", "半体内"]         # 检测方法
_CODE_RE = re.compile(r"[A-Za-z]{2,}\d{4,}[A-Za-z0-9\-]*|编号")  # 报告编号
_ORG_MARKERS = ["机构", "有限公司", "检验检测", "实验室", "研究院"]  # 检测机构


class FactRefAdjudicator(Protocol):
    """正式 G3 裁决契约。真实规则实现本 Protocol 后注入 pipeline。"""

    def adjudicate(self, text: str, materials: List[Dict[str, Any]]) -> GateResult:
        ...


@dataclass
class MockG3Adjudicator:
    """骨架期 G3 裁决实现（可被正式规则替换）。

    判定顺序：
    1. 无源事实句 → FAIL（句级溯源）
    2. 有检测/数据宣称但三要素不全 → FAIL（检测完整性）
    3. 皆过 → PASS
    """

    def adjudicate(self, text: str, materials: List[Dict[str, Any]]) -> GateResult:
        t = text or ""

        # (a) 句级溯源：W3 审计作为输入信号，封装在正式接口之内
        audit = audit_sentences(t, materials)
        if not audit.passed:
            return GateResult(
                gate=GateName.G3_FACT_REF,
                verdict=GateVerdict.FAIL,
                hits=list(audit.violations),
                note="无 source_ref 的事实句不得进入正文",
            )

        # (b) 检测数据完整性
        if any(m in t for m in _DETECTION_CLAIM_MARKERS):
            missing: List[str] = []
            if not any(m in t for m in _METHOD_MARKERS):
                missing.append("检测方法(体外/人体)")
            if not _CODE_RE.search(t):
                missing.append("报告编号")
            if not any(m in t for m in _ORG_MARKERS):
                missing.append("检测机构")
            if missing:
                return GateResult(
                    gate=GateName.G3_FACT_REF,
                    verdict=GateVerdict.FAIL,
                    hits=missing,
                    note="检测/数据宣称缺要素：" + "、".join(missing),
                )

        return GateResult(gate=GateName.G3_FACT_REF, verdict=GateVerdict.PASS)
