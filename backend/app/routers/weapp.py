"""
美业无忧助手小程序接口补丁示例。

把本文件放入已有 FastAPI 后端 app/routers/weapp.py，然后在 main.py 中：

from app.routers import weapp
app.include_router(weapp.router, prefix="/api", tags=["weapp"])

生产环境需替换：
1. 微信 code2session
2. JWT 生成与校验
3. 数据库存储
4. 私有知识库检索
5. 大模型调用
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# MVP 示例内存存储。生产环境必须替换为数据库。
USERS: Dict[str, Dict[str, Any]] = {}
STORES: Dict[str, Dict[str, Any]] = {}
CONTENTS: List[Dict[str, Any]] = []
WEBVIEW_TICKETS: Dict[str, Dict[str, Any]] = {}


class ApiResponse(BaseModel):
    code: int = 1000
    msg: str = "success"
    data: Any = None


class WechatLoginRequest(BaseModel):
    code: str


class StoreProfile(BaseModel):
    store_name: Optional[str] = None
    store_type: Optional[str] = None
    city: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    main_projects: List[str] = Field(default_factory=list)
    membership_level: str = "free"


class ContentGenerateRequest(BaseModel):
    platform: str = "moments"
    content_type: str = "knowledge"
    business_type: str = "美容院"
    theme: str
    style: str = "专业有温度"
    extra_info: Optional[str] = ""


class ChatRequest(BaseModel):
    module: str = "business_guidance"
    message: str
    context: Dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    feedback: str
    comment: Optional[str] = None


class WebviewTokenRequest(BaseModel):
    target: str = "diagnosis"
    store_id: Optional[str] = None


def _get_user_id(authorization: Optional[str]) -> str:
    if not authorization:
        return "demo_user"
    return authorization.replace("Bearer ", "") or "demo_user"


@router.post("/auth/wechat-login", response_model=ApiResponse)
def wechat_login(req: WechatLoginRequest):
    # 生产环境：使用微信 code2session 换 openid/session_key。
    openid = f"mock_openid_{req.code[-6:]}" if req.code else "mock_openid"
    token = f"token_{openid}"
    USERS[token] = {"openid": openid, "user_id": token, "created_at": time.time()}
    return ApiResponse(data={"token": token, "openid": openid, "user_id": token})


@router.get("/stores/profile", response_model=ApiResponse)
def get_store_profile(authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    return ApiResponse(data=STORES.get(user_id))


@router.post("/stores/profile", response_model=ApiResponse)
def save_store_profile(profile: StoreProfile, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    data = profile.dict()
    data["id"] = user_id
    data["updated_at"] = time.time()
    STORES[user_id] = data
    return ApiResponse(data=data)


@router.post("/content/generate", response_model=ApiResponse)
def generate_content(req: ContentGenerateRequest, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    # 生产环境：检索私有知识库，组装提示词，调用大模型，执行合规审核。
    content = {
        "title": f"{req.theme}｜{_platform_name(req.platform)}内容",
        "hook": "很多门店不是没有好项目，而是没有把项目价值讲明白。",
        "body": (
            f"围绕“{req.theme}”，建议你不要直接硬卖。先讲顾客的真实痛点，"
            "再讲为什么这个问题值得重视，最后给一个低门槛的到店理由。\n\n"
            "吴哥一直讲，内容不是喊口号，是把老板心里的专业，翻译成顾客听得懂的话。"
        ),
        "cta": "想了解自己适不适合，可以先到店做一次基础评估，我们不盲目推荐。",
        "image_suggestion": "建议配门店环境、服务细节、顾客反馈三类图片。",
        "publish_time": "建议晚上8点到9点发布，适合老客刷朋友圈时看到。",
    }
    item = {
        "id": f"content_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "platform": req.platform,
        "content_type": req.content_type,
        "theme": req.theme,
        "content": content,
        "confidence": "medium",
        "confidence_label": "知识库+模型生成",
        "quality_score": 88,
        "audit_pass": True,
        "is_favorite": False,
        "created_at": time.time(),
    }
    CONTENTS.insert(0, item)
    return ApiResponse(data=item)


@router.post("/ai/chat", response_model=ApiResponse)
def ai_chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    # 生产环境：基于 module 选择知识库、提示词和合规策略。
    safe_note = ""
    if any(word in req.message for word in ["医美", "祛斑", "热玛吉", "水光", "治疗", "疼", "过敏", "睡眠"]):
        safe_note = "\n\n⚠️ 内容仅供参考，具体请遵医嘱或结合门店实际情况判断。"
    answer = (
        "吴哥建议你先把问题分清楚：这是流量问题、转化问题、复购问题，还是表达问题。\n\n"
        "第一步，先问清楚顾客真实需求；\n"
        "第二步，用专业但不吓人的话讲清楚；\n"
        "第三步，给一个可以马上执行的小动作。\n\n"
        "可直接用的话术：\n"
        "“亲爱的，我不建议您盲目选择项目。您先把现在的情况跟我说一下，我根据您的状态给您一个更稳妥的建议。”"
        f"{safe_note}"
    )
    return ApiResponse(data={
        "id": f"msg_{uuid.uuid4().hex[:10]}",
        "answer": answer,
        "confidence": "medium",
        "confidence_label": "知识库+模型生成",
        "quality_score": 86,
        "audit_pass": True,
    })


@router.get("/content/history", response_model=ApiResponse)
def content_history(authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    return ApiResponse(data={"list": [item for item in CONTENTS if item.get("user_id") == user_id][:100]})


@router.post("/content/{content_id}/favorite", response_model=ApiResponse)
def favorite_content(content_id: str, authorization: Optional[str] = Header(default=None)):
    for item in CONTENTS:
        if item["id"] == content_id:
            item["is_favorite"] = True
            return ApiResponse(data=True)
    raise HTTPException(status_code=404, detail="content not found")


@router.post("/content/{content_id}/feedback", response_model=ApiResponse)
def feedback_content(content_id: str, req: FeedbackRequest, authorization: Optional[str] = Header(default=None)):
    return ApiResponse(data={"content_id": content_id, "feedback": req.feedback, "saved": True})


@router.post("/coach/webview-token", response_model=ApiResponse)
def coach_webview_token(req: WebviewTokenRequest, authorization: Optional[str] = Header(default=None)):
    # 生产环境：ticket 应写入 Redis，设置 5 分钟有效期，H5 用 ticket 换登录态。
    ticket = uuid.uuid4().hex
    WEBVIEW_TICKETS[ticket] = {"target": req.target, "store_id": req.store_id, "created_at": time.time()}
    path_map = {
        "diagnosis": "/diagnosis/start",
        "monthly": "/monthly/start",
        "history": "/monthly/history",
    }
    h5_base_url = "https://h5.example.com"
    url = f"{h5_base_url}{path_map.get(req.target, '/diagnosis/start')}?ticket={ticket}&source=weapp"
    return ApiResponse(data={"url": url, "ticket": ticket})


def _platform_name(value: str) -> str:
    return {
        "moments": "朋友圈",
        "video": "视频号",
        "douyin": "抖音",
        "xiaohongshu": "小红书",
    }.get(value, value)
