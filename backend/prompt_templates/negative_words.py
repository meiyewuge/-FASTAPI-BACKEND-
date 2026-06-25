"""禁止词（T5）。美业安全基线 + 风格附加。"""

from prompt_templates.style_presets import get_style

NEGATIVE_WORDS_VERSION = "beauty_safe_v1"

# 美业通用安全基线（所有风格强制叠加，去重）
_BASE_SAFE = "禁止低俗，禁止医疗功效虚假宣传，禁止违禁词"


def negative_for(style: str | None) -> str:
    """风格禁止词 + 美业安全基线（合并去重，保持顺序）。"""
    style_neg = get_style(style)["negative_words"]
    parts = [p.strip() for p in (style_neg + "，" + _BASE_SAFE).split("，") if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "，".join(out)
