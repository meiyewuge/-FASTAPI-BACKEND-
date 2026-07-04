"""硬边界三：免费模型/低成本模型不得接触敏感数据（设计 8.3）。

禁止传入免费/低成本模型的数据类型：
1. 密钥/Token/API Key
2. 客户隐私（姓名/手机号/地址/消费记录）
3. 未脱敏门店数据（真实店名/真实经营数据/真实客户画像）
4. 未授权业务数据（未签发财务数据/未公开合作信息）

本模块只做"拦截判定"，不做自动脱敏——脱敏是上游数据准备的责任
（store_001 / 地区-城市代号 / reference_only 标注 / 虚拟占位符），
拦到即拒发，绝不"顺手洗一下再发"。
"""
from __future__ import annotations

import re
from typing import List

# ── 密钥/凭据特征 ──
_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key|password)\b\s*[:=]"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9]{16,}"),          # 常见 API Key 前缀
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"),  # Bearer token
]

# ── 客户隐私特征 ──
# 注意：不能用 \b —— 中文在 re 中属于 \w，号码紧贴中文时 \b 不成立会漏检，
# 改用前后非数字断言。
_PRIVACY_PATTERNS = [
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),            # 中国大陆手机号
    re.compile(r"(?<!\d)\d{17}[\dXx](?![\dXx])"),       # 18 位身份证号
]
_PRIVACY_KEYWORDS = ["消费记录", "客户姓名", "客户手机", "客户地址", "会员档案"]

# ── 未脱敏门店/业务数据标记 ──
# 上游必须把真实数据标注/替换后才可进低成本模型；命中以下关键词视为未脱敏。
_RAW_BUSINESS_KEYWORDS = [
    "真实店名", "真实经营数据", "真实客户画像",
    "未签发财务", "未公开合作", "内部财务数据", "银行流水",
]


def scan_sensitive(text: str) -> List[str]:
    """扫描文本中的敏感数据特征，返回命中说明列表（空=干净）。"""
    hits: List[str] = []
    t = text or ""
    for pat in _CREDENTIAL_PATTERNS:
        if pat.search(t):
            hits.append("credential:密钥/Token/API Key 特征")
            break
    for pat in _PRIVACY_PATTERNS:
        if pat.search(t):
            hits.append("privacy:手机号/证件号特征")
            break
    for kw in _PRIVACY_KEYWORDS:
        if kw in t:
            hits.append(f"privacy:{kw}")
    for kw in _RAW_BUSINESS_KEYWORDS:
        if kw in t:
            hits.append(f"raw_business:{kw}")
    return hits
