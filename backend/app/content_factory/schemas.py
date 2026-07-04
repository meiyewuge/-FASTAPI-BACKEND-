"""文案加工厂数据结构 — Brief / 任务状态 / 溯源上下文 / Staging 条目。

设计依据：M1 W1 服务骨架与 Brief 接口。

本层职责边界：
- 纯数据结构定义，不含任何网络调用或持久化逻辑；
- task_type 复用 model_router.TaskType，保证下游无缝衔接；
- FactoryTaskState 为 7 态枚举（含缺料停单态），状态流转逻辑在 task_state.py。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.app.model_router.schemas import TaskType

if TYPE_CHECKING:
    from backend.app.model_router.schemas import MissingMaterialReport


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ──────────────────────────────────────────────────────────────────────
# 任务状态（7 态，含缺料停单态）
# ──────────────────────────────────────────────────────────────────────
class FactoryTaskState(str, Enum):
    """文案加工厂任务状态机 — 8 态流转（含停单态 + 候选拦截态）。

    正常链路：queued → producing → gated → packaged → in_review → closed
    缺料停单：producing → halted_missing_materials（终态）
    候选拦截：producing → blocked_draft（终态，W3：三版稿全被无源/新增事实拦截）
    不允许跳态（如 queued → closed）。
    """

    QUEUED = "queued"            # 排队等待处理
    PRODUCING = "producing"      # 模型生成中（Brief 理解 + 召回 + 出稿）
    HALTED_MISSING_MATERIALS = "halted_missing_materials"  # 缺料停单（终态）
    BLOCKED_DRAFT = "blocked_draft"  # 三版稿全被拦（无源事实句/模型新增事实）（终态）
    GATED = "gated"              # 六硬门质检中（W4 工单实现后激活）
    PACKAGED = "packaged"        # 打包完成，等待人审
    IN_REVIEW = "in_review"      # 人工审读中
    CLOSED = "closed"            # 终态：签发或拒绝


# ──────────────────────────────────────────────────────────────────────
# Brief（Brief 理解层输入）
# ──────────────────────────────────────────────────────────────────────
# ── 合法 target_platform 值 ─────────────────────────────────────────
VALID_TARGET_PLATFORMS = {"brand_site", "xiaohongshu", "douyin", "shipinhao"}

# ── M1 锁死品牌线 ───────────────────────────────────────────────────
M1_LOCKED_LINE = "brand_dfd"


@dataclass
class Brief:
    """一次内容生产请求的 Brief 理解层输入。

    brief_id：Brief 唯一标识（自动生成）
    trace_id：全链路溯源 ID（与 task_id/brief_id 三 ID 绑定）
    task_type：任务类型，复用 model_router.TaskType
    target_platform：目标平台（必填，四选一：brand_site / xiaohongshu / douyin / shipinhao）
    line：品牌线（M1 锁死 brand_dfd，G5 品牌一致门锚点）
    direction_hint：方向提示（平台灵感/热点/对标内容只进此字段，不得作为事实源）
    raw_text：原始 Brief 文本（不得为空）
    target_audience：目标受众（可选）
    risk_hint：风险提示（可选，HIGH_RISK 类内容必填）
    batch_id：批量 Brief 批次号（可选）
    extra：扩展字段（预留）
    """

    raw_text: str
    target_platform: str  # 必填，四选一
    task_type: TaskType = TaskType.FACT_STRICT
    line: str = M1_LOCKED_LINE
    direction_hint: Optional[str] = None
    target_audience: Optional[str] = None
    risk_hint: Optional[str] = None
    batch_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    brief_id: str = field(default_factory=lambda: _new_id("brief"))
    trace_id: str = field(default_factory=lambda: _new_id("trace"))


# ──────────────────────────────────────────────────────────────────────
# 溯源上下文（三 ID 绑定）
# ──────────────────────────────────────────────────────────────────────
@dataclass
class TraceContext:
    """全链路溯源上下文：trace_id + task_id + brief_id 三 ID 绑定。

    每一条内容从 Brief 输入到最终签发/拒绝，都必须携带同一 trace_id。
    """

    trace_id: str
    task_id: str = field(default_factory=lambda: _new_id("task"))
    brief_id: str = ""

    @classmethod
    def from_brief(cls, brief: Brief) -> "TraceContext":
        return cls(trace_id=brief.trace_id, brief_id=brief.brief_id)


# ──────────────────────────────────────────────────────────────────────
# Content Staging 条目
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ContentStagingEntry:
    """content_staging 私有目录中的一条内容条目。

    仅存内存（mock 阶段），不持久化、不写外部数据库。
    """

    content_id: str
    brief_id: str
    trace_id: str
    state: FactoryTaskState = FactoryTaskState.QUEUED
    text: Optional[str] = None
    used_materials_ids: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
