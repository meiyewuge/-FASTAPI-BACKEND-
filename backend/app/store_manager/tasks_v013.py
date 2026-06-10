"""V0.1.3 今日任务生成 + P0 限流 + 复盘闭环（补丁2）。

P0 限流规则：
1. 每天 P0 默认最多 3 条；
2. 投诉/退款/差评永远 P0（不受限流影响）；
3. 同一顾客多个预警合并为 1 张任务卡；
4. P0 超过 3 条时，按「金额风险 > 顾客价值 > 时效性」排序；
5. 未入选 P0 的红色项降为 P1，但保留红色标签（keep_red_tag=🔥）。
"""
import json

from ._util_v013 import now_iso_cst, today_cst

# 优先级数字与文档统一：P0=0, P1=1, P2=2, P3=3
P0_DAILY_LIMIT = 3
P0 = 0
P1 = 1
P2 = 2
P3 = 3
PRIORITY_LABELS = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}

# 投诉/退款/差评：永远 P0，不受限流影响
COMPLAINT_TYPES = {"complaint", "refund", "bad_review"}

# RFM 顾客价值排序权重
RFM_RANK = {"高价值": 3, "潜力": 2, "待唤醒": 1, "普通": 0, "": 0}


def _today():
    return today_cst()


def _gather_candidates(conn, store_id):
    """收集 P0 候选：未处理红色预警 + 可成交需求(progress>=8)，按顾客合并。"""
    cards = {}  # customer_id -> card

    def ensure(cid, name, rfm):
        if cid not in cards:
            cards[cid] = {
                "customer_id": cid, "customer_name": name, "rfm_label": rfm or "",
                "items": [], "is_complaint": False, "amount_risk": 0.0, "earliest": None,
            }
        return cards[cid]

    # 红色预警（含投诉/退款/差评）
    rows = conn.execute(
        "SELECT w.*, c.name AS customer_name, c.rfm_label, c.remaining_project_amount, c.total_spent "
        "FROM customer_warning w JOIN customer_profile c ON c.id=w.customer_id "
        "WHERE c.store_id=? AND w.is_resolved=0 AND w.warning_level='red' ORDER BY w.created_at ASC",
        (store_id,),
    ).fetchall()
    for w in rows:
        card = ensure(w["customer_id"], w["customer_name"], w["rfm_label"])
        card["items"].append({"kind": "warning", "type": w["warning_type"], "desc": w["warning_desc"], "id": w["id"]})
        if w["warning_type"] in COMPLAINT_TYPES:
            card["is_complaint"] = True
        card["amount_risk"] = max(card["amount_risk"], float(w["remaining_project_amount"] or 0), float(w["total_spent"] or 0))
        card["earliest"] = w["created_at"] if card["earliest"] is None else min(card["earliest"], w["created_at"])

    # 可成交需求（下次可成交）
    drows = conn.execute(
        "SELECT d.*, c.name AS customer_name, c.rfm_label, c.remaining_project_amount, c.total_spent "
        "FROM customer_demand d JOIN customer_profile c ON c.id=d.customer_id "
        "WHERE c.store_id=? AND d.status='active' AND d.progress_score>=8 ORDER BY d.updated_at ASC",
        (store_id,),
    ).fetchall()
    for d in drows:
        card = ensure(d["customer_id"], d["customer_name"], d["rfm_label"])
        card["items"].append({"kind": "demand", "type": "dealable", "desc": f"可成交需求：{d['demand_desc']}", "id": d["id"]})
        card["amount_risk"] = max(card["amount_risk"], float(d["remaining_project_amount"] or 0), float(d["total_spent"] or 0))
        ts = d["updated_at"] or d["created_at"]
        card["earliest"] = ts if card["earliest"] is None else min(card["earliest"], ts)

    return list(cards.values())


def _card_title(card):
    n = len(card["items"])
    if n > 1:
        return f"{card['customer_name']} 有{n}项紧急事项需处理"
    return f"{card['customer_name']}：{card['items'][0]['desc']}"


def generate_today_tasks(conn, store_id="default_store", report_date=None) -> list:
    """生成今日任务并写入 store_action_task（先清当日自动生成任务再重建）。"""
    report_date = report_date or _today()
    cards = _gather_candidates(conn, store_id)

    always_p0 = [c for c in cards if c["is_complaint"]]
    throttleable = [c for c in cards if not c["is_complaint"]]
    # 排序：金额风险 > 顾客价值 > 时效性(越早越前)
    throttleable.sort(key=lambda c: (-c["amount_risk"], -RFM_RANK.get(c["rfm_label"], 0), c["earliest"] or ""))

    remaining_slots = max(0, P0_DAILY_LIMIT - len(always_p0))
    selected_p0 = throttleable[:remaining_slots]
    demoted = throttleable[remaining_slots:]  # 降为 P1，保留红标

    # 幂等保护（P1-1）：不再 DELETE 重建，避免已完成任务状态丢失。
    # 以 source_id 为幂等键：已存在则只更新展示/限流字段、保留 status/completed_at/review_note；
    # 不存在则新建；本次不再出现的旧候选——已完成的保留，未完成的(过期候选)清除。
    existing = {
        r["source_id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM store_action_task WHERE store_id=? AND report_date=? AND source_type='customer_ops'",
            (store_id, report_date),
        ).fetchall()
    }

    def upsert(card, priority, throttled, keep_red):
        sid = f"customer:{card['customer_id']}"
        title = _card_title(card)
        desc = json.dumps(card["items"], ensure_ascii=False)
        cnt = len(card["items"])
        if sid in existing:
            ex = existing.pop(sid)
            # 保留 status / completed_at / review_note，仅刷新展示与限流标记
            conn.execute(
                "UPDATE store_action_task SET title=?, description=?, priority=?, "
                "is_throttled_to_p1=?, keep_red_tag=?, merged_warning_count=?, related_customer_id=? WHERE id=?",
                (title, desc, priority, 1 if throttled else 0, 1 if keep_red else 0, cnt, card["customer_id"], ex["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO store_action_task (store_id, report_date, title, description, priority, source_type, "
                "source_id, related_customer_id, status, is_throttled_to_p1, keep_red_tag, merged_warning_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (store_id, report_date, title, desc, priority, "customer_ops",
                 sid, card["customer_id"], "pending",
                 1 if throttled else 0, 1 if keep_red else 0, cnt),
            )

    for c in always_p0:
        upsert(c, P0, throttled=False, keep_red=True)
    for c in selected_p0:
        upsert(c, P0, throttled=False, keep_red=True)
    for c in demoted:
        upsert(c, P1, throttled=True, keep_red=True)  # 降级但保留红标

    # 本次未再出现的旧候选：已完成的保留（防状态丢失），未完成的过期候选清除
    for sid, ex in existing.items():
        if ex["status"] in ("done", "completed"):
            continue
        conn.execute("DELETE FROM store_action_task WHERE id=?", (ex["id"],))
    conn.commit()

    return get_today_tasks(conn, store_id, report_date)


def get_today_tasks(conn, store_id="default_store", report_date=None) -> list:
    report_date = report_date or _today()
    rows = conn.execute(
        "SELECT * FROM store_action_task WHERE store_id=? AND report_date=? "
        "ORDER BY priority ASC, keep_red_tag DESC, id ASC",
        (store_id, report_date),
    ).fetchall()
    out = []
    for r in rows:
        t = dict(r)
        try:
            t["items"] = json.loads(t.get("description") or "[]")
        except (ValueError, TypeError):
            t["items"] = []
        t["priority_label"] = PRIORITY_LABELS.get(t["priority"], "P?")
        t["red_tag"] = "🔥" if t["keep_red_tag"] else ""
        out.append(t)
    return out


def update_task_status(conn, task_id, status, review_note="") -> dict:
    r = conn.execute("SELECT * FROM store_action_task WHERE id=?", (task_id,)).fetchone()
    if not r:
        return None
    completed_at = now_iso_cst() if status in ("done", "completed") else None
    conn.execute(
        "UPDATE store_action_task SET status=?, review_note=?, completed_at=? WHERE id=?",
        (status, review_note or r["review_note"], completed_at, task_id),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM store_action_task WHERE id=?", (task_id,)).fetchone())


def submit_daily_review(conn, store_id, report_date, review_content="") -> dict:
    """复盘闭环：汇总完成/未完成任务，生成明日 3 件事。"""
    report_date = report_date or _today()
    tasks = get_today_tasks(conn, store_id, report_date)
    completed = [t for t in tasks if t["status"] in ("done", "completed")]
    unfinished = [t for t in tasks if t["status"] not in ("done", "completed")]

    # 明日 3 件事：优先未完成的 P0 → 被降级的红标 P1 → 其余未完成
    ranked = sorted(
        unfinished,
        key=lambda t: (t["priority"], 0 if t["keep_red_tag"] else 1, t["id"]),
    )
    tomorrow_actions = [
        {"title": t["title"], "priority_label": t["priority_label"], "red_tag": t["red_tag"]}
        for t in ranked[:3]
    ]
    # 防饥饿提示：今日因限流降为 P1 的红色项
    demoted_today = [t for t in tasks if t["is_throttled_to_p1"]]
    if demoted_today:
        tomorrow_actions_note = f"今日 {len(demoted_today)} 项 P0 候选因限流降为 P1，建议明天优先处理"
    else:
        tomorrow_actions_note = ""

    conn.execute(
        "INSERT INTO daily_review (store_id, report_date, review_content, completed_tasks, unfinished_tasks, tomorrow_actions) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(store_id, report_date) DO UPDATE SET "
        "review_content=excluded.review_content, completed_tasks=excluded.completed_tasks, "
        "unfinished_tasks=excluded.unfinished_tasks, tomorrow_actions=excluded.tomorrow_actions",
        (store_id, report_date, review_content,
         json.dumps([t["id"] for t in completed]),
         json.dumps([t["id"] for t in unfinished]),
         json.dumps(tomorrow_actions, ensure_ascii=False)),
    )
    conn.commit()
    return {
        "store_id": store_id, "report_date": report_date,
        "completed_count": len(completed), "unfinished_count": len(unfinished),
        "tomorrow_actions": tomorrow_actions, "tomorrow_actions_note": tomorrow_actions_note,
    }


def get_review_history(conn, store_id="default_store", limit=30):
    rows = conn.execute(
        "SELECT * FROM daily_review WHERE store_id=? ORDER BY report_date DESC LIMIT ?",
        (store_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("completed_tasks", "unfinished_tasks", "tomorrow_actions"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except (ValueError, TypeError):
                d[k] = []
        out.append(d)
    return out
