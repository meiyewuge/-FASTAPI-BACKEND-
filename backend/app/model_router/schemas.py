"""模型路由层数据结构 — 任务/结果/缺料报告/门结果。

设计依据：《模型路由与兜底层设计 V0.1》第一、二、八章。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────────────────────────────
class ModelRole(str, Enum):
    """四角色模型路由（设计 2.1）。"""

    PRIMARY = "primary"      # 主模型：稳定、可控、成本清楚
    FALLBACK = "fallback"    # 兜底模型：高可用、低延迟
    REVIEW = "review"        # 审稿模型：自检+找风险+看结构
    REWRITE = "rewrite"      # 改写模型：平台改写+口语化+美感润色


class TaskType(str, Enum):
    """任务类型（设计 2.2 路由映射表左列）。"""

    FACT_STRICT = "fact_strict"              # 事实严谨型：品牌科普/检测引用/功效说明
    STATE_AESTHETIC = "state_aesthetic"      # 状态美学表达：东方状态美学版本
    PLATFORM_REWRITE = "platform_rewrite"    # 小红书/抖音/视频号改写
    HIGH_RISK = "high_risk"                  # 高风险内容：敏感肌/医美/术后/招商
    IP_OPINION = "ip_opinion"                # IP 观点稿扩展
    LONG_EXPANSION = "long_expansion"        # 长文扩写（Kimi 候选，受限扩写模式）


class TaskStatus(str, Enum):
    """任务终态。出口只到候选态，绝无 approved / published。"""

    DRAFT_CANDIDATE = "draft_candidate"        # 候选稿，去向 candidate_review
    MISSING_MATERIALS = "missing_materials"    # 缺料报告（硬边界二）
    FAILED = "failed"                          # 全模型失败，进人工处理
    MANUAL_REVIEW = "manual_review"            # 熔断/双失败，进人工复核
    HELD = "held"                              # 熔断 hold，排队等待人工确认
    BLOCKED_SENSITIVE = "blocked_sensitive"    # 敏感数据拦截（硬边界三）


class FailReason(str, Enum):
    """模型调用失败原因（设计 5.1 触发条件 + 硬边界三）。"""

    TIMEOUT = "timeout"
    QUALITY_FAIL = "quality_fail"
    STYLE_DRIFT = "style_drift"
    BANNED_WORD = "banned_word"          # G1 预扫描命中禁用词：打回，不重试同模型
    SENSITIVE_DATA = "sensitive_data"    # 敏感数据禁止传入免费/低成本模型
    CIRCUIT_OPEN = "circuit_open"        # 熔断中
    EXHAUSTED = "exhausted"              # 重试耗尽


# ──────────────────────────────────────────────────────────────────────
# 任务输入
# ──────────────────────────────────────────────────────────────────────
@dataclass
class DraftTask:
    """一次草稿生成任务（Brief 理解层 + 9080 召回层的下游输入）。

    used_materials：9080 召回的 approved 素材（唯一事实入口）。
    模型层零事实产出——事实只能来自这里（设计 1.1 / 铁律）。
    """

    content_id: str
    task_type: TaskType
    brief: str
    used_materials: List[Dict[str, Any]] = field(default_factory=list)
    platform: Optional[str] = None       # brand_site / xiaohongshu / douyin / shipinhao
    risk_hint: Optional[str] = None

    @property
    def used_materials_ids(self) -> List[str]:
        return [str(m.get("id", "")) for m in self.used_materials if m.get("id")]


# ──────────────────────────────────────────────────────────────────────
# 输出
# ──────────────────────────────────────────────────────────────────────
@dataclass
class GateResult:
    """单门扫描结果（G1-G6 由 W4 工单实现，本层只留挂接点与预扫描）。"""

    gate: str
    passed: bool
    hits: List[str] = field(default_factory=list)


@dataclass
class MissingMaterialReport:
    """缺料报告 — used_materials 为空时的唯一合法输出（硬边界二）。

    不进入 G1-G6，不进入 candidate_review，只进入 Brief 理解层反馈循环。
    """

    content_id: str
    task_type: TaskType
    missing_material_types: List[str]
    suggested_recall_keywords: List[str]
    status: TaskStatus = TaskStatus.MISSING_MATERIALS
    enters_gates: bool = False           # 恒 False，不进六硬门
    enters_candidate_review: bool = False  # 恒 False，不进候选审读


@dataclass
class RouterResult:
    """路由层最终输出。

    publish_allowed 硬编码为 False（M1 严禁项 #2：不自动发布）；
    候选稿唯一去向是 candidate_review，本层不做任何状态流转。
    """

    content_id: str
    status: TaskStatus
    task_type: TaskType
    text: Optional[str] = None
    produced_by_role: Optional[ModelRole] = None
    produced_by_model: Optional[str] = None
    used_materials_ids: List[str] = field(default_factory=list)
    gate_results: List[GateResult] = field(default_factory=list)
    must_sign: bool = False              # 高风险内容必须人工签发
    fail_reason: Optional[str] = None
    total_model_calls: int = 0
    # ── 常量出口约束，无写入口 ──
    publish_allowed: bool = field(default=False, init=False)
    writes_approved: bool = field(default=False, init=False)
