"""本地降级模板 — 当 Coze 不可用时，保障前端始终拿到可用输出。

模板话术来自吴哥经营实战口径，可整理结构但不得改话术合规取向。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────
# 平台中文名映射
# ──────────────────────────────────────────────────────────────────────
_PLATFORM_NAMES: Dict[str, str] = {
    "moments": "朋友圈",
    "video": "视频号",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
}


def platform_name(value: str) -> str:
    """将平台英文标识映射为中文名，未匹配则原样返回。"""
    return _PLATFORM_NAMES.get(value, value)


# ──────────────────────────────────────────────────────────────────────
# content 降级模板
# ──────────────────────────────────────────────────────────────────────
def content_template(theme: str, platform: str) -> Dict[str, str]:
    """生成 content 接口的本地降级模板（分段式）。"""
    return {
        "title": f"{theme}｜{platform_name(platform)}内容",
        "hook": "很多门店不是没有好项目，而是没有把项目价值讲明白。",
        "body": (
            f"围绕"{theme}"，建议你不要直接硬卖。先讲顾客的真实痛点，"
            "再讲为什么这个问题值得重视，最后给一个低门槛的到店理由。\n\n"
            "吴哥一直讲，内容不是喊口号，是把老板心里的专业，翻译成顾客听得懂的话。"
        ),
        "cta": "想了解自己适不适合，可以先到店做一次基础评估，我们不盲目推荐。",
        "image_suggestion": "建议配门店环境、服务细节、顾客反馈三类图片。",
        "publish_time": "建议晚上8点到9点发布，适合老客刷朋友圈时看到。",
    }


def flatten_content(data: Dict[str, Any], theme: str, platform: str) -> tuple:
    """兼容 Coze 直返 {title,content,suggestions} 或分段 {hook,body,cta,...}。

    返回 (title, content_text, suggestions)。
    """
    title = (data.get("title") or "").strip() or f"{theme}｜{platform_name(platform)}内容"
    content_text = (data.get("content") or "").strip()
    if not content_text:
        parts = [p for p in (data.get("hook"), data.get("body"), data.get("cta")) if p]
        content_text = "\n\n".join(parts).strip()
    sugg = data.get("suggestions")
    if not (isinstance(sugg, list) and sugg):
        sugg = [s for s in (data.get("image_suggestion"), data.get("publish_time")) if s]
    return title, content_text, (sugg if isinstance(sugg, list) else [])


# ──────────────────────────────────────────────────────────────────────
# chat 降级模板
# ──────────────────────────────────────────────────────────────────────
CHAT_FALLBACK_ANSWER: str = (
    "吴哥建议你先把问题分清楚：这是流量问题、转化问题、复购问题，还是表达问题。\n\n"
    "第一步，先问清楚顾客真实需求；\n"
    "第二步，用专业但不吓人的话讲清楚；\n"
    "第三步，给一个可以马上执行的小动作。\n\n"
    "可直接用的话术：\n"
    ""亲爱的，我不建议您盲目选择项目。您先把现在的情况跟我说一下，我根据您的状态给您一个更稳妥的建议。""
)


# ──────────────────────────────────────────────────────────────────────
# private 降级模板 — 5 场景话术
# ──────────────────────────────────────────────────────────────────────
# scene_type 必须严格限定为以下 5 个场景，非法/缺失统一兜底 reactivate。
PRIVATE_SCENES: Dict[str, Dict[str, Any]] = {
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
        "tips": ["不用'限时/最后X个名额'等紧迫话术", "强调轻松氛围而非消费", "给顾客选择权"],
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

VALID_SCENE_TYPES = frozenset(PRIVATE_SCENES.keys())
