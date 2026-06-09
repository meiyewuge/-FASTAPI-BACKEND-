"""V0.1.3 自动计算指标（13 个）。

严格按《后端开发文档》第4.1节公式实现：
- 所有"率"只由系统计算，不接受前端填写；
- 除零保护：任何分母为 0 时结果直接置 0。
"""


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _div(numerator, denominator, percent=False, ndigits=2):
    """除零安全：分母<=0 返回 0。percent=True 时乘 100。"""
    d = _num(denominator)
    if d == 0:
        return 0
    val = _num(numerator) / d * (100 if percent else 1)
    return round(val, ndigits)


def compute_metrics(raw: dict) -> dict:
    """输入 15 项原始数据 dict，输出 13 个计算指标 dict。"""
    g = lambda k: _num(raw.get(k))
    visits = g("daily_visits")
    new_customers = g("daily_new_customers")

    return {
        "conversion_rate": _div(raw.get("daily_transaction_customers"), visits, percent=True),
        "new_customer_ratio": _div(new_customers, visits, percent=True),
        "new_conversion_rate": _div(raw.get("daily_new_transaction"), new_customers, percent=True),
        "avg_order_value": _div(raw.get("daily_revenue"), raw.get("daily_transaction_customers")),
        "appointment_arrival_rate": _div(raw.get("daily_appointment_arrivals"), raw.get("daily_valid_appointments"), percent=True),
        "per_capita_efficiency": _div(raw.get("daily_revenue"), raw.get("daily_staff_count")),
        "recharge_ratio": _div(raw.get("daily_recharge_amount"), raw.get("daily_revenue"), percent=True),
        "project_ratio": _div(raw.get("daily_project_sales"), raw.get("daily_revenue"), percent=True),
        "product_ratio": _div(raw.get("daily_product_retail"), raw.get("daily_revenue"), percent=True),
        "main_project_ratio": _div(raw.get("daily_main_project_sales"), raw.get("daily_project_sales"), percent=True),
        "complaint_risk_index": _div(g("daily_complaints") * 100, raw.get("daily_service_count")),
        # 预估复购客数 = 总客流 - 新客（不涉及除法，可能为负则保守置 0）
        "estimated_return_customers": int(max(0, visits - new_customers)),
        "service_efficiency": _div(raw.get("daily_service_count"), raw.get("daily_staff_count")),
    }


# 15 项原始数据字段（用于校验/录入）
RAW_FIELDS = [
    "daily_revenue", "daily_recharge_amount", "daily_product_retail",
    "daily_visits", "daily_new_customers", "daily_valid_appointments",
    "daily_appointment_arrivals", "daily_transaction_customers",
    "daily_transaction_orders", "daily_new_transaction", "daily_project_sales",
    "daily_main_project_sales", "daily_service_count", "daily_staff_count",
    "daily_complaints",
]

# 13 项计算指标字段（只读，不允许前端填写）
METRIC_FIELDS = [
    "conversion_rate", "new_customer_ratio", "new_conversion_rate",
    "avg_order_value", "appointment_arrival_rate", "per_capita_efficiency",
    "recharge_ratio", "project_ratio", "product_ratio", "main_project_ratio",
    "complaint_risk_index", "estimated_return_customers", "service_efficiency",
]
