"""美业无忧助手小程序接口 — 路由层。

本文件是 Coze 三拍（chat / private / content）接入的路由入口。
护栏逻辑 → guardrails.py
降级模板 → templates.py
Coze 调用 → coze_client.py
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .. import coze_client
from ..config import settings
from ..guardrails import (
    apply_chat_guardrail,
    make_id,
    meta_fallback,
    meta_success,
    soften_content,
    soften_private,
)
from ..templates import (
    CHAT_FALLBACK_ANSWER,
    PRIVATE_SCENES,
    VALID_SCENE_TYPES,
    content_template,
    flatten_content,
    platform_name,
)

logger = logging.getLogger("weapp")
router = APIRouter()

# ──────────────────────────────────────────────────────────────────────
# MVP 示例内存存储（生产环境必须替换为数据库）
# ──────────────────────────────────────────────────────────────────────
USERS: Dict[str, Dict[str, Any]] = {}
STORES: Dict[str, Dict[str, Any]] = {}
CONTENTS: List[Dict[str, Any]] = []
WEBVIEW_TICKETS: Dict[str, Dict[str, Any]] = {}


# ──────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────────────────
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
    target_customer: Optional[str] = ""


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


class PrivateGenerateRequest(BaseModel):
    scene_type: str = "reactivate"
    scene_name: Optional[str] = ""
    situation: str
    customer_info: Optional[str] = ""
    style: Optional[str] = "有温度、专业、不硬推、适合美业门店私域沟通"


# GET /stores/profile 默认门店对象（无资料时兜底，前端永远拿到对象）
DEFAULT_STORE_PROFILE: Dict[str, Any] = {
    "store_name": "",
    "city": "",
    "contact_person": "",
    "phone": "",
    "store_type": "",
    "cooperation_status": "",
    "main_projects": [],
    "membership_level": "free",
}


# ──────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────
def _get_user_id(authorization: Optional[str]) -> str:
    """从 Authorization header 提取用户标识（MVP 阶段简化处理）。"""
    if not authorization:
        return "demo_user"
    return authorization.replace("Bearer ", "") or "demo_user"


# ──────────────────────────────────────────────────────────────────────
# 认证 & 门店
# ──────────────────────────────────────────────────────────────────────
@router.post("/auth/wechat-login", response_model=ApiResponse)
def wechat_login(req: WechatLoginRequest):
    """微信登录（MVP mock，生产环境替换为 code2session）。"""
    openid = f"mock_openid_{req.code[-6:]}" if req.code else "mock_openid"
    token = f"token_{openid}"
    USERS[token] = {"openid": openid, "user_id": token, "created_at": time.time()}
    return ApiResponse(data={"token": token, "openid": openid, "user_id": token})


@router.get("/stores/profile", response_model=ApiResponse)
def get_store_profile(authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    return ApiResponse(data=STORES.get(user_id) or dict(DEFAULT_STORE_PROFILE))


@router.post("/stores/profile", response_model=ApiResponse)
def save_store_profile(profile: StoreProfile, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    data = profile.dict()
    data["id"] = user_id
    data["updated_at"] = time.time()
    STORES[user_id] = data
    return ApiResponse(data=data)


# ──────────────────────────────────────────────────────────────────────
# POST /content/generate — 内容生成（Coze Workflow / 本地模板降级）
# 前端契约：{ title, content, suggestions[] }  ← 不可变更
# ──────────────────────────────────────────────────────────────────────
@router.post("/content/generate", response_model=ApiResponse)
async def generate_content(
    req: ContentGenerateRequest,
    authorization: Optional[str] = Header(default=None),
):
    user_id = _get_user_id(authorization)
    t0 = time.monotonic()

    # 初始化为降级态
    title = ""
    content_text = ""
    suggestions: list = []
    content_detail: Optional[dict] = None
    meta = meta_fallback(quality_score=60)

    # ── 真实链路：灰度开启且配置完整时走 Coze Workflow ──
    if coze_client.content_configured():
        try:
            data = await coze_client.run_workflow(
                settings.coze_content_workflow_id,  # type: ignore[arg-type]
                {
                    "platform": req.platform,
                    "content_type": req.content_type,
                    "theme": req.theme,
                    "target_customer": req.target_customer or "",
                    "extra_info": req.extra_info or "",
                    "style": req.style or "",
                    "knowledge_scope": ["product", "public_promo", "guardrail", "wuge_ip"],
                },
            )
            t, ct, sg = flatten_content(data, req.theme, req.platform)
            if ct:  # 有可渲染正文才算有效输出
                title, content_text, suggestions, content_detail = t, ct, sg, data
                meta = meta_success(quality_score=88)
        except coze_client.CozeError:
            logger.info("content: coze failed, fallback to template | theme=%s", req.theme)
            content_text = ""  # 触发下方模板兜底

    # ── 降级链路：本地模板 ──
    if not content_text:
        tpl = content_template(req.theme, req.platform)
        title = tpl["title"]
        content_text = f"{tpl['hook']}\n\n{tpl['body']}\n\n{tpl['cta']}"
        suggestions = [s for s in (tpl.get("image_suggestion"), tpl.get("publish_time")) if s]
        content_detail = tpl
        meta = meta_fallback(quality_score=60)

    # ── 护栏：医疗/夸大/绝对化/收益软化（真实/降级都生效）──
    title = soften_content(title)
    content_text = soften_content(content_text)

    item = {
        "id": make_id("content"),
        "user_id": user_id,
        "platform": req.platform,
        "content_type": req.content_type,
        "theme": req.theme,
        # 前端依赖的 3 个稳定字段
        "title": title or f"{req.theme}｜{platform_name(req.platform)}内容",
        "content": content_text or "建议先到店做一次基础评估，我们不盲目推荐。",
        "suggestions": suggestions if isinstance(suggestions, list) else [],
        # 额外保留（前端不依赖）
        "content_detail": content_detail,
        **meta,
        "audit_pass": True,
        "is_favorite": False,
        "created_at": time.time(),
    }
    CONTENTS.insert(0, item)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "content/generate | source=%s | degraded=%s | elapsed=%.2fs | theme=%s",
        meta["source"], meta["degraded"], elapsed, req.theme,
    )
    return ApiResponse(data=item)


# ──────────────────────────────────────────────────────────────────────
# POST /ai/chat — 专业问答（Coze Bot Chat / 本地模板降级）
# 前端契约：{ answer }  ← 不可变更
# ──────────────────────────────────────────────────────────────────────
@router.post("/ai/chat", response_model=ApiResponse)
async def ai_chat(
    req: ChatRequest,
    authorization: Optional[str] = Header(default=None),
):
    user_id = _get_user_id(authorization)
    t0 = time.monotonic()

    answer = ""
    meta = meta_fallback(quality_score=60)

    # ── 真实链路：灰度开启且配置完整时调 Coze Bot ──
    if coze_client.chat_configured():
        try:
            answer = await coze_client.chat_bot(req.message, user_id)
            meta = meta_success(quality_score=86)
        except coze_client.CozeError:
            logger.info("chat: coze failed, fallback to template | module=%s", req.module)
            answer = ""  # 触发下方模板兜底

    # ── 降级链路：本地模板 ──
    if not answer:
        answer = CHAT_FALLBACK_ANSWER
        meta = meta_fallback(quality_score=60)

    # ── 后端硬护栏：医疗/敏感问题追加免责（只一次，真实/降级都生效）──
    answer = apply_chat_guardrail(req.message, answer)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "ai/chat | source=%s | degraded=%s | elapsed=%.2fs | module=%s",
        meta["source"], meta["degraded"], elapsed, req.module,
    )

    return ApiResponse(data={
        "id": make_id("msg"),
        "answer": answer or "暂无回复，请稍后重试",
        **meta,
        "audit_pass": True,
    })


# ──────────────────────────────────────────────────────────────────────
# POST /private/generate — 私域话术（Coze Workflow / 本地模板降级）
# 前端契约：{ answer, tips[] }  ← 不可变更
# ──────────────────────────────────────────────────────────────────────
@router.post("/private/generate", response_model=ApiResponse)
async def generate_private(
    req: PrivateGenerateRequest,
    authorization: Optional[str] = Header(default=None),
):
    user_id = _get_user_id(authorization)
    t0 = time.monotonic()

    # scene_type 5 场景分流，非法/缺失统一兜底 reactivate
    scene_type = req.scene_type if req.scene_type in VALID_SCENE_TYPES else "reactivate"

    answer = ""
    tips: list = []
    meta = meta_fallback(quality_score=60)

    # ── 真实链路：灰度开启且配置完整时走 Coze Workflow ──
    if coze_client.private_configured():
        try:
            data = await coze_client.run_workflow(
                settings.coze_private_workflow_id,  # type: ignore[arg-type]
                {
                    "scene_type": scene_type,
                    "scene_name": req.scene_name or "",
                    "situation": req.situation,
                    "customer_info": req.customer_info or "",
                    "style": req.style or "",
                    "knowledge_scope": ["guardrail", "private_rules", "product", "wuge_ip"],
                },
            )
            answer = (data.get("answer") or "").strip()
            t = data.get("tips")
            tips = t if isinstance(t, list) else []
            if answer:
                meta = meta_success(quality_score=87)
        except coze_client.CozeError:
            logger.info("private: coze failed, fallback to template | scene=%s", scene_type)
            answer = ""  # 触发下方模板兜底

    # ── 降级链路：本地模板 ──
    if not answer:
        scene = PRIVATE_SCENES[scene_type]
        answer = scene["answer"]
        tips = list(scene["tips"])
        meta = meta_fallback(quality_score=60)

    # ── 护栏：不硬推/不贬同行/不紧迫逼单（真实/降级都生效）──
    answer = soften_private(answer)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "private/generate | source=%s | degraded=%s | elapsed=%.2fs | scene=%s",
        meta["source"], meta["degraded"], elapsed, scene_type,
    )

    return ApiResponse(data={
        "id": make_id("private"),
        "answer": answer or "稍后我再根据您的情况给您一个更稳妥的建议。",
        "tips": tips if isinstance(tips, list) else [],
        "scene_type": scene_type,
        **meta,
        "audit_pass": True,
    })


# ──────────────────────────────────────────────────────────────────────
# 内容管理（历史/收藏/反馈）
# ──────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────
# WebView Token（经营诊断 H5 跳转）
# ──────────────────────────────────────────────────────────────────────
@router.post("/coach/webview-token", response_model=ApiResponse)
def coach_webview_token(req: WebviewTokenRequest, authorization: Optional[str] = Header(default=None)):
    """生成 webview ticket（生产环境应写入 Redis 并设 5 分钟有效期）。"""
    ticket = make_id("wv")
    WEBVIEW_TICKETS[ticket] = {"target": req.target, "store_id": req.store_id, "created_at": time.time()}
    path_map = {
        "diagnosis": "/diagnosis/start",
        "monthly": "/monthly/start",
        "history": "/monthly/history",
    }
    h5_base_url = "https://beautypeaceai.com"
    url = f"{h5_base_url}{path_map.get(req.target, '/diagnosis/start')}?ticket={ticket}&source=weapp"
    return ApiResponse(data={"url": url, "ticket": ticket})
