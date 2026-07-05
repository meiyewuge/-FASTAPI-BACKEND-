"""G1-G6 外置规则集骨架（W7）。

设计依据：M1-W7 条件施工许可 二.2。

每门一套 RulePack（v0.1，is_mock=True）。规则内容沿用 W4 mock 词表作为骨架占位，
结构上已就绪外置/版本化/md5 签收。正式法规级规则由后续工单填充并签收。
"""
from __future__ import annotations

from typing import Dict

from .schemas import Rule, RuleAction, RulePack, RuleSeverity


def _pack(scope: str, rules, changelog) -> RulePack:
    p = RulePack(rulepack_id=f"rp_{scope}", version="0.1.0", scope=scope,
                 rules=rules, changelog=changelog, is_mock=True)
    p.seal()   # 回填 md5（未签收：signed_by 仍空 → is_signed=False）
    return p


def g1_rulepack() -> RulePack:
    return _pack(
        "G1_compliance",
        [
            Rule("g1_medical", "医疗/治疗类禁用词",
                 ["治疗", "治愈", "根治", "痊愈", "药到病除"], RuleSeverity.HIGH, RuleAction.FAIL),
            Rule("g1_repair", "修复类（医疗范畴）禁用",
                 ["修复受损屏障", "重建屏障", "修复敏感肌"], RuleSeverity.HIGH, RuleAction.FAIL),
            Rule("g1_absolute", "绝对化用语",
                 ["100%", "绝对", "永久", "天下第一", "全球第一", "唯一"], RuleSeverity.HIGH, RuleAction.FAIL),
            Rule("g1_exaggerate", "功效夸大/收益承诺",
                 ["特效", "立竿见影", "保证赚钱", "稳赚", "包回本"], RuleSeverity.HIGH, RuleAction.FAIL),
            Rule("g1_caution", "谨慎词（须功效评价依据+缓释词）",
                 ["修护", "调理", "平衡", "舒缓"], RuleSeverity.MEDIUM, RuleAction.CONDITIONAL_PASS),
        ],
        ["v0.1.0 骨架：沿用 W4 mock 词表，待合规三清单 V1.1 正式规则替换"],
    )


def g2_rulepack() -> RulePack:
    return _pack(
        "G2_state_boundary",
        [Rule("g2_metaphysics", "玄学/转运/宿命越界",
              ["算命", "改命", "开运", "转运", "旺财", "风水", "能量场", "磁场疗愈",
               "产品改变命运", "用了就转运", "改变命运", "命里注定"],
              RuleSeverity.HIGH, RuleAction.FAIL)],
        ["v0.1.0 骨架：东方状态美学禁用玄学词表"],
    )


def g3_rulepack() -> RulePack:
    return _pack(
        "G3_fact_ref",
        [
            Rule("g3_unsourced", "无 source_ref 的事实句", [], RuleSeverity.HIGH, RuleAction.FAIL),
            Rule("g3_detection_incomplete", "检测宣称缺三要素(方法/编号/机构)",
                 ["检测", "检验", "测试", "试验", "临床", "功效评价"], RuleSeverity.HIGH, RuleAction.FAIL),
        ],
        ["v0.1.0 骨架：句级溯源 + 检测完整性；正式裁决见 FactRefAdjudicator 契约"],
    )


def g4_rulepack() -> RulePack:
    return _pack(
        "G4_platform_structure",
        [Rule("g4_structure", "平台结构必需项缺失（按四平台规则集）",
              [], RuleSeverity.HIGH, RuleAction.FAIL)],
        ["v0.1.0 骨架：结构裁决细则见 platform 四平台规则集契约"],
    )


def g5_rulepack() -> RulePack:
    return _pack(
        "G5_brand_consistency",
        [Rule("g5_cross_brand", "串品牌/串产品",
              ["雅诗兰黛", "兰蔻", "海蓝之谜", "欧莱雅", "珀莱雅", "SK-II",
               "面膜", "洗发水", "牙膏", "口红", "粉底液"],
              RuleSeverity.HIGH, RuleAction.FAIL)],
        ["v0.1.0 骨架：只允许达芙荻丽奢华油"],
    )


def g6_rulepack() -> RulePack:
    return _pack(
        "G6_format_complete",
        [Rule("g6_fields", "审读包/候选态字段缺失",
              ["正文文本", "used_materials_ids", "句级溯源审计"], RuleSeverity.HIGH, RuleAction.FAIL)],
        ["v0.1.0 骨架：字段完整性"],
    )


def all_gate_rulepacks() -> Dict[str, RulePack]:
    """六门规则集集合（scope → RulePack）。"""
    packs = [g1_rulepack(), g2_rulepack(), g3_rulepack(),
             g4_rulepack(), g5_rulepack(), g6_rulepack()]
    return {p.scope: p for p in packs}
