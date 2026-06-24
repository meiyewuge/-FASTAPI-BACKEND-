"""轻量 Intent 解析器（规则 + 正则 + 关键词，禁止依赖 LLM）。

输入：一句话需求，如「帮我做10个广州美容院抗衰视频」
输出：结构化 Intent。

铁律：
- 门店是 tenant 内部 target，不拆 tenant（tenant_scope 恒为 current_tenant）。
- 不引入任何外部大模型；将来要升级语义，可在此模块旁加 LLM 解析器并保持同样输出结构。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

# —— 关键词词典（可扩展）——
CITIES = [
    "北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "重庆", "西安",
    "苏州", "天津", "长沙", "郑州", "青岛", "东莞", "宁波", "佛山", "合肥", "厦门",
]
INDUSTRIES = ["皮肤管理", "美容院", "医美", "养生", "美甲", "美发", "纹绣", "瘦身"]
THEMES = ["抗衰", "补水", "拓客", "招商", "美白", "祛斑", "祛痘", "塑形", "课程", "IP"]

# 中文数字
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}


@dataclass
class Intent:
    action: str = "generate_video_batch"
    count: int = 1
    city: Optional[str] = None
    industry: Optional[str] = None
    theme: Optional[str] = None
    target_type: str = "store"
    tenant_scope: str = "current_tenant"
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _cn_to_int(s: str) -> Optional[int]:
    """解析简单中文数字（支持 0~99，如 三 / 十 / 十五 / 二十 / 二十三）。"""
    if not s:
        return None
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGIT.get(left, 1) if left else 1
        ones = _CN_DIGIT.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(s) == 1 and s in _CN_DIGIT:
        return _CN_DIGIT[s]
    return None


def _parse_count(text: str) -> int:
    # 阿拉伯数字优先：10个 / 5条 / 共20
    m = re.search(r"(\d+)\s*(?:个|条|集|版|份)?", text)
    if m:
        n = int(m.group(1))
        if n > 0:
            return n
    # 中文数字：十个 / 三条 / 二十
    m = re.search(r"([零一二两三四五六七八九十]+)\s*(?:个|条|集|版|份)", text)
    if m:
        n = _cn_to_int(m.group(1))
        if n:
            return n
    return 1


def _first_keyword(text: str, vocab: list[str]) -> Optional[str]:
    # 长词优先，避免「皮肤管理」被「养生」类短词截断
    for kw in sorted(vocab, key=len, reverse=True):
        if kw in text:
            return kw
    return None


def parse_intent(text: str) -> Intent:
    text = (text or "").strip()
    count = _parse_count(text)
    return Intent(
        action="generate_video_batch" if count > 1 else "generate_video",
        count=count,
        city=_first_keyword(text, CITIES),
        industry=_first_keyword(text, INDUSTRIES),
        theme=_first_keyword(text, THEMES),
        target_type="store",
        tenant_scope="current_tenant",
        raw=text,
    )
