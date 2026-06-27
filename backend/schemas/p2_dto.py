"""P2A 接口数据结构（生产单 + 裂变计划 preview）。

只定义入参 DTO；响应统一用 schemas.dto.Resp 包裹 dict（含 tenant_id 等字段）。
"""

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ProductionOrderPreviewIn(BaseModel):
    """生产单 preview 入参：从 director_plan 生成。"""

    director_plan_id: str = Field(..., min_length=1, description="导演稿 id（director_plans）")
    scenario: Optional[str] = Field(None, description="product_seeding|brand_story|tutorial|comparison|review|event|testimony")
    platform: Optional[str] = Field(None, description="douyin|xiaohongshu|shipinhao|kuaishou")


class ProductionOrderCreateIn(BaseModel):
    """生产单确认创建入参。"""

    director_plan_id: str = Field(..., min_length=1)
    scenario: Optional[str] = None
    platform: Optional[str] = None
    shot_maps_override: Optional[List[dict[str, Any]]] = Field(
        default=None, description="可选：前端编辑后的 shot_maps（落库强制填入 tenant_id）"
    )


class FissionPlanPreviewIn(BaseModel):
    """裂变计划 preview 入参：生产单 → 30 条 variant preview。"""

    production_order_id: str = Field(..., min_length=1)
