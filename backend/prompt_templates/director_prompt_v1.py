"""Director Prompt Template v1（SOP 3.2a 灵魂模板，5 段式）。

模板固定，变量由引擎填入，用户永不碰模板本身。
T1 产品定格 / T2 风格基调 / T3 逐镜指令 / T4 品牌收束 / T5 禁止项。
"""

DIRECTOR_PROMPT_VERSION = "director_prompt_v1"


def render_director_text(brand: str, product: str, style_words: str,
                         shots: list[dict], slogan: str, negative_words: str) -> str:
    """组装 content[0].text。shots: [{timecode, description, line}]。"""
    brand = brand or ""
    product = product or ""
    t1 = f"【T1-产品定格】{brand}{product}产品广告视频。"
    t2 = f"【T2-风格基调】{style_words}。"

    lines = ["【T3-逐镜指令】"]
    for i, s in enumerate(shots, 1):
        desc = (s.get("description") or "").rstrip("。")
        line = (s.get("line") or "").rstrip("。")
        lines.append(f"镜头{i}({s.get('timecode','')})：{desc}。{line}。")
    t3 = "".join(lines)

    tail = (slogan or "以美养肤之美").rstrip("。")
    t4 = f"【T4-品牌收束】{brand}{product}，{tail}。"
    t5 = f"【T5-禁止项】{negative_words}。"
    return t1 + t2 + t3 + t4 + t5
