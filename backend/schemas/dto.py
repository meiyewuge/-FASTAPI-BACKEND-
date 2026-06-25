"""接口数据结构。统一响应包 + 各入参。"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class Resp(BaseModel):
    """统一响应包：code=0 成功。"""

    code: int = 0
    message: str = "ok"
    data: Any = None


class LoginIn(BaseModel):
    """登录：手机号 + 邀约码（Patch4）。无邀约码不得登录。"""

    phone: str = Field(..., min_length=4, description="手机号")
    invite_code: str = Field(..., min_length=1, description="邀约码（必填）")


class InviteGenIn(BaseModel):
    """管理员生成邀约码。"""

    count: int = Field(1, ge=1, le=100, description="批量生成数量")
    tenant_id: Optional[str] = Field(None, description="绑定租户；空=按手机号自动建租户")
    max_uses: int = Field(1, ge=1, le=100000, description="每码可用次数")
    note: Optional[str] = None


class InviteRevokeIn(BaseModel):
    code: str = Field(..., min_length=1)


class BootstrapIn(BaseModel):
    """初始化超级管理员（Patch6，一次性，X-Admin-Key 保护）。"""

    phone: str = Field(..., min_length=4, description="超级管理员手机号（不写死，由请求提供）")
    note: Optional[str] = "initial super admin"


class GrantIn(BaseModel):
    """授权员工为管理员（仅 super_admin）。"""

    phone: str = Field(..., min_length=4)
    role: str = Field("invite_admin", description="invite_admin（发码员）")
    note: Optional[str] = None


class UserRevokeIn(BaseModel):
    """取消管理员授权（仅 super_admin）。"""

    phone: str = Field(..., min_length=4)


class TrackIn(BaseModel):
    """行为埋点（V4 P0 回流层）。tenant_id/phone 由 JWT 取，不信任前端。"""

    action: str = Field(..., description="play|select|send_to_b|download|export|favorite|dislike|delete")
    video_id: Optional[int] = None
    context: Optional[dict] = None


class FeedbackIn(BaseModel):
    """视频反馈 → 知识候选池（pending）。"""

    rating: str = Field(..., description="good | bad")
    tags: Optional[list[str]] = None
    note: Optional[str] = None


class CandidateReviewIn(BaseModel):
    """候选池审核备注（approve/reject）。"""

    note: Optional[str] = None


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


class ComposePreviewIn(BaseModel):
    """A台 compose 预览（V4 P0-B）：不调火山、不扣费，产出导演稿。"""

    prompt: str = Field(..., min_length=1, description="大白话文案")
    image_file_ids: Optional[list[str]] = Field(None, description="1-9 张图片 file_id")
    style: str = Field("premium", description="premium | fresh | chinese")
    ratio: str = Field("9:16", description="画幅，默认竖版")
    duration: int = Field(15, ge=4, le=60, description="总时长(秒)")
    resolution: str = Field("1080p", description="480p/720p/1080p")


class ComposeIn(BaseModel):
    """A台一键成片（多段15s→拼接）。V4 P0-B：需先 preview 拿 director_plan_id + 费用确认。"""

    prompt: Optional[str] = Field(None, description="大白话文案（无 director_plan_id 时必填）")
    director_plan_id: Optional[str] = Field(None, description="来自 /compose/preview")
    image_file_ids: Optional[list[str]] = None
    style: str = Field("premium")
    ratio: str = Field("9:16")
    total_seconds: int = Field(15, ge=4, le=60, description="总时长(秒)，内部切≤15s 多段拼接")
    resolution: str = Field("1080p", description="480p/720p/1080p")
    title: Optional[str] = None
    confirmed_cost: bool = Field(False, description="必须 true（用户已确认费用）才真生成")


class AGenerateIn(BaseModel):
    """A台：一句话需求。"""

    prompt: str = Field(..., min_length=1, description="视频需求，一句话")
    title: Optional[str] = None
    duration: int = Field(15, ge=4, le=15, description="视频时长(秒)，Seedance 2.0 支持 4-15")
    resolution: str = Field("720p", description="视频分辨率: 480p/720p/1080p")
    image_file_id: Optional[str] = Field(None, description="可选：参考图（来自 /api/upload 的 file_id）")


class BatchSourceIn(BaseModel):
    """批量裂变的单个源（P0 旧字段 sources 用，仅兼容）。"""

    source_video_id: int
    count: int = Field(5, ge=1, le=50, description="该源产出条数")
    strategy: Optional[str] = Field("mix", description="内容策略")


class BatchGenerateIn(BaseModel):
    """B台批量裂变（V4 P1）：会话源池优先 + 1:10（本地 ffmpeg，0 成本）。"""

    prompt: Optional[str] = None
    # P1 标准字段：前端按「会话源池优先」三层优先级提交
    source_video_ids: Optional[list[int]] = Field(None, description="P1 标准字段：源视频 id 列表")
    auto_ratio: int = Field(10, ge=1, le=10, description="每源裂变条数（1:N，默认 10）")
    max_outputs: int = Field(50, ge=1, le=50, description="总产出硬上限（P1=50）")
    strategy: Optional[str] = Field("mix", description="内容策略")
    # 兼容 P0（不推荐前端继续用）
    sources: Optional[list[BatchSourceIn]] = Field(None, description="P0 旧字段，仅兼容")
    total_limit: Optional[int] = Field(None, description="P0 旧字段，仅兼容")


class BGenerateIn(BaseModel):
    """B台：基于母视频批量裂变。"""

    source_video_id: int
    count: int = Field(10, ge=1, le=50, description="产出条数 10~50")
    prompt: Optional[str] = None
    strategy: Optional[str] = Field(
        "mix", description="内容策略：mix(轮换) / 引流型 / 成交型 / IP型 / 招商型 / 获客型"
    )
