from __future__ import annotations

import json
from typing import Any
import httpx
from .config import settings


SYSTEM_PROMPT = """
你是“美业吴哥门店经营陪跑系统”的AI经营报告生成专家。
你的任务不是重新计算分数。所有分数、指标、评级均以后端规则引擎结果为准。
你只能基于系统提供的结构化数据进行分析，禁止编造用户未填写的数据，禁止修改分数，禁止承诺医疗效果，禁止承诺保证赚钱。
输出风格：沉稳、专业、接地气；先指出问题，再给行动；老板5分钟能看懂；每条建议必须可执行。
请只输出JSON，不要输出Markdown。
""".strip()


def local_diagnosis_report(payload: dict[str, Any]) -> dict[str, Any]:
    scores = payload.get("scores", {})
    total = scores.get("total_score") or payload.get("total_score")
    rating = payload.get("rating") or scores.get("rating")
    risks = payload.get("risk_tags", [])
    lowest = payload.get("lowest_dimension", {})
    store = payload.get("store_info", {})
    mba = payload.get("mba_diagnosis", [])
    weakest = lowest.get("name", "经营短板")
    service = "299实战课" if total and total < 70 else "2-3个月陪跑"
    if any("数字化" in r or "流量" in r for r in risks):
        service = "2-3个月抖音陪跑"
    if any("复购" in r for r in risks):
        service = "老客激活与15天业绩冲刺"

    return {
        "one_sentence_summary": f"{store.get('store_name', '该门店')}当前综合评级为{rating}，最需要优先处理的是{weakest}。",
        "overall_analysis": "从系统数据看，门店不是简单缺项目，而是需要围绕流量、转化、客单、复购和团队形成经营闭环。",
        "core_problems": [
            {
                "title": risk,
                "evidence": "该问题由系统评分规则和用户填写数据自动识别。",
                "impact": "如果不及时处理，会影响门店下月业绩稳定性和长期复购。",
                "priority": "high" if i == 0 else "medium",
            }
            for i, risk in enumerate(risks[:3])
        ] or [{"title": "暂无严重短板", "evidence": "综合得分相对稳定", "impact": "建议进入月度体检持续优化", "priority": "medium"}],
        "dimension_analysis": payload.get("dimensions", []),
        "mba_model_analysis": mba,
        "fifteen_day_action_plan": [
            {"period": "第1-3天", "action": "整理近30天、90天、180天未到店客户名单，筛选高价值沉睡会员。", "goal": "找到可快速激活的老客资产。"},
            {"period": "第4-7天", "action": "围绕最低分维度设计一个回店体验项目，并统一员工邀约话术。", "goal": "提升到店率和成交承接。"},
            {"period": "第8-12天", "action": "集中做到店转化和利润项目升单，每天复盘邀约、到店、成交数据。", "goal": "把动作转化为业绩。"},
            {"period": "第13-15天", "action": "复盘成交客户、未成交客户和员工表现，形成下月体检目标。", "goal": "进入持续经营陪跑闭环。"},
        ],
        "thirty_to_ninety_day_plan": "建议连续3个月做月度经营体检，重点追踪客流、客单、复购、人效和线上渠道转化。",
        "service_recommendation": {"recommended_service": service, "reason": f"系统识别到{weakest}是当前优先短板，需要配合具体动作落地。"},
        "risk_warning": "报告仅基于用户填写数据和规则引擎生成，如数据不完整，应补充后重新生成。",
        "confidence_note": f"当前报告置信度：{payload.get('confidence_level', '中')}。"
    }


def local_monthly_report(payload: dict[str, Any]) -> dict[str, Any]:
    scores = payload.get("scores", {})
    total = scores.get("total_score") or payload.get("total_score")
    risks = payload.get("risk_tags", [])
    lowest = payload.get("lowest_dimension", {})
    weakest = lowest.get("name", "经营短板")
    metrics = payload.get("metrics", {})
    return {
        "monthly_summary": f"本月经营体检分为{total}分，当前最需要关注的是“{weakest}”维度。",
        "biggest_improvement": "请结合趋势页查看环比提升最大的指标。",
        "biggest_risk": risks[0] if risks else "暂无严重风险，建议持续跟踪。",
        "six_dimension_analysis": payload.get("dimensions", []),
        "top_three_problems": [
            {"problem": r, "evidence": "由月度体检数据和规则评分自动识别。", "impact_next_month": "若不处理，可能影响下月业绩稳定性。", "priority": "high" if i == 0 else "medium"}
            for i, r in enumerate(risks[:3])
        ],
        "next_month_action_plan": [
            {"week": "第1周", "action": "围绕本月最低分维度制定一个明确目标。", "target": "目标必须可量化。", "owner_suggestion": "老板或店长亲自盯。"},
            {"week": "第2周", "action": "执行老客回访和高价值客户邀约。", "target": "完成不少于100个有效触达。", "owner_suggestion": "前台和顾问共同负责。"},
            {"week": "第3周", "action": "集中提升利润项目成交和客单价。", "target": "形成主推项目成交记录。", "owner_suggestion": "销售冠军带教。"},
            {"week": "第4周", "action": "复盘本月数据，准备下次月度体检。", "target": "沉淀可复制动作。", "owner_suggestion": "店长复盘。"}
        ],
        "boss_decision_advice": f"下月不要平均用力，先抓{weakest}。关键指标参考：复购率{metrics.get('repurchase_rate')}%，人效{metrics.get('staff_efficiency')}元，安全边际{metrics.get('safety_margin')}元。",
        "coach_followup_suggestion": "顾问跟进时先讲数据，再讲动作，最后推荐对应课程或陪跑服务。"
    }


async def call_llm(payload: dict[str, Any], report_type: str) -> dict[str, Any]:
    if not settings.llm_api_key:
        return local_monthly_report(payload) if report_type == "monthly_checkup" else local_diagnosis_report(payload)

    user_prompt = f"请基于以下结构化数据生成{report_type}报告，严格输出JSON：\n{json.dumps(payload, ensure_ascii=False)}"
    url = settings.llm_base_url.rstrip("/") + "/v1/chat/completions"
    # Some providers use /chat/completions without /v1; if it fails, local report prevents total outage.
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                alt_url = settings.llm_base_url.rstrip("/") + "/chat/completions"
                resp = await client.post(alt_url, headers=headers, json=body)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception:
        return local_monthly_report(payload) if report_type == "monthly_checkup" else local_diagnosis_report(payload)
