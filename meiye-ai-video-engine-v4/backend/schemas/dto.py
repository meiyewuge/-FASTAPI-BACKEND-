"""接口数据结构。统一响应包 + 各入参。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Resp(BaseModel):
    """统一响应包：code=0 成功。"""

    code: int = 0
    msg: str = "ok"
    data: Any = None


class LoginIn(BaseModel):
    phone: Optional[str] = None
    token: Optional[str] = None


class ExportIn(BaseModel):
    """导出：按 ids 或筛选条件，产出视频清单（manifest）。"""

    video_ids: Optional[list[int]] = None
    type: Optional[str] = None
    strategy: Optional[str] = None
    store_id: Optional[int] = None
    source_video_id: Optional[int] = None
    format: str = Field("json", description="json | csv")


class IntentIn(BaseModel):
    """一句话需求（Intent Layer 入口）。"""

    text: str = Field(..., min_length=1, description="自然语言需求，如：帮我做10个广州美容院抗衰视频")


class AGenerateIn(BaseModel):
    """A台：一句话需求。"""

    prompt: str = Field(..., min_length=1, description="视频需求，一句话")
    title: Optional[str] = None


class BGenerateIn(BaseModel):
    """B台：基于母视频批量裂变。"""

    source_video_id: int
    count: int = Field(10, ge=1, le=50, description="产出条数 10~50")
    prompt: Optional[str] = None
    strategy: Optional[str] = Field(
        "mix", description="内容策略：mix(轮换) / 引流型 / 成交型 / IP型 / 招商型 / 获客型"
    )
