"""used_materials 绑定 + 缺料报告。

设计依据：M1 W2 9080 只读召回适配。

职责：
- 将召回素材绑定到 Brief，生成 used_materials 列表；
- 素材不足时生成缺料报告（桥接 model_router.MissingMaterialReport）；
- 素材充分性判定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.model_router.schemas import MissingMaterialReport, TaskType

from ..schemas import Brief
from .results import RecallResult, RecallStatus
from .source_refs import SourceRef


@dataclass
class BoundMaterials:
    """召回素材绑定结果。"""

    materials: List[Dict[str, Any]] = field(default_factory=list)
    source_refs: List[SourceRef] = field(default_factory=list)
    is_sufficient: bool = True
    missing_report: Optional[MissingMaterialReport] = None

    @property
    def material_ids(self) -> List[str]:
        return [str(m.get("id", "")) for m in self.materials if m.get("id")]


# ── 任务类型 → 最低素材数量要求（草案值，M1 施工校准）──────────────────
_MIN_MATERIALS_REQUIRED: Dict[TaskType, int] = {
    TaskType.FACT_STRICT: 1,
    TaskType.STATE_AESTHETIC: 1,
    TaskType.PLATFORM_REWRITE: 1,
    TaskType.HIGH_RISK: 2,       # 高风险需要更多素材支撑
    TaskType.IP_OPINION: 1,
    TaskType.LONG_EXPANSION: 1,
}

# ── 任务类型 → 缺失素材类型提示（与 model_router 对齐）───────────────
_MISSING_TYPE_HINTS: Dict[TaskType, List[str]] = {
    TaskType.FACT_STRICT: ["事实卡", "检测摘要"],
    TaskType.STATE_AESTHETIC: ["事实卡", "引擎允许词表"],
    TaskType.PLATFORM_REWRITE: ["事实卡", "平台工艺卡素材"],
    TaskType.HIGH_RISK: ["事实卡", "合规依据"],
    TaskType.IP_OPINION: ["观点素材", "金句素材"],
    TaskType.LONG_EXPANSION: ["事实卡", "已审草稿"],
}


def bind_materials(
    recall_result: RecallResult,
    brief: Brief,
) -> BoundMaterials:
    """将召回结果绑定到 Brief，生成 used_materials。

    判定素材充分性：
    - 召回状态为 MISSING 或素材数量不足 → is_sufficient=False，生成缺料报告
    - 召回状态为 BLOCKED → is_sufficient=False，缺料报告标注拦截原因
    - 素材充分 → is_sufficient=True，正常返回
    """
    materials = recall_result.materials
    source_refs = [
        sr for sr in recall_result.source_refs if isinstance(sr, SourceRef)
    ]
    min_required = _MIN_MATERIALS_REQUIRED.get(brief.task_type, 1)

    # 拦截判定（优先于缺料判定）
    if recall_result.status == RecallStatus.BLOCKED:
        report = MissingMaterialReport(
            content_id=f"pending_{brief.brief_id}",
            task_type=brief.task_type,
            missing_material_types=["素材被合规规则拦截，请检查 Brief 内容"],
            suggested_recall_keywords=brief.raw_text.split()[:5] or [brief.raw_text[:20]],
        )
        return BoundMaterials(
            materials=[],
            source_refs=[],
            is_sufficient=False,
            missing_report=report,
        )

    # 缺料判定
    if recall_result.status == RecallStatus.MISSING or len(materials) < min_required:
        report = MissingMaterialReport(
            content_id=f"pending_{brief.brief_id}",
            task_type=brief.task_type,
            missing_material_types=_MISSING_TYPE_HINTS.get(brief.task_type, ["事实卡"]),
            suggested_recall_keywords=brief.raw_text.split()[:5] or [brief.raw_text[:20]],
        )
        return BoundMaterials(
            materials=materials,
            source_refs=source_refs,
            is_sufficient=False,
            missing_report=report,
        )

    # 素材充分
    return BoundMaterials(
        materials=materials,
        source_refs=source_refs,
        is_sufficient=True,
    )
