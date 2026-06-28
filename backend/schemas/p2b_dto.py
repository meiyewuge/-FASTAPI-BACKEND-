"""P2B-A 接口入参（V4 P2B-A）。响应统一用 schemas.dto.Resp 包裹 dict。"""

from typing import Optional

from pydantic import BaseModel, Field


class ThemeKernelIn(BaseModel):
    """生成中心思想：从 P2A 生产单。"""

    production_order_id: str = Field(..., min_length=1, description="P2A 生产单编号")


class ExecutionPlanPreviewIn(BaseModel):
    """预览 30 条执行计划（不入库）。fission_plan_id 可选。"""

    production_order_id: str = Field(..., min_length=1, description="P2A 生产单编号（必填）")
    fission_plan_id: Optional[str] = Field(
        None, description="裂变计划编号（可选）。未传则基于生产单 deterministic 生成 30 条"
    )


class ExecutionPlanConfirmIn(BaseModel):
    """确认并入库 30 条执行计划（幂等）。fission_plan_id 可选。"""

    production_order_id: str = Field(..., min_length=1)
    fission_plan_id: Optional[str] = Field(None)
