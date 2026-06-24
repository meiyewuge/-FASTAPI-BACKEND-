"""接口数据结构。统一响应包 + 各入参。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Resp(BaseModel):
    """统一响应包：code=0 成功。"""

    code: int = 0
    message: str = "ok"
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


class ComposeIn(BaseModel):
    """B6：长视频一次成型（多段拼接）。"""

    prompt: str = Field(..., min_length=1)
    total_seconds: int = Field(30, ge=5, le=180, description="总时长(秒)，内部切≤15s 多段拼接")
    resolution: str = Field("720p", description="480p/720p/1080p")
    title: Optional[str] = None


class AGenerateIn(BaseModel):
    """A台：一句话需求。"""

    prompt: str = Field(..., min_length=1, description="视频需求，一句话")
    title: Optional[str] = None
    duration: int = Field(15, ge=4, le=15, description="视频时长(秒)，Seedance 2.0 支持 4-15")
    resolution: str = Field("720p", description="视频分辨率: 480p/720p/1080p")


class BGenerateIn(BaseModel):
    """B台：基于母视频批量裂变。"""

    source_video_id: int
    count: int = Field(10, ge=1, le=50, description="产出条数 10~50")
    prompt: Optional[str] = None
    strategy: Optional[str] = Field(
        "mix", description="内容策略：mix(轮换) / 引流型 / 成交型 / IP型 / 招商型 / 获客型"
    )
