"""V0.1.3 经营诊断编排：原始数据 → 自动指标 → 9类规则诊断 → 落库。"""
import json

from .metrics_v013 import compute_metrics, RAW_FIELDS
from . import diagnosis_v013 as dg
from ._util_v013 import today_cst


def _today():
    return today_cst()


def save_daily_raw_data(conn, store_id, report_date, fields: dict) -> dict:
    store_id = store_id or "default_store"
    report_date = report_date or _today()
    vals = {k: (fields.get(k) or 0) for k in RAW_FIELDS}
    vals["daily_notes"] = fields.get("daily_notes", "")
    cols = ["store_id", "report_date"] + list(vals.keys())
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join([f"{k}=excluded.{k}" for k in vals.keys()] + ["updated_at=CURRENT_TIMESTAMP"])
    conn.execute(
        f"INSERT INTO store_daily_raw_data ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(store_id, report_date) DO UPDATE SET {updates}",
        tuple([store_id, report_date] + list(vals.values())),
    )
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM store_daily_raw_data WHERE store_id=? AND report_date=?", (store_id, report_date)
    ).fetchone())


def save_metrics(conn, store_id, report_date, raw_id, metrics: dict) -> dict:
    cols = ["store_id", "report_date", "raw_data_id"] + list(metrics.keys())
    placeholders = ",".join(["?"] * len(cols))
    updates = ",".join([f"{k}=excluded.{k}" for k in metrics.keys()])
    conn.execute(
        f"INSERT INTO store_computed_metrics ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(store_id, report_date) DO UPDATE SET {updates}",
        tuple([store_id, report_date, raw_id] + list(metrics.values())),
    )
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM store_computed_metrics WHERE store_id=? AND report_date=?", (store_id, report_date)
    ).fetchone())


def get_computed_metrics(conn, store_id="default_store", report_date=None) -> dict:
    if report_date:
        r = conn.execute(
            "SELECT * FROM store_computed_metrics WHERE store_id=? AND report_date=?", (store_id, report_date)
        ).fetchone()
    else:
        r = conn.execute(
            "SELECT * FROM store_computed_metrics WHERE store_id=? ORDER BY report_date DESC LIMIT 1", (store_id,)
        ).fetchone()
    return dict(r) if r else None


def create_diagnosis(conn, payload: dict) -> dict:
    """主流程：保存15项原始数据 → 计算13指标 → 9类规则诊断 → 落库报告与问题。"""
    store_id = payload.get("store_id") or "default_store"
    report_date = payload.get("report_date") or payload.get("diagnosis_month") or _today()
    fields = payload.get("form_data") or payload.get("raw_data") or payload

    raw = save_daily_raw_data(conn, store_id, report_date, fields)
    metrics = compute_metrics(raw)
    metrics_row = save_metrics(conn, store_id, report_date, raw["id"], metrics)
    metrics_id = metrics_row["id"]

    cfg = dg.get_benchmark(conn, store_id)
    diag = dg.run_diagnosis(raw, metrics, cfg)

    data_overview = {k: raw.get(k) for k in RAW_FIELDS}
    cur = conn.execute(
        "INSERT INTO store_diagnosis_result (store_id, report_date, status, data_overview, computed_metrics, "
        "top_issues, customer_opportunities, tomorrow_actions, raw_data_id, metrics_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        (store_id, report_date, "published",
         json.dumps(data_overview, ensure_ascii=False),
         json.dumps(metrics, ensure_ascii=False),
         json.dumps(diag["top_issues"], ensure_ascii=False),
         json.dumps({}, ensure_ascii=False),
         json.dumps([], ensure_ascii=False),
         raw["id"], metrics_id),
    )
    diagnosis_id = cur.lastrowid
    if not diagnosis_id:
        row = conn.execute(
            "SELECT id FROM store_diagnosis_result WHERE store_id=? AND report_date=? ORDER BY id DESC LIMIT 1",
            (store_id, report_date)).fetchone()
        diagnosis_id = row["id"] if row else None
    # 落库问题列表
    conn.execute("DELETE FROM store_diagnosis_issue WHERE diagnosis_id=?", (diagnosis_id,))
    for it in diag["issues"]:
        conn.execute(
            "INSERT INTO store_diagnosis_issue (diagnosis_id, issue_type, issue_name, severity, priority, "
            "data_evidence, root_cause, root_cause_detail, library_ref, today_action, day15_action, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (diagnosis_id, it["issue_type"], it["issue_name"], it["severity"], it["priority"],
             json.dumps(it["data_evidence"], ensure_ascii=False), it["root_cause"], it.get("root_cause_detail", ""),
             json.dumps(it["library_ref"], ensure_ascii=False), it["today_action"], it["day15_action"], it["sort_order"]),
        )
    conn.commit()
    return get_diagnosis(conn, diagnosis_id)


def get_diagnosis(conn, diagnosis_id) -> dict:
    r = conn.execute("SELECT * FROM store_diagnosis_result WHERE id=?", (diagnosis_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("data_overview", "computed_metrics", "customer_opportunities"):
        d[k] = json.loads(d.get(k) or "{}")
    for k in ("top_issues", "tomorrow_actions"):
        d[k] = json.loads(d.get(k) or "[]")
    issues = conn.execute(
        "SELECT * FROM store_diagnosis_issue WHERE diagnosis_id=? ORDER BY sort_order ASC", (diagnosis_id,)
    ).fetchall()
    parsed = []
    for it in issues:
        x = dict(it)
        x["data_evidence"] = json.loads(x.get("data_evidence") or "{}")
        x["library_ref"] = json.loads(x.get("library_ref") or "{}")
        parsed.append(x)
    d["issues"] = parsed
    # 文案边界（补丁7）
    d["method"] = dg.DIAGNOSIS_METHOD_LABEL
    d["source_label"] = dg.DIAGNOSIS_SOURCE_LABEL
    d["disclaimer"] = dg.DIAGNOSIS_DISCLAIMER
    return d
