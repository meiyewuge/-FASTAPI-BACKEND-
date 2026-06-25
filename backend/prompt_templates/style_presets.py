"""风格预设（固化配置，用户只选风格名）。对应 SOP 3.2a 风格表。"""

STYLE_PRESET_VERSION = "style_preset_v1"

STYLES = {
    "premium": {
        "label": "高端商业",
        "style_words": "低饱和冷调，商业摄影质感，柔光漫射，高级光影，原生高清画质",
        "negative_words": "禁止卡通变形，禁止夸张滤镜，禁止低画质，禁止文字水印，禁止杂乱多余元素",
    },
    "fresh": {
        "label": "清新自然",
        "style_words": "明亮自然光，清新通透，浅色调，轻盈质感",
        "negative_words": "禁止暗调，禁止厚重妆感，禁止过度磨皮",
    },
    "chinese": {
        "label": "国风",
        "style_words": "东方美学，水墨渐变，国风雅致，留白构图",
        "negative_words": "禁止西式元素，禁止荧光色，禁止现代科技感",
    },
}

_DEFAULT = "premium"


def get_style(name: str | None) -> dict:
    """返回风格预设；未知风格回落 premium。"""
    return STYLES.get((name or _DEFAULT), STYLES[_DEFAULT])
