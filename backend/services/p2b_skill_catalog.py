"""P2B L2 技能目录 + 中文化映射（V4 P2B-A）。

铁律：P2B-A 的 6 个 L2 技能放在代码常量 P2B_L2_SKILL_CATALOG，
**不写 P2A 的 skill_registry 表**。GET /api/p2b/skills 从此常量返回。

skill_chain 硬锁（吴哥施工指令 §六）：数据库/接口必须保存 canonical skill_id，
用户界面显示中文 → 结构 [{"skill_id": "rhythm_edit_v1", "display_name": "节奏剪辑"}]。
"""

from __future__ import annotations

# ===== 6 个 L2 技能（canonical，唯一真值源）=====
P2B_L2_SKILL_CATALOG = [
    {"skill_id": "rhythm_edit_v1",            "name": "节奏剪辑",     "adapter": "rhythm_edit_adapter",            "category": "post_production", "layer": "L2", "description": "决定每个镜头为什么这么长"},
    {"skill_id": "smooth_transition_v1",      "name": "丝滑转场",     "adapter": "smooth_transition_adapter",      "category": "post_production", "layer": "L2", "description": "根据镜头关系选择转场方式"},
    {"skill_id": "narrative_subtitle_v1",     "name": "视觉叙事字幕", "adapter": "narrative_subtitle_adapter",     "category": "post_production", "layer": "L2", "description": "按优先级排版字幕，强化记忆点"},
    {"skill_id": "highlight_card_v1",         "name": "文案高光转场", "adapter": "highlight_card_adapter",         "category": "post_production", "layer": "L2", "description": "在叙事转折点插视觉冲击卡片"},
    {"skill_id": "active_dedup_v1",           "name": "主动编排去重", "adapter": "active_dedup_adapter",           "category": "qa_check",       "layer": "L2", "description": "从源头确保30条视频差异化"},
    {"skill_id": "orchestration_pipeline_v1", "name": "编排流水线",   "adapter": "orchestration_pipeline_adapter", "category": "orchestration",  "layer": "L2", "description": "把30条视频编成不同执行计划"},
]

# L2 canonical 集合（校验用）
P2B_L2_SKILL_IDS = {s["skill_id"] for s in P2B_L2_SKILL_CATALOG}
P2B_L2_ADAPTERS = {s["adapter"] for s in P2B_L2_SKILL_CATALOG}

# skill_chain 用到的 skill_id → 中文 display_name（含 P2A L1 的 safe_concat/playback_validate）
SKILL_DISPLAY = {
    "rhythm_edit_v1": "节奏剪辑",
    "smooth_transition_v1": "丝滑转场",
    "narrative_subtitle_v1": "视觉叙事字幕",
    "highlight_card_v1": "文案高光转场",
    "active_dedup_v1": "主动编排去重",
    "orchestration_pipeline_v1": "编排流水线",
    "safe_concat_v1": "安全拼接",
    "playback_validate_v1": "播放验证",
}


def chain_entry(skill_id: str) -> dict:
    """构造 skill_chain 条目：canonical skill_id + 中文 display_name。"""
    return {"skill_id": skill_id, "display_name": SKILL_DISPLAY.get(skill_id, skill_id)}


def list_skills() -> list[dict]:
    return [dict(s) for s in P2B_L2_SKILL_CATALOG]


# ===== 中文化映射（用户可见字段 100% 中文）=====
GROUP_TYPE_CN = {
    "pain_first": "痛点优先",
    "selling_first": "卖点优先",
    "result_close": "效果收尾",
    "brand_double": "品牌双打",
    "same_source": "同源裂变",
    "reverse": "反转策略",
}
GROUP_TYPE_DESC = {
    "pain_first": "痛点前置→卖点→品牌收束",
    "selling_first": "卖点前置→痛点→品牌收束",
    "result_close": "痛点→效果收束→品牌",
    "brand_double": "品牌双定→产品→品牌",
    "same_source": "同源前后对比",
    "reverse": "倒叙：品牌→痛点→产品",
}

HIGHLIGHT_FOCUS_CN = {
    "pain_emphasis": "痛点突出",
    "selling_emphasis": "卖点突出",
    "brand_emphasis": "品牌突出",
    "result_emphasis": "效果突出",
    "balanced": "均衡呈现",
}

VISUAL_STYLE_CN = {
    "cinematic": "电影感",
    "trendy": "时尚感",
    "minimal": "极简风",
    "energetic": "活力感",
    "elegant": "优雅感",
}

ROLE_CN = {
    "pain": "痛点", "product": "产品", "solution": "解决方案", "result": "效果",
    "brand": "品牌", "cta": "行动号召", "proof": "证据", "scene": "场景",
}

SCENARIO_CN = {
    "product_seeding": "产品种草", "brand_story": "品牌故事", "tutorial": "教程指南",
    "comparison": "对比评测", "review": "真实测评", "event": "活动促销", "testimony": "用户证言",
}

PLATFORM_CN = {
    "douyin": "抖音", "xiaohongshu": "小红书", "kuaishou": "快手", "shipinhao": "视频号",
}

# 5 种文案重点 / 5 种视觉风格（顺序固定，组内 5 条按此分配）
HIGHLIGHT_FOCUS_ORDER = ["pain_emphasis", "selling_emphasis", "brand_emphasis", "result_emphasis", "balanced"]
VISUAL_STYLE_ORDER = ["cinematic", "trendy", "minimal", "energetic", "elegant"]
GROUP_TYPE_ORDER = ["pain_first", "selling_first", "result_close", "brand_double", "same_source", "reverse"]

# 各 group_type 的镜头角色序列（与 P2A director_layer 对齐）
GROUP_ROLE_SEQUENCE = {
    "pain_first": ["pain", "product", "brand"],
    "selling_first": ["product", "pain", "brand"],
    "result_close": ["pain", "result", "brand"],
    "brand_double": ["brand", "product", "brand"],
    "same_source": ["pain", "product", "result"],
    "reverse": ["brand", "pain", "product"],
}
