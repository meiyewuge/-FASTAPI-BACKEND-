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

from .. import coze_client
from ..config import settings

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


# GET /stores/profile 无资料时的默认门店对象（可用兜底，前端永远拿到对象，不再 null）
DEFAULT_STORE_PROFILE = {
    "store_name": "",
    "city": "",
    "contact_person": "",
    "phone": "",
    "store_type": "",
    "cooperation_status": "",
    "main_projects": [],
    "membership_level": "free",
}


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
    # 无资料时返回默认门店对象（不再返回 null），保证前端永远拿到可用对象
    return ApiResponse(data=STORES.get(user_id) or dict(DEFAULT_STORE_PROFILE))


@router.post("/stores/profile", response_model=ApiResponse)
def save_store_profile(profile: StoreProfile, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    data = profile.dict()
    data["id"] = user_id
    data["updated_at"] = time.time()
    STORES[user_id] = data
    return ApiResponse(data=data)


# content 硬护栏：医疗/夸大/绝对化/收益 → 软化（平台差异在 Coze prompt + 本表共同约束）
_CONTENT_SOFTEN = [
    ("根治", "调理改善"), ("治愈", "改善"), ("治疗", "调理"),
    ("100%", "大多数情况"), ("百分百", "大多数情况"), ("绝对", "通常"),
    ("彻底", "明显"), ("永久", "长期"), ("特效", "明显效果"), ("立竿见影", "见效较快"),
    ("最有效", "较为有效"), ("最好的", "优质的"), ("天下第一", "领先"),
    ("保证赚钱", "帮助经营"), ("稳赚", "有助于"), ("包回本", "辅助提升"),
]


def _soften_content(text: str) -> str:
    out = text or ""
    for bad, good in _CONTENT_SOFTEN:
        out = out.replace(bad, good)
    return out


def _content_template(req: "ContentGenerateRequest") -> dict:
    return {
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


def _flatten_content(data: dict, req: "ContentGenerateRequest"):
    """兼容 Coze 直返 {title,content,suggestions} 或分段 {hook,body,cta,image_suggestion,publish_time}。"""
    title = (data.get("title") or "").strip() or f"{req.theme}｜{_platform_name(req.platform)}内容"
    content_text = (data.get("content") or "").strip()
    if not content_text:
        parts = [p for p in (data.get("hook"), data.get("body"), data.get("cta")) if p]
        content_text = "\n\n".join(parts).strip()
    sugg = data.get("suggestions")
    if not (isinstance(sugg, list) and sugg):
        sugg = [s for s in (data.get("image_suggestion"), data.get("publish_time")) if s]
    return title, content_text, (sugg if isinstance(sugg, list) else [])


@router.post("/content/generate", response_model=ApiResponse)
async def generate_content(req: ContentGenerateRequest, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    title = ""
    content_text = ""
    suggestions = []
    content_detail = None
    source = "local_fallback"
    confidence_label = "本地模板(降级)"
    confidence = "low"
    degraded = True

    # 真实链路：灰度开启且配置完整时走 Coze Workflow；任何失败均降级到本地模板
    if coze_client.content_configured():
        try:
            data = await coze_client.run_workflow(
                settings.coze_content_workflow_id,
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
            t, ct, sg = _flatten_content(data, req)
            if ct:  # 有可渲染正文才算有效输出
                title, content_text, suggestions, content_detail = t, ct, sg, data
                source = "coze"
                confidence_label = "扣子知识库+模型生成"
                confidence = "medium"
                degraded = False
        except coze_client.CozeError:
            content_text = ""  # 触发模板兜底

    if not content_text:
        content = _content_template(req)
        title = content["title"]
        content_text = f"{content['hook']}\n\n{content['body']}\n\n{content['cta']}"
        suggestions = [s for s in (content.get("image_suggestion"), content.get("publish_time")) if s]
        content_detail = content
        source = "local_fallback"
        confidence_label = "本地模板(降级)"
        confidence = "low"
        degraded = True

    # 护栏：医疗/夸大/绝对化/收益软化（真实/降级都生效；平台差异另由 Coze prompt 约束）
    title = _soften_content(title)
    content_text = _soften_content(content_text)

    item = {
        "id": f"content_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "platform": req.platform,
        "content_type": req.content_type,
        "theme": req.theme,
        # 前端依赖的 3 个稳定字段
        "title": title or f"{req.theme}｜{_platform_name(req.platform)}内容",
        "content": content_text or "建议先到店做一次基础评估，我们不盲目推荐。",
        "suggestions": suggestions if isinstance(suggestions, list) else [],
        # 额外保留（前端不依赖）
        "content_detail": content_detail,
        "source": source,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "degraded": degraded,
        "quality_score": 88 if source == "coze" else 60,
        "audit_pass": True,
        "is_favorite": False,
        "created_at": time.time(),
    }
    CONTENTS.insert(0, item)
    return ApiResponse(data=item)


# chat 医疗/敏感词 → 追加免责（后端硬护栏，只追加一次）
_CHAT_SAFE_WORDS = ["医美", "祛斑", "热玛吉", "水光", "治疗", "疼", "过敏", "睡眠"]
_CHAT_SAFE_NOTE = "\n\n⚠️ 内容仅供参考，具体请遵医嘱或结合门店实际情况判断。"

_CHAT_FALLBACK_ANSWER = (
    "吴哥建议你先把问题分清楚：这是流量问题、转化问题、复购问题，还是表达问题。\n\n"
    "第一步，先问清楚顾客真实需求；\n"
    "第二步，用专业但不吓人的话讲清楚；\n"
    "第三步，给一个可以马上执行的小动作。\n\n"
    "可直接用的话术：\n"
    "“亲爱的，我不建议您盲目选择项目。您先把现在的情况跟我说一下，我根据您的状态给您一个更稳妥的建议。”"
)


def _apply_chat_guardrail(message: str, answer: str) -> str:
    """医疗/敏感问题追加免责，只追加一次。"""
    if any(w in (message or "") for w in _CHAT_SAFE_WORDS) or any(w in (answer or "") for w in _CHAT_SAFE_WORDS):
        if _CHAT_SAFE_NOTE.strip() not in (answer or ""):
            answer = (answer or "") + _CHAT_SAFE_NOTE
    return answer


@router.post("/ai/chat", response_model=ApiResponse)
async def ai_chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    user_id = _get_user_id(authorization)
    answer = ""
    source = "local_fallback"
    confidence_label = "本地模板(降级)"
    confidence = "low"
    degraded = True

    # 真实链路：仅当灰度开启且配置完整时调 Coze Bot；任何失败均降级到本地模板
    if coze_client.chat_configured():
        try:
            answer = await coze_client.chat_bot(req.message, user_id)
            source = "coze"
            confidence_label = "扣子知识库+模型生成"
            confidence = "medium"
            degraded = False
        except coze_client.CozeError:
            answer = ""  # 触发下方模板兜底

    if not answer:
        # 本地模板降级（绝不标"知识库+模型生成"）
        answer = _CHAT_FALLBACK_ANSWER
        source = "local_fallback"
        confidence_label = "本地模板(降级)"
        confidence = "low"
        degraded = True

    # 后端硬护栏：医疗/敏感问题追加免责（只一次，真实/降级都生效）
    answer = _apply_chat_guardrail(req.message, answer)

    return ApiResponse(data={
        "id": f"msg_{uuid.uuid4().hex[:10]}",
        "answer": answer or "暂无回复，请稍后重试",
        "source": source,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "degraded": degraded,
        "quality_score": 86 if source == "coze" else 60,
        "audit_pass": True,
    })


# 私域话术生成场景 → 话术 + 要点模板（生产环境后续接知识库/LLM + 合规审核）
_PRIVATE_SCENES = {
    "reactivate": {
        "answer": (
            "姐，好久没见你来店里了，最近还好吗？\n\n"
            "上次你做完护理说感觉轻松了不少，最近身体状态怎么样？换季很多老客的老毛病又容易反复。\n\n"
            "这周我给老客留了几个舒缓护理的位置，不是让你花钱，就是想着你之前那个状态如果又紧了，正好来放松一下。\n\n"
            "你看这周哪天方便？我先帮你留个位置。"
        ),
        "tips": ["先关心、后邀约，不要一上来就发促销", "给顾客台阶，不强迫", "用具体的上次记录拉近距离"],
    },
    "objection": {
        "answer": (
            "姐，我理解你的顾虑，选护理确实要慎重。\n\n"
            "我们的价格对应的是：专业评估 → 个性化方案 → 持续跟进，这三步是一体的。\n\n"
            "我不建议你只看价格，便宜的不一定适合你的情况；当然，预算也是要考虑的。\n\n"
            "这样，你先来做个免费评估，了解自己的实际情况再决定，不适合我也不会建议你做。"
        ),
        "tips": ["不贬低同行", "引导先体验再决策", "尊重顾客的经济考虑"],
    },
    "invitation": {
        "answer": (
            "姐，告诉你个好消息～\n\n"
            "这周六下午我们做了个小型护理体验，不是大促销，就是邀请几个老客一起放松。\n\n"
            "现场有评估和体验，氛围很轻松，你可以当来休息。\n\n"
            "我先帮你留一个名额？你看周六下午方便吗？"
        ),
        "tips": ["不用‘限时/最后X个名额’等紧迫话术", "强调轻松氛围而非消费", "给顾客选择权"],
    },
    "aftercare": {
        "answer": (
            "姐，谢谢你告诉我。出现这种反应一般属于正常范围，通常一段时间会缓解。\n\n"
            "你可以先这样做：①避免热水、用温水；②暂时不化妆让皮肤休息；③用医用保湿喷雾舒缓。\n\n"
            "如果情况没有缓解或有其他不适，第一时间找我，我来帮你处理。你的感受我很重视。"
        ),
        "tips": ["第一时间回复、不拖延", "不否认顾客感受", "严重情况建议就医、不自行判断"],
    },
    "followup": {
        "answer": (
            "姐，上次聊的项目你还在考虑吗？没有催你的意思，就是想着如果有疑问随时可以问我。\n\n"
            "第一次了解会犹豫很正常，毕竟是对自己的投入。\n\n"
            "方便的话可以先来做个免费状态检测，看看适不适合，不适合我也会直说，不会硬推。\n\n"
            "你看这周哪天有空？"
        ),
        "tips": ["距上次沟通至少间隔几天", "不催促不施压", "提供免费/低门槛的下一步"],
    },
}


# private 硬护栏：禁止项 → 软化（命中即替换违规措辞；无法软化由上层降级）
_PRIVATE_SOFTEN = [
    ("最后一个名额", "名额有限"), ("最后名额", "名额有限"),
    ("限时", "近期"), ("错过没有了", "欢迎随时了解"),
    ("隔壁家差", "每家定位不同"), ("别家骗人", "建议综合判断"), ("同行垃圾", "每家各有特色"),
    ("保证治好", "帮助改善体验"), ("一定见效", "因人而异"), ("根治", "调理改善"),
]


def _soften_private(text: str) -> str:
    out = text or ""
    for bad, good in _PRIVATE_SOFTEN:
        out = out.replace(bad, good)
    return out


@router.post("/private/generate", response_model=ApiResponse)
async def generate_private(req: PrivateGenerateRequest, authorization: Optional[str] = Header(default=None)):
    # scene_type 5 场景分流，非法/缺失统一兜底 reactivate
    scene_type = req.scene_type if req.scene_type in _PRIVATE_SCENES else "reactivate"

    answer = ""
    tips = []
    source = "local_fallback"
    confidence_label = "本地模板(降级)"
    confidence = "low"
    degraded = True

    # 真实链路：灰度开启且配置完整时走 Coze Workflow；任何失败均降级到本地模板
    if coze_client.private_configured():
        try:
            data = await coze_client.run_workflow(
                settings.coze_private_workflow_id,
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
                source = "coze"
                confidence_label = "扣子知识库+模型生成"
                confidence = "medium"
                degraded = False
        except coze_client.CozeError:
            answer = ""  # 触发模板兜底

    if not answer:
        scene = _PRIVATE_SCENES[scene_type]
        answer = scene["answer"]
        tips = list(scene["tips"])
        source = "local_fallback"
        confidence_label = "本地模板(降级)"
        confidence = "low"
        degraded = True

    # private 护栏：不硬推/不贬同行/不紧迫逼单 → 软化（真实/降级都生效）
    answer = _soften_private(answer)

    return ApiResponse(data={
        "id": f"private_{uuid.uuid4().hex[:10]}",
        "answer": answer or "稍后我再根据您的情况给您一个更稳妥的建议。",
        "tips": tips if isinstance(tips, list) else [],
        "scene_type": scene_type,
        "source": source,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "degraded": degraded,
        "quality_score": 87 if source == "coze" else 60,
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
    h5_base_url = "https://beautypeaceai.com"
    url = f"{h5_base_url}{path_map.get(req.target, '/diagnosis/start')}?ticket={ticket}&source=weapp"
    return ApiResponse(data={"url": url, "ticket": ticket})


def _platform_name(value: str) -> str:
    return {
        "moments": "朋友圈",
        "video": "视频号",
        "douyin": "抖音",
        "xiaohongshu": "小红书",
    }.get(value, value)
