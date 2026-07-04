"""G1 / G2 / G4 / G5 / G6 门规则（W4 mock 裁决器）。

设计依据：M1-W4 条件施工许可 三·六硬门定义。

骨架期 mock 裁决——词表/规则为工程占位，正式规则集（外置配置 + 版本化）
由后续工单接入；本层只搭编排与判定接口，不冒充法规级裁决。

严禁（许可 13）：G4 不得扩权成事实/合规/品牌裁决器——G4 只判平台结构，
非结构问题一律路由到 G1/G2/G3/G5，不由 G4 出 fail。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.model_router.prescan import prescan_g1

from .schemas import GateName, GateResult, GateVerdict


# ──────────────────────────────────────────────────────────────────────
# 门上下文
# ──────────────────────────────────────────────────────────────────────
@dataclass
class GateContext:
    """单版稿过门所需上下文。"""

    version_kind: str
    text: str
    used_materials: List[Dict[str, Any]] = field(default_factory=list)
    used_materials_ids: List[str] = field(default_factory=list)
    platform: Optional[str] = None
    line: Optional[str] = None
    has_audit: bool = False


# ──────────────────────────────────────────────────────────────────────
# G1 合规红线门：医疗/功效/绝对化/禁用词
# ──────────────────────────────────────────────────────────────────────
# 谨慎词（🟡 有条件使用）→ conditional_pass（须功效评价依据+缓释词，交人工）
_G1_CAUTION_WORDS = ["修护", "调理", "平衡", "舒缓"]


def gate_g1(ctx: GateContext) -> GateResult:
    banned = prescan_g1(ctx.text)  # 复用 W0.5 禁用词预扫描子集
    if banned:
        return GateResult(GateName.G1_COMPLIANCE, GateVerdict.FAIL, hits=banned,
                          note="命中合规红线禁用词")
    caution = [w for w in _G1_CAUTION_WORDS if w in ctx.text]
    if caution:
        return GateResult(GateName.G1_COMPLIANCE, GateVerdict.CONDITIONAL_PASS, hits=caution,
                          note="谨慎词需功效评价依据+缓释词，转人工审读")
    return GateResult(GateName.G1_COMPLIANCE, GateVerdict.PASS)


# ──────────────────────────────────────────────────────────────────────
# G2 状态越界门：玄学/转运/把状态写成功效或宿命承诺
# ──────────────────────────────────────────────────────────────────────
_G2_BANNED = [
    "算命", "改命", "开运", "转运", "旺财", "风水", "能量场", "磁场疗愈",
    "产品改变命运", "项目改变运势", "用了就转运", "改变命运", "命里注定",
]


def gate_g2(ctx: GateContext) -> GateResult:
    hits = [w for w in _G2_BANNED if w in ctx.text]
    if hits:
        return GateResult(GateName.G2_STATE_BOUNDARY, GateVerdict.FAIL, hits=hits,
                          note="东方状态美学越界：玄学/转运/宿命承诺")
    return GateResult(GateName.G2_STATE_BOUNDARY, GateVerdict.PASS)


# ──────────────────────────────────────────────────────────────────────
# G4 平台结构门：只判结构，非结构问题路由到 G1/G2/G3/G5
# ──────────────────────────────────────────────────────────────────────
# 各平台必需结构标记（缺 → FAIL）与可选标记（缺 → WARNING）
_PLATFORM_REQUIRED = {
    "brand_site": ["标题", "正文"],
    "xiaohongshu": ["标题", "正文", "标签"],
    "douyin": ["钩子", "口播"],
    "shipinhao": ["开场", "正文"],
}
_PLATFORM_OPTIONAL = {
    "brand_site": ["FAQ", "SEO摘要"],
    "xiaohongshu": ["封面建议"],
    "douyin": ["分镜"],
    "shipinhao": ["金句"],
}

# G4 顺手扫描到的非结构信号 → 只标注路由，不由 G4 裁决（必测 6）
_ROUTE_SIGNALS = {
    GateName.G1_COMPLIANCE: ["根治", "治愈", "100%", "特效"],
    GateName.G2_STATE_BOUNDARY: ["转运", "改命", "旺财"],
    GateName.G5_BRAND_CONSISTENCY: ["雅诗兰黛", "兰蔻", "海蓝之谜"],
}


def gate_g4(ctx: GateContext) -> GateResult:
    platform = ctx.platform or ""
    required = _PLATFORM_REQUIRED.get(platform, [])
    optional = _PLATFORM_OPTIONAL.get(platform, [])

    # 非结构信号 → 记录路由，绝不由 G4 出 fail
    routed_to = [
        gate for gate, sigs in _ROUTE_SIGNALS.items()
        if any(s in ctx.text for s in sigs)
    ]

    missing_required = [m for m in required if m not in ctx.text]
    if missing_required:
        return GateResult(GateName.G4_PLATFORM_STRUCTURE, GateVerdict.FAIL,
                          hits=missing_required, routed_to=routed_to,
                          note=f"平台[{platform}]缺必需结构项")
    missing_optional = [m for m in optional if m not in ctx.text]
    if missing_optional:
        return GateResult(GateName.G4_PLATFORM_STRUCTURE, GateVerdict.WARNING,
                          hits=missing_optional, routed_to=routed_to,
                          note=f"平台[{platform}]缺可选结构项（不阻断）")
    return GateResult(GateName.G4_PLATFORM_STRUCTURE, GateVerdict.PASS, routed_to=routed_to)


# ──────────────────────────────────────────────────────────────────────
# G5 品牌一致门：只围绕达芙荻丽奢华油，不串品牌/串产品
# ──────────────────────────────────────────────────────────────────────
_G5_OTHER_BRANDS = ["雅诗兰黛", "兰蔻", "海蓝之谜", "欧莱雅", "珀莱雅", "sk-ii", "SK-II"]
# 非本品品类（串产品）
_G5_OTHER_PRODUCTS = ["面膜", "洗发水", "牙膏", "口红", "粉底液"]


def gate_g5(ctx: GateContext) -> GateResult:
    hits = [b for b in _G5_OTHER_BRANDS if b in ctx.text]
    hits += [p for p in _G5_OTHER_PRODUCTS if p in ctx.text]
    if hits:
        return GateResult(GateName.G5_BRAND_CONSISTENCY, GateVerdict.FAIL, hits=hits,
                          note="串品牌/串产品：M1 只允许达芙荻丽奢华油")
    return GateResult(GateName.G5_BRAND_CONSISTENCY, GateVerdict.PASS)


# ──────────────────────────────────────────────────────────────────────
# G6 格式完整门：审读包字段/候选态字段完整性
# ──────────────────────────────────────────────────────────────────────
def gate_g6(ctx: GateContext) -> GateResult:
    missing: List[str] = []
    if not ctx.text or not ctx.text.strip():
        missing.append("正文文本")
    if not ctx.used_materials_ids:
        missing.append("used_materials_ids")
    if not ctx.has_audit:
        missing.append("句级溯源审计")
    if missing:
        return GateResult(GateName.G6_FORMAT_COMPLETE, GateVerdict.FAIL, hits=missing,
                          note="候选态/审读包字段缺失")
    return GateResult(GateName.G6_FORMAT_COMPLETE, GateVerdict.PASS)
