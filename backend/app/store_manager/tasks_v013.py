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


def sync_diagnosis_tasks(conn, store_id, report_date) -> None:
    """桥接：根据最新诊断的 top3 问题(issue.today_action) 生成/同步 store_action_task。

    幂等：以 source_id='diagnosis_issue:{issue_id}' 为键，保留已完成状态；
    不再属于 top3 的旧诊断任务（未完成）清除。诊断 POST 时即调用，保证 today-tasks 非空。
    """
    report_date = report_date or _today()
    existing = {
        r["source_id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM store_action_task WHERE store_id=? AND report_date=? AND source_type='diagnosis_issue'",
            (store_id, report_date),
        ).fetchall()
    }
    diag = conn.execute(
        "SELECT id FROM store_diagnosis_result WHERE store_id=? AND report_date=? ORDER BY id DESC LIMIT 1",
        (store_id, report_date),
    ).fetchone()
    wanted = set()
    if diag:
        issues = conn.execute(
            "SELECT * FROM store_diagnosis_issue WHERE diagnosis_id=? ORDER BY sort_order ASC, severity DESC LIMIT 3",
            (diag["id"],),
        ).fetchall()
        for it in issues:
            sid = f"diagnosis_issue:{it['id']}"
            wanted.add(sid)
            title = it["issue_name"]
            desc = it["today_action"] or it["issue_name"]
            pr = it["priority"] if it["priority"] in (0, 1, 2, 3) else (P0 if it["severity"] >= 8 else P1)
            if sid in existing:
                ex = existing[sid]
                # P2: done/completed 行不再刷新 title/description/priority
                if ex["status"] not in ("done", "completed"):
                    conn.execute(
                        "UPDATE store_action_task SET title=?, description=?, priority=? WHERE id=?",
                        (title, desc, pr, ex["id"]),
                    )  # 保留 status/completed_at/review_note
            else:
                conn.execute(
                    "INSERT INTO store_action_task (store_id, report_date, title, description, priority, source_type, "
                    "source_id, status, force_p0, keep_red_tag, is_throttled_to_p1, merged_warning_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (store_id, report_date, title, desc, pr, "diagnosis_issue",
                     sid, "pending", 0, 0, 0, 1),
                )
    for sid, ex in existing.items():
        if sid not in wanted and ex["status"] not in ("done", "completed"):
            conn.execute("DELETE FROM store_action_task WHERE id=?", (ex["id"],))
    conn.commit()
    # P1-1: 桥接后立即做全局 P0 限流，避免 diagnosis POST 后短暂暴露 >3 个非豁免 P0
    _apply_global_p0_limit(conn, store_id, report_date)


def _apply_global_p0_limit(conn, store_id, report_date) -> None:
    """全局 P0 限流：每天 P0≤3（投诉/退款/差评 force_p0=1 豁免，永远 P0）。

    超限的非豁免 P0 降为 P1（保留红标），按「红标 > 合并数 > 时效(id)」排序保留。
    幂等：每次按基准优先级重算降级，可重复调用。
    """
    pend = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM store_action_task WHERE store_id=? AND report_date=? "
            "AND priority=0 AND status NOT IN ('done','completed')",
            (store_id, report_date),
        ).fetchall()
    ]
    force = [t for t in pend if t.get("force_p0")]
    others = [t for t in pend if not t.get("force_p0")]
    others.sort(key=lambda t: (-(t["keep_red_tag"] or 0), -(t["merged_warning_count"] or 0), t["id"]))
    keep_n = max(0, P0_DAILY_LIMIT - len(force))
    keep, demote = others[:keep_n], others[keep_n:]
    for t in keep + force:
        conn.execute("UPDATE store_action_task SET is_throttled_to_p1=0 WHERE id=?", (t["id"],))
    for t in demote:
        # 降级到 P1 仍保留红色标签(keep_red_tag=1)且标记限流(is_throttled_to_p1=1)
        conn.execute(
            "UPDATE store_action_task SET priority=?, is_throttled_to_p1=1, keep_red_tag=1 WHERE id=?",
            (P1, t["id"]),
        )
    conn.commit()


def generate_today_tasks(conn, store_id="default_store", report_date=None) -> list:
    """生成今日任务：聚合 diagnosis_issue + customer_ops 两类来源，应用 P0 限流。

    幂等：以 source_id 为键 upsert，保留 done/completed；不丢已完成状态。
    """
    report_date = report_date or _today()

    # 1) 桥接诊断问题 → 诊断任务（保证有可执行任务）
    sync_diagnosis_tasks(conn, store_id, report_date)

    # 2) 顾客经营候选（预警/需求/项目消耗）→ upsert
    cards = _gather_candidates(conn, store_id)
    existing = {
        r["source_id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM store_action_task WHERE store_id=? AND report_date=? AND source_type='customer_ops'",
            (store_id, report_date),
        ).fetchall()
    }
    current = set()

    def upsert(card):
        sid = f"customer:{card['customer_id']}"
        current.add(sid)
        title = _card_title(card)
        desc = json.dumps(card["items"], ensure_ascii=False)
        cnt = len(card["items"])
        force = 1 if card["is_complaint"] else 0   # 投诉/退款/差评永远 P0
        if sid in existing:
            ex = existing[sid]
            # P2: done/completed 行不再刷新 title/description/priority 等
            if ex["status"] not in ("done", "completed"):
                conn.execute(
                    "UPDATE store_action_task SET title=?, description=?, priority=?, "
                    "keep_red_tag=1, merged_warning_count=?, related_customer_id=?, force_p0=? WHERE id=?",
                    (title, desc, P0, cnt, card["customer_id"], force, ex["id"]),
                )  # 保留 status/completed_at/review_note
        else:
            conn.execute(
                "INSERT INTO store_action_task (store_id, report_date, title, description, priority, source_type, "
                "source_id, related_customer_id, status, is_throttled_to_p1, keep_red_tag, merged_warning_count, force_p0) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (store_id, report_date, title, desc, P0, "customer_ops",
                 sid, card["customer_id"], "pending", 0, 1, cnt, force),
            )

    for c in cards:
        upsert(c)
    # 本次未再出现的旧 customer_ops 候选：已完成保留，未完成清除
    for sid, ex in existing.items():
        if sid not in current and ex["status"] not in ("done", "completed"):
            conn.execute("DELETE FROM store_action_task WHERE id=?", (ex["id"],))
    conn.commit()

    # 3) 全局 P0 限流（≤3，force 豁免）
    _apply_global_p0_limit(conn, store_id, report_date)

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
        t["action"] = t.get("description") or ""   # diagnosis 任务的 today_action / 顾客任务的 items json
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
