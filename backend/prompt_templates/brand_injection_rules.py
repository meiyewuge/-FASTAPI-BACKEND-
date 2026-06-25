"""品牌约束注入规则（强制）。对应 SOP 3.2a「品牌约束注入规则」。

每段镜头文案必须含品牌要素，防止 AI 生成泛化内容。按镜头位置注入不同格式：
- 开场镜头(1-2)：{品牌名}{产品名}，{核心卖点}
- 中间镜头(3-N)：{品牌名}，{功能/效果}
- 收束镜头(末)：{品牌名}{产品名}，{slogan}
"""

BRAND_INJECTION_VERSION = "brand_injection_v1"


def inject_brand_line(brand: str, product: str, slogan: str,
                      shot_index: int, total: int, point: str) -> str:
    """生成某镜头的品牌台词。shot_index 从 1 起。"""
    brand = brand or ""
    product = product or ""
    if shot_index == total:  # 收束
        tail = slogan or point or "以美养肤"
        return f"{brand}{product}，{tail}".strip("，")
    if shot_index <= 2:  # 开场
        return f"{brand}{product}，{point}".strip("，")
    return f"{brand}，{point}".strip("，")  # 中间
