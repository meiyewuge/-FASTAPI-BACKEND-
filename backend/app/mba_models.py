from typing import Any


def diagnosis_mba_analysis(scored: dict[str, Any], form_data: dict[str, Any]) -> list[dict[str, str]]:
    dims = {d["key"]: d for d in scored.get("dimensions", [])}
    risks = scored.get("risk_tags", [])
    output: list[dict[str, str]] = []

    if any("复购" in r for r in risks) or dims.get("retention", {}).get("score", 99) < 12:
        output.append({
            "model_name": "AARRR增长模型",
            "conclusion": "留存与复购环节偏弱，说明门店不能只看新客引流，还要补老客回店和会员激活动作。",
            "business_meaning": "如果老客不能持续回店，门店会长期依赖低价获客，利润会被平台和投放吃掉。"
        })
    if dims.get("product", {}).get("score", 99) < 10 or dims.get("ticket", {}).get("score", 99) < 10:
        output.append({
            "model_name": "4P/4C产品营销模型",
            "conclusion": "产品结构和客户感知价值存在提升空间，当前需要检查引流款、利润款、高端款的梯度是否清晰。",
            "business_meaning": "项目没有梯度，客户只会买低价体验，很难自然升级到高客单。"
        })
    if dims.get("team", {}).get("score", 99) < 7:
        output.append({
            "model_name": "麦肯锡7S模型",
            "conclusion": "团队能力、话术SOP和服务流程需要加强，门店不能长期依赖老板或销售冠军个人能力。",
            "business_meaning": "团队不标准，成交和交付就不可复制，业绩会出现明显波动。"
        })
    if not output:
        output.append({
            "model_name": "BSC平衡计分卡",
            "conclusion": "门店整体经营基础尚可，下一步应围绕财务、客户、流程和团队四个维度做持续优化。",
            "business_meaning": "当前重点不是大改，而是通过月度体检持续找到最短板，逐月优化。"
        })
    return output


def monthly_mba_analysis(scored: dict[str, Any], form_data: dict[str, Any]) -> list[dict[str, str]]:
    metrics = scored.get("metrics", {})
    risks = scored.get("risk_tags", [])
    output: list[dict[str, str]] = []

    if "低于盈亏平衡线" in risks:
        output.append({
            "model_name": "盈亏平衡点模型",
            "conclusion": "本月业绩低于门店安全线，优先级不是扩张，而是先解决现金流和基础利润。",
            "business_meaning": "低于盈亏平衡点时，任何新增投入都要谨慎，先抓高确定性的老客激活和利润项目。"
        })
    if metrics.get("repurchase_rate", 0) < 30:
        output.append({
            "model_name": "RFM会员价值模型",
            "conclusion": "本月复购率偏低，需要把会员按活跃、高价值、沉睡、流失风险进行分层运营。",
            "business_meaning": "美业门店的稳定利润不来自一次性新客，而来自老客持续复购和升级。"
        })
    if metrics.get("cac") and metrics["cac"] > 200:
        output.append({
            "model_name": "LTV/CAC模型",
            "conclusion": "本月获客成本偏高，需要核算新客后续复购和升单价值，避免越投越亏。",
            "business_meaning": "如果客户终身价值不能覆盖获客成本，流量越多亏损越大。"
        })
    output.append({
        "model_name": "PDCA月度经营闭环",
        "conclusion": "本月体检结果应转化为下月四周行动计划，并在月底继续复查数据。",
        "business_meaning": "陪跑不是讲道理，而是每月用数据检查动作有没有产生结果。"
    })
    return output
