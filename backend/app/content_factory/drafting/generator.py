"""W3 草稿生成器 — 接线 model_router，产出三版稿候选。

设计依据：M1-W3 条件施工许可 一/二。

链路（本模块负责最后一段）：
    used_materials（充分）
      → model_router.generate_draft ×3（专业/状态美学/平台改写）
      → 模型新增事实拦截（new_fact_guard）
      → 句级溯源审计（sentence_refs）
      → DraftCandidate（停在候选态）

严禁（W3 三）：不接真实模型、不接真实 9080、不进 W4、不实现 G1-G6 正式裁决器、
不产生 publish_allowed、不写 approved。本模块只用注入的 ModelRouter（mock clients）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.app.model_router.router import ModelRouter
from backend.app.model_router.schemas import (
    DraftTask,
    MissingMaterialReport,
    ModelRole,
    RouterResult,
    TaskStatus,
    TaskType,
)

from .new_fact_guard import detect_new_facts
from .schemas import (
    DraftCandidate,
    DraftCandidateStatus,
    DraftVersion,
    DraftVersionKind,
    DraftVersionStatus,
)
from .sentence_refs import audit_sentences

# 三版稿 → model_router 任务类型（同一组 used_materials，仅出稿角色/风格不同）
_VERSION_TASK_TYPE = {
    DraftVersionKind.PROFESSIONAL: TaskType.FACT_STRICT,
    DraftVersionKind.STATE_AESTHETIC: TaskType.STATE_AESTHETIC,
    DraftVersionKind.PLATFORM_REWRITE: TaskType.PLATFORM_REWRITE,
}


@dataclass
class DraftGenerator:
    """草稿生成器。持有一个 ModelRouter（mock 阶段 clients 全为 MockModelClient）。"""

    router: ModelRouter

    def generate(
        self,
        *,
        content_id: str,
        brief_id: str,
        trace_id: str,
        brief_text: str,
        used_materials: List[Dict[str, Any]],
        platform: Optional[str] = None,
        risk_hint: Optional[str] = None,
    ) -> DraftCandidate:
        """在 used_materials 充分的前提下生成三版稿候选。

        调用方（factory）负责在调用本方法前完成缺料/黑名单/无客户端停单判定；
        本方法内再做一次防御性校验：used_materials 为空直接停单。
        """
        used_ids = [str(m.get("id", "")) for m in used_materials if m.get("id")]

        # 防御性：空素材绝不出稿（与 model_router 硬边界二一致）
        if not used_materials:
            return DraftCandidate(
                content_id=content_id,
                brief_id=brief_id,
                trace_id=trace_id,
                status=DraftCandidateStatus.HALTED_MISSING_MATERIALS,
                used_materials_ids=[],
                halt_reason="used_materials 为空，缺料停单",
            )

        versions: List[DraftVersion] = []
        must_sign = False
        for kind in DraftVersionKind:
            v = self._one_version(kind, content_id, brief_text, used_materials, platform, risk_hint)
            versions.append(v)

        # 高风险提示：任一版由 model_router 标记 must_sign（此处以 risk_hint 兜底）
        must_sign = bool(risk_hint)

        ok = [v for v in versions if v.is_ok]
        status = (
            DraftCandidateStatus.DRAFT_CANDIDATE if ok else DraftCandidateStatus.BLOCKED
        )
        return DraftCandidate(
            content_id=content_id,
            brief_id=brief_id,
            trace_id=trace_id,
            status=status,
            used_materials_ids=used_ids,      # 三版稿共用同一组 used_materials
            versions=versions,
            must_sign=must_sign,
        )

    def _one_version(
        self,
        kind: DraftVersionKind,
        content_id: str,
        brief_text: str,
        used_materials: List[Dict[str, Any]],
        platform: Optional[str],
        risk_hint: Optional[str],
    ) -> DraftVersion:
        used_ids = [str(m.get("id", "")) for m in used_materials if m.get("id")]
        task = DraftTask(
            content_id=f"{content_id}:{kind.value}",
            task_type=_VERSION_TASK_TYPE[kind],
            brief=brief_text,
            used_materials=used_materials,
            platform=platform,
            risk_hint=risk_hint,
        )
        result = self.router.generate_draft(task)

        # 缺料/失败：model_router 返回 MissingMaterialReport 或非候选态
        if isinstance(result, MissingMaterialReport) or not isinstance(result, RouterResult):
            return DraftVersion(
                kind=kind, text=None, status=DraftVersionStatus.GEN_FAILED,
                used_materials_ids=used_ids, block_reason="model_router 未产出候选稿",
            )
        if result.status != TaskStatus.DRAFT_CANDIDATE or not result.text:
            return DraftVersion(
                kind=kind, text=result.text, status=DraftVersionStatus.GEN_FAILED,
                used_materials_ids=used_ids,
                produced_by_role=result.produced_by_role.value if result.produced_by_role else None,
                produced_by_model=result.produced_by_model,
                block_reason=f"model_router status={result.status.value}",
            )

        text = result.text
        role = result.produced_by_role.value if result.produced_by_role else None

        # 拦截一：模型新增事实（used_materials 之外的数字/编号）
        new_facts = detect_new_facts(text, used_materials)
        if new_facts:
            return DraftVersion(
                kind=kind, text=text, status=DraftVersionStatus.BLOCKED_NEW_FACT,
                used_materials_ids=used_ids, produced_by_role=role,
                produced_by_model=result.produced_by_model,
                block_reason=f"模型新增事实(未溯源): {','.join(new_facts)}",
            )

        # 拦截二：句级溯源 — 任一无源事实句 → 整版拒绝
        audit = audit_sentences(text, used_materials)
        if not audit.passed:
            return DraftVersion(
                kind=kind, text=text, status=DraftVersionStatus.BLOCKED_UNSOURCED_FACT,
                used_materials_ids=used_ids, audit=audit, produced_by_role=role,
                produced_by_model=result.produced_by_model,
                block_reason=f"无源事实句: {'|'.join(audit.violations)}",
            )

        return DraftVersion(
            kind=kind, text=text, status=DraftVersionStatus.OK,
            used_materials_ids=used_ids, audit=audit, produced_by_role=role,
            produced_by_model=result.produced_by_model,
        )
