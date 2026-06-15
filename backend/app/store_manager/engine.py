import uuid
from datetime import datetime
from typing import Dict, Any, List


def to_number(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def current_month():
    return datetime.now().strftime("%Y-%m")


def now_iso():
    return datetime.now().isoformat()


def make_id(prefix):
    return "%s_%s_%s" % (prefix, datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8])


def calc_metrics(form: Dict[str, Any]) -> Dict[str, Any]:
    revenue = to_number(form.get("monthly_revenue"))
    target = to_number(form.get("target_revenue"))
    visits = to_number(form.get("customer_visits"))
    employees = to_number(form.get("employee_count"))
    old_visits = to_number(form.get("old_customer_visits"))
    new_customers = to_number(form.get("new_customers"))

    average_ticket = to_number(form.get("average_ticket")) or (revenue / visits if visits > 0 else 0)
    per_staff_output = to_number(form.get("per_staff_output")) or (revenue / employees if employees > 0 else 0)
    target_completion_rate = (revenue / target * 100) if target > 0 else 0
    old_customer_ratio = (old_visits / visits * 100) if visits > 0 else 0
    new_customer_ratio = (new_customers / visits * 100) if visits > 0 else 0

    return {
        "monthly_revenue": round(revenue, 2),
        "target_revenue": round(target, 2),
        "customer_visits": int(visits),
        "average_ticket": round(average_ticket, 2),
        "employee_count": int(employees),
        "per_staff_output": round(per_staff_output, 2),
        "target_completion_rate": round(target_completion_rate, 1),
        "old_customer_ratio": round(old_customer_ratio, 1),
        "new_customer_ratio": round(new_customer_ratio, 1),
        "inactive_30d_customers": int(to_number(form.get("inactive_30d_customers"))),
        "repurchase_rate": round(to_number(form.get("repurchase_rate")), 1) if form.get("repurchase_rate") not in (None, "") else None,
        "avg_customer_age": round(to_number(form.get("avg_customer_age")), 1) if form.get("avg_customer_age") not in (None, "") else None,
    }


def choose_core_issues(form: Dict[str, Any], metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = []

    if metrics["target_completion_rate"] < 80:
        candidates.append({
            "score": 95,
            "title": "本月目标完成有缺口",
            "reason": "本月营收与目标之间存在明显差距，店长需要把目标拆到每日动作，而不是只等月底结果。",
            "data_basis": "目标完成率约 %.1f%%，本月营收 %.0f 元，目标 %.0f 元。" % (
                metrics["target_completion_rate"], metrics["monthly_revenue"], metrics["target_revenue"]
            )
        })

    inactive = metrics["inactive_30d_customers"]
    if inactive >= 30:
        candidates.append({
            "score": 90,
            "title": "30天未到店客户需要优先激活",
            "reason": "30天未到店客户越多，说明老客触达、回店理由和复购机制需要重新梳理。",
            "data_basis": "30天未到店客户数为 %d 人。" % inactive
        })

    repurchase = metrics.get("repurchase_rate")
    if repurchase is not None and repurchase < 25:
        candidates.append({
            "score": 88,
            "title": "老客复购率偏低",
            "reason": "老客复购不足，会让门店持续依赖新客和活动，店长需要把复购动作前置到每日跟进。",
            "data_basis": "老客复购率约 %.1f%%。" % repurchase
        })

    if metrics["per_staff_output"] > 0 and metrics["per_staff_output"] < 20000:
        candidates.append({
            "score": 80,
            "title": "员工人均产出需要提升",
            "reason": "总业绩不能只靠老板或销冠，店长要把目标拆到员工每日客户跟进和主推项目动作。",
            "data_basis": "员工数 %d 人，人均产出约 %.0f 元。" % (
                metrics["employee_count"], metrics["per_staff_output"]
            )
        })

    age = metrics.get("avg_customer_age")
    if age is not None and age >= 45:
        candidates.append({
            "score": 70,
            "title": "客户年龄结构需要关注",
            "reason": "消费年龄偏高时，要同时维护老客信任，并逐步补充年轻客群和内容触达。",
            "data_basis": "顾客平均消费年龄约 %.1f 岁。" % age
        })

    if not candidates:
        candidates.append({
            "score": 60,
            "title": "本月经营动作需要更聚焦",
            "reason": "当前数据没有明显极端风险，但店长仍需要把目标拆到客户、员工和项目动作上。",
            "data_basis": "基础数据相对平稳，建议继续补充复购、客户分层和项目结构数据。"
        })

    # Add subjective issue if provided.
    if form.get("main_problem_text"):
        candidates.append({
            "score": 75,
            "title": "店长主观反馈的问题需要纳入复盘",
            "reason": "店长的一线感受往往能补足数据盲区，需要和经营数据一起判断。",
            "data_basis": "店长反馈：%s" % form.get("main_problem_text")
        })

    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)[:3]
    issues = []
    for idx, item in enumerate(candidates, start=1):
        issues.append({
            "id": idx,
            "title": item["title"],
            "reason": item["reason"],
            "data_basis": item["data_basis"]
        })
    return issues


def weekly_actions_for_issue(issue: Dict[str, Any]) -> str:
    title = issue.get("title", "")
    if "目标" in title or "营收" in title:
        return "把本月缺口拆成未来7天每日目标，店长每天追一次执行动作和结果。"
    if "未到店" in title or "复购" in title or "老客" in title:
        return "整理30天未到店和高价值老客名单，按优先级做第一轮回访。"
    if "员工" in title or "人均" in title:
        return "让每位员工明确本周主推项目、跟进客户和每日动作，店长每天做短复盘。"
    if "年龄" in title:
        return "梳理现有客户年龄结构，优化朋友圈和项目表达，避免只服务存量老客。"
    return "围绕这个问题制定一周内可执行的动作，并每天记录执行情况。"


def today_task_for_issue(issue: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = issue.get("title", "")
    task_id = make_id("task")
    if "未到店" in title or "复购" in title or "老客" in title:
        return {
            "task_id": task_id, "issue_id": issue["id"], "type": "客户跟进", "related": "老客/30天未到店客户",
            "priority": "高", "action": "筛出10位优先回访老客，今天完成第一轮微信私聊。",
            "script": "姐，最近一直没见你来店里，我帮你看了一下上次护理记录。这周有个适合你状态的护理安排，我先不推项目，先帮你约个时间看看状态。",
            "deadline": "今天18:00前", "status": "待执行"
        }
    if "目标" in title or "营收" in title:
        return {
            "task_id": task_id, "issue_id": issue["id"], "type": "业绩推动", "related": "本月目标缺口",
            "priority": "高", "action": "把本月目标缺口拆成今日目标，并确认今天重点跟进的客户名单。",
            "script": "", "deadline": "今天闭店前", "status": "待执行"
        }
    if "员工" in title or "人均" in title:
        return {
            "task_id": task_id, "issue_id": issue["id"], "type": "员工沟通", "related": "美容师/顾问",
            "priority": "中", "action": "找产出偏低员工做10分钟沟通，明确今天3个跟进客户和1个主推项目。",
            "script": "今天先别追大目标，你就盯住3个客户，先把她们的需求问清楚，再按话术给我回结果。",
            "deadline": "今天15:00前", "status": "待执行"
        }
    return {
        "task_id": task_id, "issue_id": issue["id"], "type": "其他", "related": "",
        "priority": "中", "action": "围绕该问题完成一次信息整理和动作确认。",
        "script": "", "deadline": "今天内", "status": "待执行"
    }


def generate_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    form = payload.get("form_data") or {}
    metrics = calc_metrics(form)
    report_id = make_id("smr")
    store_id = payload.get("store_id") or "default_store"
    diagnosis_month = payload.get("diagnosis_month") or current_month()

    core_issues = choose_core_issues(form, metrics)
    weekly_actions = [
        {"issue_id": issue["id"], "action": weekly_actions_for_issue(issue)}
        for issue in core_issues
    ]
    today_tasks = [today_task_for_issue(issue, idx) for idx, issue in enumerate(core_issues, start=1)]
    today_tasks = today_tasks[:5]

    staff_suggestions = [
        {"role": "美容师", "suggestion": "先把客户状态问清楚，不要一上来推卡，把护理需求和顾虑记录下来。"},
        {"role": "顾问", "suggestion": "围绕今日高优先级客户做跟进，少说泛话，多问具体需求。"},
        {"role": "店长", "suggestion": "今天先盯动作，不只盯结果；闭店前复盘谁执行了、谁需要继续跟进。"}
    ]
    risk_notes = [
        "本报告用于帮助识别问题、拆解动作、形成复盘依据，不承诺营收、成交率、复购率上涨。",
        "数据不足的维度已按保守方式判断，建议后续持续补齐门店经营数据。"
    ]

    display_text = {
        "section_1_core_issues": "\n".join(["问题%d：%s" % (i + 1, item["title"]) for i, item in enumerate(core_issues)]),
        "section_2_reasons": "\n".join(["问题%d原因：%s（%s）" % (i + 1, item["reason"], item["data_basis"]) for i, item in enumerate(core_issues)]),
        "section_3_weekly_actions": "\n".join(["问题%d本周：%s" % (item["issue_id"], item["action"]) for item in weekly_actions]),
        "section_4_today_actions": "\n".join(["%s：%s" % (task["type"], task["action"]) for task in today_tasks]),
        "section_5_manager_reminder": "店长今天不要只盯结果，先盯动作。动作不断，数据才有机会变好。",
        "section_6_staff_suggestions": "；".join(["%s：%s" % (s["role"], s["suggestion"]) for s in staff_suggestions]),
        "section_7_risk_notes": "\n".join(risk_notes)
    }

    structured_json = {
        "report_id": report_id,
        "store_id": store_id,
        "diagnosis_month": diagnosis_month,
        "generated_at": now_iso(),
        "core_issues": core_issues,
        "weekly_actions": weekly_actions,
        "today_tasks": today_tasks,
        "staff_suggestions": staff_suggestions,
        "risk_notes": risk_notes
    }

    return {
        "report_id": report_id,
        "store_id": store_id,
        "store_name": payload.get("store_name") or "",
        "diagnosis_month": diagnosis_month,
        "generated_at": structured_json["generated_at"],
        "metrics": metrics,
        "display_text": display_text,
        "structured_json": structured_json
    }
