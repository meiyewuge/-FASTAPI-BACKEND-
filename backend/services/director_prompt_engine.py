"""Director-Prompt Engine（V4 P0-B，SOP 第三部分）。

用户只传 文案 + 图片 + 选风格，引擎自动翻译成多模态 Seedance API 请求。
导演脚本与提示词一体化产出：Step1 文案解析 → Step2 导演分镜 → Step3 模板组装
→ Step4 图片角色分配 → Step5 组装 content[]。

纯函数、不碰 DB、不调火山。变量由引擎填入 prompt_templates 的固定模板。
"""

from __future__ import annotations

import math
import re

from config import settings
from prompt_templates import (
    DIRECTOR_PROMPT_VERSION, NEGATIVE_WORDS_VERSION, STYLE_PRESET_VERSION,
    get_style, inject_brand_line, negative_for, render_director_text,
)

# 常见美业产品形态后缀（用于从文案识别产品名）
_PRODUCT_SUFFIX = ("油", "霜", "水", "精华", "面膜", "乳", "露", "膏", "液", "粉", "棒", "啫喱")
_SPLIT = re.compile(r"[，,。；;、\n\s]+")

VERSIONS = {
    "director_prompt_version": DIRECTOR_PROMPT_VERSION,
    "style_preset_version": STYLE_PRESET_VERSION,
    "negative_words_version": NEGATIVE_WORDS_VERSION,
}


# ---------------- Step 1：文案解析 ----------------
def extract_brand_context(prompt: str, profile: dict | None = None) -> dict:
    """提取 品牌名 / 产品名 / 核心卖点(1-3) / slogan。提取失败回落 profile。"""
    profile = profile or {}
    tokens = [t for t in _SPLIT.split(prompt or "") if t]

    brand = profile.get("brand")
    product = ""
    # 第一个含产品后缀的 token 视为「品牌+产品」，拆出产品名
    for t in tokens:
        for suf in _PRODUCT_SUFFIX:
            if t.endswith(suf) and len(t) >= 2:
                product = suf if len(t) == 1 else t[-min(len(t) - 1, 3):]
                # 品牌 = 该 token 去掉产品形态后的前缀（启发式）
                if not brand:
                    brand = t[: len(t) - len(suf)] or profile.get("brand", "")
                # 更稳：产品名取整个含后缀的核心词
                product = t[len(brand):] if brand and t.startswith(brand) else suf
                break
        if product:
            break
    if not brand:
        brand = tokens[0] if tokens else profile.get("brand", "")
    # 卖点：除首 token 外的描述性 token，取前 3
    points = [t for t in tokens[1:] if t][:3] or tokens[:1]
    slogan = profile.get("slogan") or (points[-1] if points else "")
    return {
        "brand": brand or "",
        "product": product or "",
        "selling_points": points,
        "slogan": slogan,
        "scene_keywords": tokens[1:4],
    }


# ---------------- Step 4：图片角色分配（先于 Step2，便于绑定）----------------
def assign_image_roles(image_file_ids: list[str] | None) -> list[dict]:
    """第 1 张→first_frame；第 2-9 张→reference_image。无图→[]（纯文生）。"""
    ids = list(image_file_ids or [])[: settings.compose_max_images]
    roles = []
    for i, fid in enumerate(ids):
        roles.append({"file_id": fid, "role": "first_frame" if i == 0 else "reference_image"})
    return roles


# ---------------- Step 2：导演分镜 ----------------
def direct_storyboard(prompt: str, brand_context: dict, image_roles: list[dict],
                      style: str = "premium", duration: int = 15) -> list[dict]:
    """大白话 → 逐段分镜。每段：timecode/description/line/image_ref。

    叙事节奏：开场抓眼球 → 核心卖点 → 品牌定格收束。每段约 compose_seg_seconds 秒。
    """
    seg_len = max(1, settings.compose_seg_seconds)
    n = max(1, min(math.ceil(duration / seg_len), 6))
    brand = brand_context.get("brand", "")
    product = brand_context.get("product", "")
    slogan = brand_context.get("slogan", "")
    points = brand_context.get("selling_points") or [prompt]
    has_first = any(r["role"] == "first_frame" for r in image_roles)
    has_ref = any(r["role"] == "reference_image" for r in image_roles)

    shots = []
    for i in range(1, n + 1):
        start = (i - 1) * seg_len
        end = min(i * seg_len, duration)
        point = points[(i - 1) % len(points)]
        # 画面描述：首镜对齐 first_frame；其余锚定 reference_image
        if i == 1 and has_first:
            desc = f"{brand}{product}产品首帧定格，柔光缓慢推近，瓶身标签清晰可见，背景虚化"
        elif has_ref:
            desc = f"围绕{point}的特写，与参考图产品外观一致，{get_style(style)['style_words'].split('，')[0]}"
        else:
            desc = f"围绕{point}的场景，主体清晰，构图干净"
        line = inject_brand_line(brand, product, slogan, i, n, point)
        shots.append({
            "index": i,
            "timecode": f"{start}-{end}秒",
            "description": desc,
            "line": line,
            "image_ref": "first_frame" if (i == 1 and has_first) else ("reference_image" if has_ref else None),
        })
    return shots


# ---------------- Step 3：提示词组装（T1-T5）----------------
def assemble_prompt(brand_context: dict, storyboard: list[dict], style: str = "premium") -> str:
    """导演分镜 + 品牌约束 + 风格词 + 禁止词 → T1-T5 结构化中文提示词。"""
    sp = get_style(style)
    text = render_director_text(
        brand=brand_context.get("brand", ""),
        product=brand_context.get("product", ""),
        style_words=sp["style_words"],
        shots=storyboard,
        slogan=brand_context.get("slogan", ""),
        negative_words=negative_for(style),
    )
    return text


# ---------------- Step 5：组装 Seedance content[] ----------------
def assemble_seedance_content(text_prompt: str, image_roles: list[dict]) -> list[dict]:
    """text + image_url(role) → content[]。image_roles 需已含 url。"""
    content: list[dict] = [{"type": "text", "text": text_prompt}]
    for r in image_roles:
        if not r.get("url"):
            continue
        content.append({
            "type": "image_url",
            "image_url": {"url": r["url"]},
            "role": r["role"],
        })
    return content


# ---------------- 一体化：从输入到完整导演稿 ----------------
def build_director_plan(prompt: str, image_roles_with_url: list[dict], style: str,
                        duration: int, profile: dict | None = None) -> dict:
    """串起 Step1-5，返回 {brand_context, storyboard, text_prompt, content, versions}。

    image_roles_with_url：已带 url 的角色列表（url 校验在 image_url_check 完成）。
    """
    brand_context = extract_brand_context(prompt, profile)
    storyboard = direct_storyboard(prompt, brand_context, image_roles_with_url, style, duration)
    text_prompt = assemble_prompt(brand_context, storyboard, style)
    content = assemble_seedance_content(text_prompt, image_roles_with_url)
    return {
        "brand_context": brand_context,
        "storyboard": storyboard,
        "text_prompt": text_prompt,
        "content": content,
        "versions": dict(VERSIONS),
    }
