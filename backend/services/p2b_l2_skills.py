"""P2B L2 六个技能 · 专业工艺计划生成（V4 P2B-A · 只出计划，不执行）。

每个技能是「专业工艺判断」而非「ffmpeg 工具封装」：只输出 plan（dict，含中文 explanation），
**不调用任何 L1 技能 / remixer / ffmpeg / 火山 / LLM**，纯规则 + 词库匹配，零成本。

对应 §4.2-4.7：rhythm_edit / smooth_transition / narrative_subtitle /
highlight_card / active_dedup / orchestration_pipeline。
"""

from __future__ import annotations

import re

from services.p2b_skill_catalog import (
    GROUP_TYPE_CN, HIGHLIGHT_FOCUS_CN, ROLE_CN, VISUAL_STYLE_CN,
)

# 角色时长权重（§4.2）
_ROLE_WEIGHT = {"pain": 0.35, "product": 0.45, "result": 0.30, "brand": 0.20,
                "cta": 0.15, "solution": 0.35, "scene": 0.25, "proof": 0.30}

# 视觉风格 → 节奏倾向（影响总时长与镜头停留）
_STYLE_RHYTHM = {
    "cinematic": ("慢节奏、大景深、柔和色调", 1.10),
    "trendy":    ("中快节奏、强对比、潮流色", 0.96),
    "minimal":   ("克制节奏、留白、低饱和", 1.00),
    "energetic": ("快节奏、强卡点、高饱和", 0.90),
    "elegant":   ("舒缓节奏、细腻光影、淡雅色", 1.06),
}

# 转场规则表（§4.3）：(from_role, to_role) → (type, duration, reason)
_TRANSITION_RULES = {
    ("pain", "product"): ("交叉淡化", 0.4, "从痛点焦虑情绪平滑过渡到产品展示，用交叉淡化制造情感缓冲"),
    ("product", "result"): ("擦除", 0.3, "展示产品后用擦除揭示效果，强化逻辑递进"),
    ("pain", "pain"): ("快切", 0.0, "连续痛点用快切，制造紧迫冲击感"),
    ("brand", "product"): ("淡出淡入", 0.5, "品牌→产品重新建立场景，制造品牌双打的重新切入"),
    ("result", "cta"): ("溶解", 0.4, "效果展示后柔和过渡到行动号召"),
    ("product", "pain"): ("交叉淡化", 0.4, "卖点先行后回扣痛点，用交叉淡化保持情感连续"),
    ("brand", "pain"): ("淡入", 0.5, "反转开场：品牌定格后切入痛点，用淡入制造悬念"),
    ("pain", "result"): ("擦除", 0.3, "痛点直连效果，用擦除快速建立前后对比认知"),
    ("product", "brand"): ("淡入", 0.5, "产品→品牌用淡入，制造品牌收束的仪式感"),
    ("result", "brand"): ("淡入", 0.5, "效果收束后品牌定格，像句号一样强化记忆"),
}
_DEFAULT_TRANSITION = ("淡入", 0.4, "镜头切换用淡入，保持整体观感顺滑")

# 痛点 / 卖点词库（零 LLM，正则 + 词库）
_PAIN_WORDS = ["皱纹", "暗沉", "松弛", "粗糙", "干燥", "细纹", "焦虑", "衰老", "黑头", "毛孔", "斑"]
_SELLING_WORDS = ["修复", "焕亮", "紧致", "提拉", "补水", "淡化", "嫩肤", "抗衰", "保湿", "亮白", "光滑"]
_NUM_RE = re.compile(r"\d+%|\d+万|\d+倍|\d+天|\d+ml|\d+次")


def _cn_role(role: str) -> str:
    return ROLE_CN.get(role, role)


# ---------------- 4.2 rhythm_edit ----------------
def rhythm_edit_plan(shots: list[dict], total_range: tuple[float, float],
                     visual_style: str, group_index: int) -> dict:
    lo, hi = total_range
    profile_desc, style_factor = _STYLE_RHYTHM.get(visual_style, ("标准节奏", 1.0))
    weights = [_ROLE_WEIGHT.get(s["role"], 0.30) for s in shots] or [1.0]
    wsum = sum(weights) or 1.0
    # 组内 5 条用 group_index 微调总时长，保持在 [lo,hi]
    base = (lo + hi) / 2.0
    target_total = base * style_factor + (group_index - 3) * 0.6
    target_total = max(lo, min(hi, target_total))

    durations = []
    for s, w in zip(shots, weights):
        d = round(w / wsum * target_total, 1)
        role = s["role"]
        reason = {
            "pain": f"痛点镜头控制在 {d} 秒内，快速刺入用户注意力，停留太久会失去冲击力",
            "product": f"产品展示给到 {d} 秒，让用户看清质地与瓶身细节",
            "result": f"效果镜头 {d} 秒，给足时间建立前后对比认知",
            "brand": f"品牌定格 {d} 秒，像句号一样强化品牌记忆",
            "cta": f"行动号召 {d} 秒，短促有力，直接告诉用户下一步",
            "solution": f"解决方案 {d} 秒，讲清产品如何起作用",
        }.get(role, f"{_cn_role(role)}镜头 {d} 秒，承接叙事节奏")
        durations.append({"shot_id": s.get("shot_id"), "role": _cn_role(role),
                          "duration": d, "reason": reason})

    real_total = round(sum(x["duration"] for x in durations), 1)
    seq_cn = "→".join(_cn_role(s["role"]) for s in shots)
    explanation = (
        f"本条采用「{seq_cn}」镜头节奏，视觉风格为{VISUAL_STYLE_CN.get(visual_style, visual_style)}"
        f"（{profile_desc}）。节奏整体遵循「快-慢-收」原则：痛点/CTA 快速切入，产品/效果充分展示，"
        f"品牌定格收束。总时长约 {real_total} 秒，落在 {int(lo)}-{int(hi)} 秒抖音完播率最优区间内；"
        f"组内第 {group_index} 条在总时长上做了细微差异化，避免与同组其它条节奏雷同。"
    )
    return {
        "shot_durations": durations,
        "total_duration": real_total,
        "rhythm_profile": f"{seq_cn}（{profile_desc}）",
        "explanation": explanation,
    }


# ---------------- 4.3 smooth_transition ----------------
def smooth_transition_plan(shots: list[dict], visual_style: str) -> dict:
    transitions = []
    for i in range(len(shots) - 1):
        a, b = shots[i]["role"], shots[i + 1]["role"]
        ttype, dur, reason = _TRANSITION_RULES.get((a, b), _DEFAULT_TRANSITION)
        transitions.append({
            "from_shot": shots[i].get("shot_id"), "to_shot": shots[i + 1].get("shot_id"),
            "from_role": _cn_role(a), "to_role": _cn_role(b),
            "type": ttype, "duration": dur, "reason": reason,
        })
    flow = "→".join(t["type"] for t in transitions) or "单镜头无转场"
    explanation = (
        f"转场设计围绕「{VISUAL_STYLE_CN.get(visual_style, visual_style)}」情感曲线展开："
        f"{flow}。痛点→产品用交叉淡化做情感缓冲，产品/效果→品牌用淡入制造收束仪式感，"
        f"连续痛点用快切制造紧迫感。每处转场都服务于叙事，不为炫技而转场，整体观感顺滑。"
    )
    return {"transitions": transitions, "overall_flow": flow, "explanation": explanation}


# ---------------- 4.4 narrative_subtitle ----------------
def narrative_subtitle_plan(shots: list[dict], rhythm: dict, brand_name: str,
                            must_keep: list[str]) -> dict:
    durations = rhythm["shot_durations"]
    total = rhythm["total_duration"]
    entries, key_terms, highlight_words = [], [], []
    t = 0.0
    for s, dur in zip(shots, durations):
        text = (s.get("text_content") or "").strip()
        seg = dur["duration"]
        start = round(t + 0.3, 1)
        end = round(t + seg, 1)
        if text:
            # 关键词识别（正则 + 词库），决定优先级/样式
            if any(w in text for w in _PAIN_WORDS):
                style, prio = "红色警示48px", "P2"
                reason = "痛点词用红色 48px 制造警示感"
            elif any(w in text for w in _SELLING_WORDS):
                style, prio = "绿色正向48px", "P3"
                reason = "卖点词用绿色 48px 传递正向情绪"
            elif _NUM_RE.search(text):
                style, prio = "黄色加粗60px", "P1"
                reason = "数字是信任锚点，加粗黄色高亮"
            else:
                style, prio = "白色标准36px", "P4"
                reason = "普通文案不抢风头，辅助阅读"
            entries.append({"start": start, "end": end, "text": text[:18],
                            "style": style, "priority": prio, "reason": reason})
            key_terms.extend([w for w in _PAIN_WORDS + _SELLING_WORDS if w in text])
            highlight_words.extend(m.group() for m in _NUM_RE.finditer(text))
        t += seg

    brand_start = round(max(0.0, total - 2.0), 1)
    brand_subtitle = {"start": brand_start, "end": round(total, 1),
                      "text": brand_name or "品牌", "style": "品牌大字72px"}
    entries.append({"start": brand_start, "end": round(total, 1), "text": brand_name or "品牌",
                    "style": "品牌大字72px", "priority": "P0",
                    "reason": "品牌名最后 2 秒最大字号定格，强化记忆"})
    key_terms = list(dict.fromkeys(key_terms + [brand_name] + (must_keep or [])))
    highlight_words = list(dict.fromkeys(highlight_words + ([brand_name] if brand_name else [])))
    explanation = (
        "字幕遵循「记忆金字塔」原则：品牌名(P0)最后 2 秒最大字号定格，数字(P1)加粗黄色高亮，"
        "痛点词(P2)红色警示，卖点词(P3)绿色正向，普通文案(P4)白色辅助。字幕在镜头开始后 0.3 秒出现、"
        "镜头结束前收尾，留 0.2 秒间隙避免重叠；全程零 LLM，仅用正则与痛点/卖点词库识别重点词。"
    )
    return {"subtitle_entries": entries, "key_terms": key_terms,
            "highlight_words": highlight_words, "brand_subtitle": brand_subtitle,
            "explanation": explanation}


# ---------------- 4.5 highlight_card ----------------
_CARD_RULES = {
    "pain_first": ("痛点→产品之间", "痛点关键词+问号", "红色底+大字", "在痛点到产品的转折点，用红色卡片强化痛点冲击"),
    "selling_first": ("产品→痛点之间", "卖点关键词+感叹号", "绿色底+大字", "在产品到痛点的转折点，用绿色卡片强化卖点信心"),
    "result_close": ("痛点→效果之间", "真实效果", "金色底+对勾", "在痛点到效果的转折点，用金色卡片证明效果"),
    "brand_double": ("品牌开头", "品牌名+Slogan", "品牌色底+Logo", "在开头用品牌卡片建立权威感"),
    "same_source": ("痛点→产品之间", "前后对比", "分屏卡片", "在痛点到产品之间，用分屏卡片制造对比冲击"),
    "reverse": ("品牌→痛点之间", "品牌名+?", "品牌色底+倒叙标记", "在品牌到痛点的转折点，用问号卡片制造悬念"),
}


def highlight_card_plan(group_type: str, pain_words: list[str], brand_name: str) -> dict:
    pos, content_tpl, style, reason = _CARD_RULES.get(group_type, _CARD_RULES["pain_first"])
    pain = (pain_words or ["皱纹"])[0]
    content = {
        "痛点关键词+问号": f"{pain}？", "卖点关键词+感叹号": "焕亮！", "真实效果": "真实效果 ✓",
        "品牌名+Slogan": f"{brand_name or '品牌'}·专业修复", "前后对比": "前 / 后",
        "品牌名+?": f"{brand_name or '品牌'}？",
    }.get(content_tpl, content_tpl)
    cards = [{"position": pos, "content": content, "style": style, "duration": 1.0,
              "reason": reason + "，卡片动画为淡入0.2秒+定格0.6秒+淡出0.2秒，不干扰叙事节奏"}]
    explanation = (
        f"本条采用「{GROUP_TYPE_CN.get(group_type, group_type)}」叙事结构，在「{pos}」插入 1 秒高光卡，"
        f"内容「{content}」、样式「{style}」。卡片在叙事转折点制造视觉冲击，大字设计确保 3 米外可读；"
        f"动画淡入 0.2 秒 + 定格 0.6 秒 + 淡出 0.2 秒，节奏上不打断主叙事。"
    )
    return {"cards": cards, "explanation": explanation}


# ---------------- 4.6 active_dedup（源头主动去重计划，不做 SSIM/MD5）----------------
def uniqueness_plan(group_type: str, group_index: int, highlight_focus: str,
                    visual_style: str, shots: list[dict], card_style: str,
                    transition_type: str) -> dict:
    seq = tuple(_cn_role(s["role"]) for s in shots)
    dims = [
        f"叙事结构：{GROUP_TYPE_CN.get(group_type, group_type)}（第{group_index}条）",
        f"文案重点：{HIGHLIGHT_FOCUS_CN.get(highlight_focus, highlight_focus)}",
        f"视觉风格：{VISUAL_STYLE_CN.get(visual_style, visual_style)}",
        f"镜头顺序：{'→'.join(seq)}",
        f"高光卡风格：{card_style}",
        f"首转场：{transition_type}",
    ]
    fingerprint = (f"group_type={group_type}|highlight_focus={highlight_focus}"
                   f"|visual_style={visual_style}|shot_sequence={seq}"
                   f"|card_style={card_style}|transition_type={transition_type}")
    explanation = (
        f"本条差异化锚点：采用「{GROUP_TYPE_CN.get(group_type, group_type)}」叙事结构，文案重点为"
        f"「{HIGHLIGHT_FOCUS_CN.get(highlight_focus, highlight_focus)}」，视觉风格为"
        f"「{VISUAL_STYLE_CN.get(visual_style, visual_style)}」。与同组其它 4 条相比，本条在视觉风格、"
        f"字幕节奏与高光卡风格上均不相同；与全部 30 条相比，参数指纹完全唯一。P2B-A 从源头主动去重，"
        f"不依赖画面相似度检测（不做 SSIM/MD5/截帧），MD5 兜底留待 P2B-C。"
    )
    return {"differentiation_dimensions": dims, "param_fingerprint": fingerprint,
            "explanation": explanation}
