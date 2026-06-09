"""V0.1.3 顾客经营模型业务逻辑。

覆盖：顾客档案(RFM自动) / 在店项目(消耗+预警) / 家居产品(用完预警) /
需求管理(进度≥8进可成交) / 红黄预警(去重) / 今日需求看板。
"""
import json
from datetime import datetime, timedelta


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _row(r):
    return dict(r) if r else None


# ---------------- 顾客档案 ----------------
CUSTOMER_FIELDS = [
    "store_id", "name", "nickname", "phone", "gender", "age_range", "skin_type",
    "source_channel", "first_visit_date", "customer_no", "preferred_projects",
    "preferred_staff", "preferred_time", "price_sensitivity", "comm_preference",
]


def compute_rfm(profile: dict) -> str:
    """简版 RFM 标签：基于最近到店/累计到店/累计消费。"""
    total_spent = float(profile.get("total_spent") or 0)
    total_visits = int(profile.get("total_visits") or 0)
    last_visit = profile.get("last_visit_date")
    recent = False
    if last_visit:
        try:
            recent = (datetime.now() - datetime.strptime(last_visit[:10], "%Y-%m-%d")).days <= 30
        except ValueError:
            recent = False
    if total_spent >= 20000 and total_visits >= 6:
        return "高价值"
    if recent and (total_spent >= 5000 or total_visits >= 3):
        return "潜力"
    if not recent and total_visits >= 1:
        return "待唤醒"
    return "普通"


def create_customer(conn, payload: dict) -> dict:
    data = {k: payload.get(k) for k in CUSTOMER_FIELDS}
    data["store_id"] = data.get("store_id") or "default_store"
    if not data.get("name") or not data.get("phone"):
        raise ValueError("name 和 phone 为必填")
    cols = [k for k in data if data[k] is not None]
    ph = ",".join(["?"] * len(cols))
    cur = conn.execute(
        f"INSERT INTO customer_profile ({','.join(cols)}) VALUES ({ph})",
        tuple(data[k] for k in cols),
    )
    conn.commit()
    return get_customer(conn, cur.lastrowid)


def get_customer(conn, customer_id) -> dict:
    r = conn.execute("SELECT * FROM customer_profile WHERE id=?", (customer_id,)).fetchone()
    return _row(r)


def list_customers(conn, store_id="default_store", keyword=None):
    if keyword:
        rows = conn.execute(
            "SELECT * FROM customer_profile WHERE store_id=? AND (name LIKE ? OR phone LIKE ?) ORDER BY id DESC LIMIT 100",
            (store_id, f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM customer_profile WHERE store_id=? ORDER BY id DESC LIMIT 100", (store_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def refresh_customer_profile(conn, customer_id):
    """根据在店项目刷新 remaining_project_amount + rfm_label。"""
    prof = get_customer(conn, customer_id)
    if not prof:
        return None
    remaining = conn.execute(
        "SELECT COALESCE(SUM(remaining_quantity*unit_amount),0) AS amt FROM customer_project WHERE customer_id=? AND status='active'",
        (customer_id,),
    ).fetchone()["amt"]
    prof["remaining_project_amount"] = remaining
    rfm = compute_rfm(prof)
    conn.execute(
        "UPDATE customer_profile SET remaining_project_amount=?, rfm_label=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (remaining, rfm, customer_id),
    )
    conn.commit()
    return get_customer(conn, customer_id)


# ---------------- 红黄预警（去重 + 升级） ----------------
def create_warning(conn, customer_id, warning_type, warning_level, warning_source, warning_desc) -> dict:
    """去重：同一顾客同 type+source 且同 level 的未处理预警不重复生成；
    不同 level（如 yellow→red 升级）允许新增。"""
    existing = conn.execute(
        "SELECT * FROM customer_warning WHERE customer_id=? AND warning_type=? AND warning_source=? AND is_resolved=0",
        (customer_id, warning_type, warning_source),
    ).fetchall()
    for e in existing:
        if e["warning_level"] == warning_level:
            return dict(e)  # 同级未处理，已存在
    cur = conn.execute(
        "INSERT INTO customer_warning (customer_id, warning_type, warning_level, warning_source, warning_desc) VALUES (?,?,?,?,?)",
        (customer_id, warning_type, warning_level, warning_source, warning_desc),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM customer_warning WHERE id=?", (cur.lastrowid,)).fetchone())


def list_warnings(conn, store_id="default_store", only_unresolved=True):
    q = (
        "SELECT w.*, c.name AS customer_name, c.rfm_label FROM customer_warning w "
        "JOIN customer_profile c ON c.id=w.customer_id WHERE c.store_id=?"
    )
    if only_unresolved:
        q += " AND w.is_resolved=0"
    q += " ORDER BY CASE w.warning_level WHEN 'red' THEN 0 ELSE 1 END, w.created_at DESC LIMIT 200"
    return [dict(r) for r in conn.execute(q, (store_id,)).fetchall()]


# ---------------- 在店项目 + 消耗 ----------------
def add_project(conn, customer_id, payload: dict) -> dict:
    total_q = int(payload.get("total_quantity") or 1)
    used = int(payload.get("used_quantity") or 0)
    total_amount = float(payload.get("total_amount") or 0)
    unit = float(payload.get("unit_amount") or (total_amount / total_q if total_q else 0))
    cur = conn.execute(
        "INSERT INTO customer_project (customer_id, project_name, project_type, purchase_date, "
        "total_quantity, total_amount, unit_amount, used_quantity, remaining_quantity, expiry_date, "
        "responsible_staff, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (customer_id, payload.get("project_name"), payload.get("project_type", ""),
         payload.get("purchase_date") or _today(), total_q, total_amount, unit, used,
         total_q - used, payload.get("expiry_date"), payload.get("responsible_staff", ""),
         "active", payload.get("notes", "")),
    )
    conn.commit()
    refresh_customer_profile(conn, customer_id)
    return dict(conn.execute("SELECT * FROM customer_project WHERE id=?", (cur.lastrowid,)).fetchone())


def consume_project(conn, project_id) -> dict:
    """消耗 1 次：used+1，remaining=total-used；remaining<=2 黄，==0 红（自动预警）。"""
    p = conn.execute("SELECT * FROM customer_project WHERE id=?", (project_id,)).fetchone()
    if not p:
        return None
    p = dict(p)
    used = int(p["used_quantity"]) + 1
    remaining = int(p["total_quantity"]) - used
    if remaining < 0:
        remaining, used = 0, int(p["total_quantity"])
    status = "finished" if remaining == 0 else "active"
    conn.execute(
        "UPDATE customer_project SET used_quantity=?, remaining_quantity=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (used, remaining, status, project_id),
    )
    conn.commit()
    # 自动预警
    if remaining == 0:
        create_warning(conn, p["customer_id"], "project_used_up", "red", f"project:{project_id}",
                       f"项目【{p['project_name']}】已消耗完，需及时续项。")
    elif remaining <= 2:
        create_warning(conn, p["customer_id"], "project_low", "yellow", f"project:{project_id}",
                       f"项目【{p['project_name']}】仅剩 {remaining} 次，建议提前沟通续项。")
    refresh_customer_profile(conn, p["customer_id"])
    return dict(conn.execute("SELECT * FROM customer_project WHERE id=?", (project_id,)).fetchone())


def list_projects(conn, customer_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM customer_project WHERE customer_id=? ORDER BY id DESC", (customer_id,)).fetchall()]


# ---------------- 家居产品 + 复购预警 ----------------
def add_home_product(conn, customer_id, payload: dict) -> dict:
    purchase = payload.get("purchase_date") or _today()
    cycle = int(payload.get("estimated_cycle") or 30)
    end_date = payload.get("estimated_end_date")
    if not end_date:
        try:
            end_date = (datetime.strptime(purchase[:10], "%Y-%m-%d") + timedelta(days=cycle)).strftime("%Y-%m-%d")
        except ValueError:
            end_date = None
    cur = conn.execute(
        "INSERT INTO customer_home_product (customer_id, product_name, product_type, brand, specification, "
        "purchase_date, estimated_cycle, estimated_end_date, usage_progress, remaining_estimate, "
        "usage_feedback, repurchase_status, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (customer_id, payload.get("product_name"), payload.get("product_type", ""), payload.get("brand", ""),
         payload.get("specification", ""), purchase, cycle, end_date, payload.get("usage_progress", ""),
         payload.get("remaining_estimate", ""), payload.get("usage_feedback", ""),
         payload.get("repurchase_status", "normal"), payload.get("notes", "")),
    )
    conn.commit()
    pid = cur.lastrowid
    _check_home_product_warning(conn, customer_id, pid, end_date, payload.get("repurchase_status", "normal"))
    return dict(conn.execute("SELECT * FROM customer_home_product WHERE id=?", (pid,)).fetchone())


def _check_home_product_warning(conn, customer_id, pid, end_date, repurchase_status):
    name = conn.execute("SELECT product_name FROM customer_home_product WHERE id=?", (pid,)).fetchone()["product_name"]
    if repurchase_status == "switched_competitor":
        create_warning(conn, customer_id, "home_product_switched", "red", f"home_product:{pid}",
                       f"家居产品【{name}】顾客反馈转竞品，需立即跟进。")
        return
    if not end_date:
        return
    try:
        days_left = (datetime.strptime(end_date[:10], "%Y-%m-%d") - datetime.now()).days
    except ValueError:
        return
    if days_left < 0:
        create_warning(conn, customer_id, "home_product_used_up", "red", f"home_product:{pid}",
                       f"家居产品【{name}】预计已用完，建议复购跟进。")
    elif days_left <= 7:
        create_warning(conn, customer_id, "home_product_low", "yellow", f"home_product:{pid}",
                       f"家居产品【{name}】预计 {days_left} 天内用完，可提前提醒复购。")


def list_home_products(conn, customer_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM customer_home_product WHERE customer_id=? ORDER BY id DESC", (customer_id,)).fetchall()]


# ---------------- 需求管理 ----------------
DEMAND_DEALABLE_SCORE = 8


def add_demand(conn, customer_id, payload: dict) -> dict:
    score = int(payload.get("progress_score") or 0)
    cur = conn.execute(
        "INSERT INTO customer_demand (customer_id, demand_desc, demand_type, related_project, progress_score, "
        "created_at_service, last_updated_at_service, created_by_staff, responsible_staff, status, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (customer_id, payload.get("demand_desc"), payload.get("demand_type", ""), payload.get("related_project", ""),
         score, payload.get("created_at_service") or _today(), _today(),
         payload.get("created_by_staff", ""), payload.get("responsible_staff", ""),
         payload.get("status", "active"), payload.get("notes", "")),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM customer_demand WHERE id=?", (cur.lastrowid,)).fetchone())


def update_demand_progress(conn, demand_id, progress_score) -> dict:
    conn.execute(
        "UPDATE customer_demand SET progress_score=?, last_updated_at_service=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (int(progress_score), _today(), demand_id),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM customer_demand WHERE id=?", (demand_id,)).fetchone())


def list_demands(conn, customer_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM customer_demand WHERE customer_id=? ORDER BY id DESC", (customer_id,)).fetchall()]


# ---------------- 今日需求看板 ----------------
def build_demand_board(conn, store_id="default_store") -> dict:
    """聚合：可成交需求(progress≥8 标💰) + 红黄预警，供今日看板展示。"""
    dealable = conn.execute(
        "SELECT d.*, c.name AS customer_name, c.phone, c.rfm_label FROM customer_demand d "
        "JOIN customer_profile c ON c.id=d.customer_id "
        "WHERE c.store_id=? AND d.status='active' AND d.progress_score>=? "
        "ORDER BY d.progress_score DESC LIMIT 100",
        (store_id, DEMAND_DEALABLE_SCORE),
    ).fetchall()
    warnings = list_warnings(conn, store_id, only_unresolved=True)
    board = {
        "board_date": _today(),
        "dealable_demands": [dict(r, dealable=True, flag="💰") for r in dealable],
        "warnings": warnings,
        "summary": {
            "dealable_count": len(dealable),
            "red_warning_count": sum(1 for w in warnings if w["warning_level"] == "red"),
            "yellow_warning_count": sum(1 for w in warnings if w["warning_level"] == "yellow"),
        },
    }
    conn.execute(
        "INSERT INTO daily_demand_board (store_id, board_date, board_data) VALUES (?,?,?) "
        "ON CONFLICT(store_id, board_date) DO UPDATE SET board_data=excluded.board_data",
        (store_id, _today(), json.dumps(board, ensure_ascii=False)),
    )
    conn.commit()
    return board
