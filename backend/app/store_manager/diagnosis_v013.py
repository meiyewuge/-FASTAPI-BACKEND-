"""V0.1.3 诊断规则引擎（9 类经营问题）。

- 阈值从 StoreBenchmarkConfig 读取（补丁1），首次无配置 fallback 到表 DEFAULT 值。
- 9 类问题：客流/成交/新客承接/客单/锁客/复购/项目结构/员工人效/服务风险。
- 输出按 severity 降序，取 top3 作为"今日最核心 3 个问题"。
- 文案边界（补丁7）：统一"规则诊断"，禁止"AI 智能诊断"等表述。
"""
import json

from . import db_v013 as db
from .library_ref import get_library_ref

# 补丁7：报告页统一文案边界。
DIAGNOSIS_SOURCE_LABEL = "基于经营数据 + 7大库规则映射生成"
DIAGNOSIS_METHOD_LABEL = "规则诊断"
DIAGNOSIS_DISCLAIMER = "AI深度分析将在V0.1.4接入"

# 部分阈值未在 StoreBenchmarkConfig 中（客流/新客承接/锁客/项目结构），
# 使用规则级默认常量（标注为待确认，可后续配置化）。
RULE_DEFAULTS = {
    "traffic_visits_min": 20,        # 客流问题：日客流低于此值
    "new_conversion_min": 50.0,      # 新客承接：新客成交率(%)低于此值
    "recharge_ratio_min": 30.0,      # 锁客问题：充值占比(%)低于此值
    "main_project_ratio_min": 50.0,  # 项目结构：主推项目占比(%)低于此值
}

BENCHMARK_DEFAULTS = {
    "store_id": "default_store", "store_type": "mature_store", "store_stage": "mature",
    "staff_count": 0, "monthly_target": 0, "avg_order_target": 0, "per_capita_target": 0,
    "new_customer_ratio_green_low": 15.00, "new_customer_ratio_green_high": 30.00,
    "return_customer_ratio_green_low": 70.00, "return_customer_ratio_green_high": 85.00,
    "conversion_rate_green": 60.00, "repurchase_rate_green": 50.00,
    "appointment_arrival_rate_green": 80.00, "complaint_risk_max": 5.00,
}


def ensure_default_benchmark(conn, store_id="default_store"):
    """ECS 首次启动/首次读取时插入默认配置（补丁1：默认值初始化）。"""
    row = conn.execute("SELECT * FROM store_benchmark_config WHERE store_id=?", (store_id,)).fetchone()
    if row:
        return dict(row)
    cfg = dict(BENCHMARK_DEFAULTS, store_id=store_id)
    cols = ",".join(cfg.keys())
    ph = ",".join(["?"] * len(cfg))
    conn.execute(f"INSERT INTO store_benchmark_config ({cols}) VALUES ({ph})", tuple(cfg.values()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM store_benchmark_config WHERE store_id=?", (store_id,)).fetchone())


def get_benchmark(conn, store_id="default_store") -> dict:
    return ensure_default_benchmark(conn, store_id)


def update_benchmark(conn, store_id, patch: dict) -> dict:
    cfg = ensure_default_benchmark(conn, store_id)
    editable = [k for k in BENCHMARK_DEFAULTS if k != "store_id"]
    sets, vals = [], []
    for k in editable:
        if k in patch and patch[k] is not None:
            sets.append(f"{k}=?")
            vals.append(patch[k])
    if sets:
        sets.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(store_id)
        conn.execute(f"UPDATE store_benchmark_config SET {','.join(sets)} WHERE store_id=?", tuple(vals))
        conn.commit()
    return dict(conn.execute("SELECT * FROM store_benchmark_config WHERE store_id=?", (store_id,)).fetchone())


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _issue(itype, name, severity, evidence, root_cause, today_action, day15_action):
    sev = max(1, min(10, int(severity)))
    return {
        "issue_type": itype,
        "issue_name": name,
        "severity": sev,
        # 优先级数字与文档统一：P0=0, P1=1（严重度>=8 视为 P0）
        "priority": 0 if sev >= 8 else 1,
        "data_evidence": evidence,
        "root_cause": root_cause,
        "root_cause_detail": "",
        "library_ref": get_library_ref(itype),
        "today_action": today_action,
        "day15_action": day15_action,
    }


def match_rules(raw: dict, metrics: dict, cfg: dict) -> list:
    """匹配 9 类诊断规则，返回命中问题列表（未排序）。"""
    issues = []
    rd = RULE_DEFAULTS

    visits = _f(raw.get("daily_visits"))
    complaints = _f(raw.get("daily_complaints"))

    # 1. 客流问题
    if visits < rd["traffic_visits_min"]:
        issues.append(_issue(
            "traffic", "客流问题", 8,
            {"daily_visits": visits, "threshold": rd["traffic_visits_min"]},
            "进店客流不足，获客与到店转化需要加强。",
            "盘点引流渠道，今天先激活老客转介绍与到店预约。",
            "建立稳定的私域引流与预约机制。"))

    # 2. 成交问题（conversion_rate < 成交率健康线）
    if _f(metrics.get("conversion_rate")) < _f(cfg.get("conversion_rate_green")):
        issues.append(_issue(
            "deal", "成交问题", 8,
            {"conversion_rate": metrics.get("conversion_rate"), "threshold": _f(cfg.get("conversion_rate_green"))},
            "到店成交率低于健康线，咨询/逼单/信任建立环节需要复盘。",
            "复盘今日未成交顾客，明确卡点并跟进。",
            "打磨成交话术与体验流程。"))

    # 3. 新客承接问题
    if _f(metrics.get("new_conversion_rate")) < rd["new_conversion_min"]:
        issues.append(_issue(
            "new_customer", "新客承接问题", 7,
            {"new_conversion_rate": metrics.get("new_conversion_rate"), "threshold": rd["new_conversion_min"]},
            "新客首次成交率偏低，新客承接与体验设计需要优化。",
            "为新客设计低门槛体验与跟进动作。",
            "建立新客 7 天承接 SOP。"))

    # 4. 客单问题（仅当设置了客单目标时判定）
    avg_order_target = _f(cfg.get("avg_order_target"))
    if avg_order_target > 0 and _f(metrics.get("avg_order_value")) < avg_order_target:
        issues.append(_issue(
            "price", "客单问题", 7,
            {"avg_order_value": metrics.get("avg_order_value"), "threshold": avg_order_target},
            "客单价低于目标，连带与升单能力需要提升。",
            "梳理可连带项目，今天演练升单话术。",
            "优化项目结构与套餐设计。"))

    # 5. 锁客问题（充值占比偏低）
    if _f(metrics.get("recharge_ratio")) < rd["recharge_ratio_min"]:
        issues.append(_issue(
            "lock", "锁客问题", 6,
            {"recharge_ratio": metrics.get("recharge_ratio"), "threshold": rd["recharge_ratio_min"]},
            "充值占比偏低，顾客锁定与预存机制不足。",
            "梳理高价值顾客，设计今日锁客方案。",
            "建立会员储值与权益体系。"))

    # 6. 复购问题（复购客占比 < 老客占比健康线下限）
    return_ratio = 0.0
    if visits > 0:
        return_ratio = round(_f(metrics.get("estimated_return_customers")) / visits * 100, 2)
    if return_ratio < _f(cfg.get("return_customer_ratio_green_low")):
        issues.append(_issue(
            "repeat", "复购问题", 7,
            {"return_customer_ratio": return_ratio, "threshold": _f(cfg.get("return_customer_ratio_green_low"))},
            "复购/回店客占比偏低，老客经营与回店理由需要加强。",
            "筛出近期未回店老客，今天完成第一轮回访。",
            "建立老客分层回访与复购机制。"))

    # 7. 项目结构问题
    if _f(metrics.get("main_project_ratio")) < rd["main_project_ratio_min"]:
        issues.append(_issue(
            "project", "项目结构问题", 6,
            {"main_project_ratio": metrics.get("main_project_ratio"), "threshold": rd["main_project_ratio_min"]},
            "主推项目占比偏低，项目结构不够聚焦。",
            "明确本周主推项目并统一话术。",
            "优化项目矩阵与主推策略。"))

    # 8. 员工人效问题（仅当设置了人效目标时判定）
    per_capita_target = _f(cfg.get("per_capita_target"))
    if per_capita_target > 0 and _f(metrics.get("per_capita_efficiency")) < per_capita_target:
        issues.append(_issue(
            "staff", "员工人效问题", 6,
            {"per_capita_efficiency": metrics.get("per_capita_efficiency"), "threshold": per_capita_target},
            "人均产出低于目标，员工动作与目标拆解需要加强。",
            "把目标拆到员工，确认今日跟进客户。",
            "建立员工日清与人效复盘机制。"))

    # 9. 服务风险问题（complaint_risk_index > 3 或有投诉）
    if _f(metrics.get("complaint_risk_index")) > 3 or complaints > 0:
        sev = 9 if complaints > 0 else 8
        issues.append(_issue(
            "risk", "服务风险问题", sev,
            {"complaint_risk_index": metrics.get("complaint_risk_index"), "daily_complaints": complaints},
            "存在投诉或客诉风险偏高，服务体验与客诉处理需要立即关注。",
            "立即处理今日投诉/风险顾客，闭环安抚。",
            "建立服务质检与客诉预警机制。"))

    return issues


def run_diagnosis(raw: dict, metrics: dict, cfg: dict) -> dict:
    """生成诊断结构：全部问题 + top3 核心问题。"""
    issues = match_rules(raw, metrics, cfg)
    issues_sorted = sorted(issues, key=lambda x: x["severity"], reverse=True)
    for i, it in enumerate(issues_sorted):
        it["sort_order"] = i
    top3 = issues_sorted[:3]
    return {
        "method": DIAGNOSIS_METHOD_LABEL,
        "source_label": DIAGNOSIS_SOURCE_LABEL,
        "disclaimer": DIAGNOSIS_DISCLAIMER,
        "issues": issues_sorted,
        "top_issues": [
            {"issue_type": t["issue_type"], "issue_name": t["issue_name"], "severity": t["severity"]}
            for t in top3
        ],
    }
