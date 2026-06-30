"""P2B-B1 接口入参（V4 P2B-B1）。响应统一用 schemas.dto.Resp 包裹 dict。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class RunsPreviewIn(BaseModel):
    """预览本次小批量执行（不生成）。"""

    production_order_id: str = Field(..., min_length=1)
    execution_plan_ids: List[str] = Field(..., min_length=1, description="选 3-6 条 confirmed plan")
    source_video_id: int = Field(..., description="绑定的真实源视频 id（本租户 mother，非缺陷源）")
    max_items: int = Field(3, ge=1, le=6, description="本次最多执行条数（B1 ≤ 6）")


class RunsIn(BaseModel):
    """真实执行小批量（受 staging + flag 双闸门）。"""

    production_order_id: str = Field(..., min_length=1)
    execution_plan_ids: List[str] = Field(..., min_length=1)
    source_video_id: int = Field(...)
    max_items: int = Field(3, ge=1, le=6)
    run_name: Optional[str] = None
    force: bool = Field(False, description="B2.6：跳过 duplicate run 拦截（管理端用；灰度默认 false）")
