from __future__ import annotations

from typing import Any


def num(data: dict[str, Any], key: str, default: float = 0) -> float:
    value = data.get(key, default)
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_value(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "是", "有"}
    return bool(value)


def interpolate(value: float, low: float, high: float, low_score: int, high_score: int) -> int:
    if high == low:
        return high_score
    ratio = (value - low) / (high - low)
    score = low_score + ratio * (high_score - low_score)
    return max(min(round(score), max(low_score, high_score)), min(low_score, high_score))


def score_by_ranges(value: float, ranges: list[tuple[float, float | None, int, int]]) -> int:
    """Ranges are [low, high), high None means infinity. Scores interpolate within range."""
    for low, high, min_score, max_score in ranges:
        if value >= low and (high is None or value < high):
            if high is None:
                return max_score
            return interpolate(value, low, high, min_score, max_score)
    return 0


def get_rating(total_score: int) -> str:
    if total_score >= 90:
        return "A+"
    if total_score >= 80:
        return "A"
    if total_score >= 70:
        return "B"
    if total_score >= 60:
        return "C"
    return "D"


def warning_level(total_score: int) -> str:
    if total_score <= 59:
        return "red"
    if total_score <= 79:
        return "yellow"
    return "green"


def confidence_level(data: dict[str, Any], required_keys: list[str]) -> str:
    filled = 0
    for key in required_keys:
        value = data.get(key)
        if value not in (None, "", []):
            filled += 1
    ratio = filled / max(len(required_keys), 1)
    if ratio >= 0.9:
        return "高"
    if ratio >= 0.7:
        return "中"
    return "低"


def validate_diagnosis_data(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    monthly_revenue = num(data, "monthly_revenue")
    monthly_visits = num(data, "monthly_visits")
    average_ticket = num(data, "average_ticket")
    visit_conversion_rate = num(data, "visit_conversion_rate") / 100
    theoretical_revenue = monthly_visits * visit_conversion_rate * average_ticket
    if monthly_revenue and theoretical_revenue:
        diff = abs(monthly_revenue - theoretical_revenue) / max(monthly_revenue, 1)
        if diff > 0.3:
            warnings.append("月均业绩、月均到店客流、到店转化率、月均客单价之间偏差超过30%，建议核对数据。")

    total_members = num(data, "total_members")
    active_members_3m = num(data, "active_members_3m")
    if total_members and active_members_3m > total_members:
        warnings.append("近3个月活跃会员数大于总会员数，请核对会员数据。")

    product_ratio_sum = num(data, "traffic_product_revenue_ratio") + num(data, "profit_product_revenue_ratio") + num(data, "premium_product_revenue_ratio")
    if product_ratio_sum and abs(product_ratio_sum - 100) > 5:
        warnings.append("引流款、利润款、高端款业绩占比之和不接近100%，建议核对品项数据。")

    customer_ratio_sum = num(data, "old_customer_ratio") + num(data, "new_customer_ratio")
    if customer_ratio_sum and abs(customer_ratio_sum - 100) > 5:
        warnings.append("新客占比与老客占比之和不接近100%，建议核对客户结构。")
    return warnings


def score_diagnosis(data: dict[str, Any]) -> dict[str, Any]:
    required = [
        "monthly_revenue", "monthly_visits", "average_ticket", "total_members", "active_members_3m",
        "old_customer_ratio", "new_customer_ratio", "repurchase_rate_3m", "visit_conversion_rate",
        "new_customer_conversion_rate", "champion_monthly_sales", "staff_avg_monthly_sales",
        "monthly_marketing_cost", "has_crm", "has_douyin_account", "has_douyin_local_life"
    ]
    warnings = validate_diagnosis_data(data)

    # 复购力 20
    repurchase = num(data, "repurchase_rate_3m")
    old_ratio = num(data, "old_customer_ratio")
    total_members = num(data, "total_members")
    active_members = num(data, "active_members_3m")
    active_ratio = (active_members / total_members * 100) if total_members else 0
    repurchase_score = score_by_ranges(repurchase, [(50, None, 10, 10), (30, 50, 7, 9), (10, 30, 3, 6), (0, 10, 0, 2)])
    old_ratio_score = score_by_ranges(old_ratio, [(60, None, 5, 5), (40, 60, 3, 4), (20, 40, 1, 2), (0, 20, 0, 0)])
    active_score = score_by_ranges(active_ratio, [(50, None, 5, 5), (30, 50, 3, 4), (0, 30, 0, 2)])
    retention_score = repurchase_score + old_ratio_score + active_score

    # 客单力 15
    average_ticket = num(data, "average_ticket")
    premium_ratio = num(data, "premium_product_revenue_ratio")
    ticket_score = score_by_ranges(average_ticket, [(500, None, 10, 10), (300, 500, 7, 9), (200, 300, 3, 6), (0, 200, 0, 2)])
    premium_score = score_by_ranges(premium_ratio, [(20, None, 5, 5), (10, 20, 3, 4), (1, 10, 1, 2), (0, 1, 0, 0)])
    ticket_total = ticket_score + premium_score

    # 转化力 15
    visit_conv = num(data, "visit_conversion_rate")
    new_conv = num(data, "new_customer_conversion_rate")
    champion = num(data, "champion_monthly_sales")
    avg_staff = num(data, "staff_avg_monthly_sales")
    gap = (champion / avg_staff) if avg_staff else 999
    visit_conv_score = score_by_ranges(visit_conv, [(60, None, 7, 7), (40, 60, 5, 6), (20, 40, 2, 4), (0, 20, 0, 1)])
    new_conv_score = score_by_ranges(new_conv, [(40, None, 4, 4), (25, 40, 2, 3), (0, 25, 0, 1)])
    gap_score = 4 if gap <= 3 else (3 if gap <= 5 else 1)
    conversion_score = visit_conv_score + new_conv_score + gap_score

    # 团队力 10
    years = num(data, "staff_avg_years")
    turnover = num(data, "staff_turnover_rate_3m")
    employee_count = num(data, "employee_count")
    monthly_revenue = num(data, "monthly_revenue")
    staff_efficiency = monthly_revenue / employee_count if employee_count else 0
    years_score = score_by_ranges(years, [(3, None, 3, 3), (1, 3, 1, 2), (0, 1, 0, 1)])
    turnover_score = 3 if turnover <= 10 else (2 if turnover <= 20 else (1 if turnover <= 30 else 0))
    efficiency_score = 2 if staff_efficiency >= 30000 else (1 if staff_efficiency >= 15000 else 0)
    sop_score = (1 if bool_value(data, "has_sales_script") else 0) + (1 if bool_value(data, "has_service_sop") else 0)
    team_score = years_score + turnover_score + efficiency_score + sop_score

    # 产品力 15：结构10 + 毛利/数量5
    traffic_ratio = num(data, "traffic_product_revenue_ratio")
    profit_ratio = num(data, "profit_product_revenue_ratio")
    premium_ratio = num(data, "premium_product_revenue_ratio")
    deviation = (abs(traffic_ratio - 30) + abs(profit_ratio - 50) + abs(premium_ratio - 20)) / 3
    if deviation <= 10:
        structure_score = 10
    elif deviation <= 20:
        structure_score = 8
    elif deviation <= 30:
        structure_score = 6
    else:
        structure_score = 3
    gross = num(data, "main_product_gross_margin")
    premium_count = num(data, "premium_product_count")
    gross_score = 3 if gross >= 60 else (2 if gross >= 40 else (1 if gross > 0 else 0))
    premium_count_score = 2 if premium_count >= 2 else (1 if premium_count == 1 else 0)
    product_score = min(structure_score + gross_score + premium_count_score, 15)

    # 流量力 15
    monthly_visits = num(data, "monthly_visits")
    new_ratio = num(data, "new_customer_ratio")
    channels = data.get("main_marketing_channels") or []
    if isinstance(channels, str):
        channels = [channels]
    marketing_cost = num(data, "monthly_marketing_cost")
    estimated_new_customers = monthly_visits * new_ratio / 100 if monthly_visits else 0
    cac = marketing_cost / estimated_new_customers if estimated_new_customers else 0
    visits_score = score_by_ranges(monthly_visits, [(500, None, 4, 4), (300, 500, 3, 3), (100, 300, 1, 2), (0, 100, 0, 1)])
    new_ratio_score = score_by_ranges(new_ratio, [(35, None, 3, 3), (20, 35, 2, 2), (10, 20, 1, 1), (0, 10, 0, 0)])
    channel_score = min(len(channels), 3)
    cac_score = 3 if cac and cac <= 80 else (2 if cac and cac <= 150 else (1 if cac and cac <= 300 else 0))
    referral_score = 2 if "老带新" in channels else 0
    traffic_score = visits_score + new_ratio_score + channel_score + cac_score + referral_score

    # 数字化力 10
    digital_score = 0
    digital_score += 2 if bool_value(data, "has_crm") else 0
    digital_score += 1 if bool_value(data, "has_douyin_account") else 0
    followers = num(data, "douyin_followers")
    views = num(data, "douyin_monthly_views")
    digital_score += 2 if followers >= 1000 else (1 if followers >= 100 else 0)
    digital_score += 2 if views >= 100000 else (1 if views >= 10000 else 0)
    digital_score += 2 if bool_value(data, "has_douyin_local_life") else 0
    private_revenue = num(data, "private_domain_monthly_revenue")
    digital_score += 1 if private_revenue > 0 else 0
    digital_score = min(digital_score, 10)

    total_score = int(sum([traffic_score, conversion_score, ticket_total, retention_score, team_score, product_score, digital_score]))
    rating = get_rating(total_score)
    metrics = {
        "active_member_ratio": round(active_ratio, 2),
        "staff_efficiency": round(staff_efficiency, 2),
        "sales_gap": round(gap, 2) if gap != 999 else None,
        "estimated_cac": round(cac, 2) if cac else None,
    }
    dimensions = [
        {"key": "traffic", "name": "流量力", "score": traffic_score, "max_score": 15},
        {"key": "conversion", "name": "转化力", "score": conversion_score, "max_score": 15},
        {"key": "ticket", "name": "客单力", "score": ticket_total, "max_score": 15},
        {"key": "retention", "name": "复购力", "score": retention_score, "max_score": 20},
        {"key": "team", "name": "团队力", "score": team_score, "max_score": 10},
        {"key": "product", "name": "产品力", "score": product_score, "max_score": 15},
        {"key": "digital", "name": "数字化力", "score": digital_score, "max_score": 10},
    ]
    lowest = sorted(dimensions, key=lambda x: x["score"] / x["max_score"])[0]
    return {
        "total_score": total_score,
        "rating": rating,
        "warning_level": warning_level(total_score),
        "confidence_level": confidence_level(data, required),
        "dimensions": dimensions,
        "scores": {
            "traffic_score": traffic_score,
            "conversion_score": conversion_score,
            "ticket_score": ticket_total,
            "retention_score": retention_score,
            "team_score": team_score,
            "product_score": product_score,
            "digital_score": digital_score,
        },
        "metrics": metrics,
        "validation_warnings": warnings,
        "risk_tags": build_diagnosis_risk_tags(dimensions, data, metrics),
        "lowest_dimension": lowest,
    }


def build_diagnosis_risk_tags(dimensions: list[dict[str, Any]], data: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for d in dimensions:
        if d["score"] / d["max_score"] < 0.55:
            tags.append(f"{d['name']}偏弱")
    if num(data, "repurchase_rate_3m") < 30:
        tags.append("老客复购不足")
    if num(data, "average_ticket") < 300:
        tags.append("客单价偏低")
    if num(data, "visit_conversion_rate") < 40:
        tags.append("到店转化偏弱")
    if metrics.get("staff_efficiency") and metrics["staff_efficiency"] < 15000:
        tags.append("人效偏低")
    return tags


def validate_monthly_data(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    revenue = num(data, "revenue")
    paying = num(data, "paying_customers")
    avg_ticket = num(data, "average_ticket")
    if revenue and paying and avg_ticket:
        calculated = paying * avg_ticket
        diff = abs(revenue - calculated) / max(revenue, 1)
        if diff > 0.3:
            warnings.append("本月总业绩、成交人数、客单价之间偏差超过30%，建议核对。")
    if num(data, "new_customers") + num(data, "old_customers") > paying * 1.2 and paying:
        warnings.append("新客数与老客数合计明显高于成交人数，请核对客户数据。")
    return warnings


def score_monthly(data: dict[str, Any], previous: dict[str, Any] | None = None, store_area: float | None = None) -> dict[str, Any]:
    warnings = validate_monthly_data(data)
    revenue = num(data, "revenue")
    visits = num(data, "customer_visits")
    paying = num(data, "paying_customers")
    new_customers = num(data, "new_customers")
    old_customers = num(data, "old_customers")
    avg_ticket = num(data, "average_ticket") or (revenue / paying if paying else 0)
    employees = num(data, "employee_count")
    marketing = num(data, "marketing_cost")
    gross_margin = num(data, "gross_margin_rate") or 60
    rent = num(data, "rent_cost")
    labor = num(data, "labor_cost")
    platform_commission = num(data, "platform_commission")
    water = num(data, "water_electric_cost")
    consumables = num(data, "consumable_cost")

    conversion_rate = paying / visits * 100 if visits else 0
    staff_efficiency = revenue / employees if employees else 0
    new_ratio = new_customers / paying * 100 if paying else 0
    old_ratio = old_customers / paying * 100 if paying else 0
    repurchase_customers = num(data, "repurchase_customers")
    repurchase_rate = repurchase_customers / paying * 100 if paying else 0
    cac = marketing / new_customers if new_customers else 0
    fixed_cost = rent + labor + platform_commission + water
    breakeven = fixed_cost / (gross_margin / 100) if gross_margin else 0
    safety_margin = revenue - breakeven
    gross_profit = revenue * gross_margin / 100 - fixed_cost - consumables

    # 人 15
    people_score = 0
    people_score += score_by_ranges(staff_efficiency, [(30000, None, 6, 6), (15000, 30000, 3, 5), (0, 15000, 0, 2)])
    resigned = num(data, "resigned_count")
    people_score += 3 if resigned == 0 else (2 if employees and resigned / employees <= 0.1 else 1)
    people_score += 3 if num(data, "training_count") >= 2 else (1 if num(data, "training_count") >= 1 else 0)
    complaints = num(data, "complaint_count")
    people_score += 3 if complaints == 0 else (2 if complaints <= 2 else 0)

    # 货 15
    profit_rev = num(data, "profit_project_revenue")
    premium_rev = num(data, "premium_project_revenue")
    traffic_rev = num(data, "traffic_project_revenue")
    product_total = profit_rev + premium_rev + traffic_rev
    product_score = 0
    if product_total:
        product_score += 5 if profit_rev / product_total >= 0.45 else (3 if profit_rev / product_total >= 0.3 else 1)
        product_score += 5 if premium_rev / product_total >= 0.2 else (3 if premium_rev / product_total >= 0.1 else 1)
    product_score += 3 if num(data, "main_project_revenue") >= revenue * 0.2 and revenue else 1
    product_score += 2 if (not revenue or num(data, "inventory_backlog_amount") <= revenue * 0.1) else 0
    product_score = min(product_score, 15)

    # 场 15
    satisfaction = num(data, "satisfaction_score")
    meituan = num(data, "meituan_rating")
    bad_reviews = num(data, "bad_review_count")
    followups = num(data, "followup_customer_count")
    place_score = 0
    place_score += score_by_ranges(satisfaction, [(9, None, 5, 5), (7, 9, 3, 4), (0, 7, 0, 2)])
    place_score += score_by_ranges(meituan, [(4.8, None, 4, 4), (4.5, 4.8, 2, 3), (0, 4.5, 0, 1)])
    place_score += 3 if bad_reviews == 0 else (2 if bad_reviews <= 2 else 0)
    place_score += 3 if followups >= paying * 0.5 and paying else (1 if followups > 0 else 0)

    # 客 20
    customer_score = 0
    customer_score += score_by_ranges(repurchase_rate, [(50, None, 7, 7), (30, 50, 4, 6), (10, 30, 2, 3), (0, 10, 0, 1)])
    customer_score += score_by_ranges(new_ratio, [(30, None, 4, 4), (15, 30, 2, 3), (0, 15, 0, 1)])
    customer_score += score_by_ranges(old_ratio, [(50, None, 4, 4), (30, 50, 2, 3), (0, 30, 0, 1)])
    customer_score += 3 if num(data, "reactivated_members") >= 10 else (1 if num(data, "reactivated_members") > 0 else 0)
    customer_score += 2 if num(data, "referral_customers") >= 5 else (1 if num(data, "referral_customers") > 0 else 0)

    # 财 20
    finance_score = 0
    finance_score += score_by_ranges(revenue, [(200000, None, 5, 5), (100000, 200000, 3, 4), (50000, 100000, 1, 2), (0, 50000, 0, 1)])
    finance_score += score_by_ranges(gross_margin, [(60, None, 4, 4), (45, 60, 2, 3), (0, 45, 0, 1)])
    finance_score += 5 if safety_margin >= 0 else 0
    finance_score += 3 if cac and cac <= 100 else (2 if cac and cac <= 200 else (1 if cac and cac <= 400 else 0))
    finance_score += 3 if gross_profit > 0 else 0

    # 数 15
    digital_score = 0
    digital_score += score_by_ranges(num(data, "douyin_views"), [(100000, None, 4, 4), (10000, 100000, 2, 3), (0, 10000, 0, 1)])
    digital_score += score_by_ranges(num(data, "douyin_orders"), [(50, None, 4, 4), (10, 50, 2, 3), (0, 10, 0, 1)])
    digital_score += score_by_ranges(num(data, "private_domain_new_contacts"), [(100, None, 3, 3), (30, 100, 2, 2), (0, 30, 0, 1)])
    digital_score += 2 if num(data, "live_sessions") >= 4 else (1 if num(data, "live_sessions") > 0 else 0)
    digital_score += 2 if num(data, "short_video_count") >= 12 else (1 if num(data, "short_video_count") > 0 else 0)

    dimensions = [
        {"key": "people", "name": "人", "score": int(people_score), "max_score": 15},
        {"key": "product", "name": "货", "score": int(product_score), "max_score": 15},
        {"key": "place", "name": "场", "score": int(place_score), "max_score": 15},
        {"key": "customer", "name": "客", "score": int(customer_score), "max_score": 20},
        {"key": "finance", "name": "财", "score": int(finance_score), "max_score": 20},
        {"key": "digital", "name": "数", "score": int(digital_score), "max_score": 15},
    ]
    total = int(sum(d["score"] for d in dimensions))
    metrics = {
        "conversion_rate": round(conversion_rate, 2),
        "average_ticket": round(avg_ticket, 2),
        "staff_efficiency": round(staff_efficiency, 2),
        "new_customer_ratio": round(new_ratio, 2),
        "old_customer_ratio": round(old_ratio, 2),
        "repurchase_rate": round(repurchase_rate, 2),
        "cac": round(cac, 2) if cac else None,
        "gross_profit_estimate": round(gross_profit, 2),
        "breakeven": round(breakeven, 2),
        "safety_margin": round(safety_margin, 2),
    }
    mom_changes = {}
    if previous:
        for k in ["revenue", "average_ticket", "repurchase_rate", "staff_efficiency"]:
            current = metrics.get(k) if k in metrics else data.get(k)
            prev = previous.get(k)
            if current is not None and prev:
                mom_changes[k] = round((float(current) - float(prev)) / float(prev) * 100, 2)
    lowest = sorted(dimensions, key=lambda x: x["score"] / x["max_score"])[0]
    return {
        "total_score": total,
        "rating": get_rating(total),
        "dimensions": dimensions,
        "scores": {
            "people_score": int(people_score),
            "product_score": int(product_score),
            "place_score": int(place_score),
            "customer_score": int(customer_score),
            "finance_score": int(finance_score),
            "digital_score": int(digital_score),
        },
        "metrics": metrics,
        "mom_changes": mom_changes,
        "validation_warnings": warnings,
        "risk_tags": build_monthly_risk_tags(dimensions, metrics),
        "lowest_dimension": lowest,
    }


def build_monthly_risk_tags(dimensions: list[dict[str, Any]], metrics: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for d in dimensions:
        if d["score"] / d["max_score"] < 0.55:
            tags.append(f"{d['name']}维度偏弱")
    if metrics.get("safety_margin", 0) < 0:
        tags.append("低于盈亏平衡线")
    if metrics.get("repurchase_rate", 0) < 30:
        tags.append("复购率偏低")
    if metrics.get("cac") and metrics["cac"] > 200:
        tags.append("获客成本偏高")
    return tags
