import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any


DB_PATH = os.getenv("STORE_MANAGER_DB_PATH", "/opt/meiye-wuyou/data/store_manager_workbench.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS store_manager_reports (
        report_id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL,
        store_name TEXT,
        diagnosis_month TEXT,
        generated_at TEXT,
        form_data TEXT,
        metrics TEXT,
        display_text TEXT,
        structured_json TEXT,
        admin_mark TEXT,
        admin_note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS store_manager_tasks (
        task_id TEXT PRIMARY KEY,
        report_id TEXT,
        store_id TEXT,
        task_json TEXT,
        status TEXT,
        review_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()


def save_report(payload: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    conn = _connect()
    try:
        conn.execute("""
        INSERT OR REPLACE INTO store_manager_reports
        (report_id, store_id, store_name, diagnosis_month, generated_at, form_data, metrics, display_text, structured_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report["report_id"],
            report["store_id"],
            report.get("store_name", ""),
            report["diagnosis_month"],
            report["generated_at"],
            json.dumps(payload.get("form_data") or {}, ensure_ascii=False),
            json.dumps(report.get("metrics") or {}, ensure_ascii=False),
            json.dumps(report.get("display_text") or {}, ensure_ascii=False),
            json.dumps(report.get("structured_json") or {}, ensure_ascii=False),
            datetime.now().isoformat()
        ))

        for task in report.get("structured_json", {}).get("today_tasks", []):
            conn.execute("""
            INSERT OR REPLACE INTO store_manager_tasks
            (task_id, report_id, store_id, task_json, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                task["task_id"],
                report["report_id"],
                report["store_id"],
                json.dumps(task, ensure_ascii=False),
                task.get("status", "待执行"),
                datetime.now().isoformat()
            ))
        conn.commit()
    finally:
        conn.close()
    return report


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM store_manager_reports WHERE report_id = ?", (report_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["display_text"] = json.loads(data.get("display_text") or "{}")
        data["structured_json"] = json.loads(data.get("structured_json") or "{}")
        data["metrics"] = json.loads(data.get("metrics") or "{}")
        data["form_data"] = json.loads(data.get("form_data") or "{}")
        return data
    finally:
        conn.close()


def list_reports(store_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("""
        SELECT report_id, store_id, store_name, diagnosis_month, generated_at, admin_mark
        FROM store_manager_reports
        WHERE store_id = ?
        ORDER BY generated_at DESC
        LIMIT 50
        """, (store_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_tasks(store_id: str) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("""
        SELECT * FROM store_manager_tasks
        WHERE store_id = ?
        ORDER BY created_at DESC
        LIMIT 50
        """, (store_id,)).fetchall()
        tasks = []
        for row in rows:
            data = dict(row)
            task = json.loads(data.get("task_json") or "{}")
            task["status"] = data.get("status") or task.get("status", "待执行")
            tasks.append(task)
        return tasks
    finally:
        conn.close()


def update_task_status(task_id: str, status: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM store_manager_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = json.loads(dict(row).get("task_json") or "{}")
        task["status"] = status
        conn.execute("""
        UPDATE store_manager_tasks
        SET status = ?, task_json = ?, updated_at = ?
        WHERE task_id = ?
        """, (status, json.dumps(task, ensure_ascii=False), datetime.now().isoformat(), task_id))
        conn.commit()
        return task
    finally:
        conn.close()


def save_task_review(task_id: str, review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM store_manager_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        review["created_at"] = datetime.now().isoformat()
        conn.execute("""
        UPDATE store_manager_tasks
        SET review_json = ?, updated_at = ?
        WHERE task_id = ?
        """, (json.dumps(review, ensure_ascii=False), datetime.now().isoformat(), task_id))
        conn.commit()
        return review
    finally:
        conn.close()


def mark_report(report_id: str, mark: str, note: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute("SELECT report_id FROM store_manager_reports WHERE report_id = ?", (report_id,)).fetchone()
        if not row:
            return None
        conn.execute("""
        UPDATE store_manager_reports
        SET admin_mark = ?, admin_note = ?, updated_at = ?
        WHERE report_id = ?
        """, (mark, note, datetime.now().isoformat(), report_id))
        conn.commit()
        return {"report_id": report_id, "mark": mark, "note": note}
    finally:
        conn.close()
