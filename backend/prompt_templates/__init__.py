"""提示词模板注册表（V4 P0-B）。

集中管理 Director Prompt 模板、风格预设、禁止词、品牌注入规则，并带版本号，
每次 compose 生成都记录三个版本（可追溯哪一版提示词导致的效果）。
"""

from .director_prompt_v1 import DIRECTOR_PROMPT_VERSION, render_director_text
from .style_presets import STYLE_PRESET_VERSION, get_style, STYLES
from .negative_words import NEGATIVE_WORDS_VERSION, negative_for
from .brand_injection_rules import inject_brand_line

__all__ = [
    "DIRECTOR_PROMPT_VERSION", "render_director_text",
    "STYLE_PRESET_VERSION", "get_style", "STYLES",
    "NEGATIVE_WORDS_VERSION", "negative_for",
    "inject_brand_line",
]
