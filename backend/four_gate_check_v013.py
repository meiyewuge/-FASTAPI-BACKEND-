"""V0.1.3 第四闸门验收脚本（四闸门：顾客经营 + 诊断→任务闭环全链路）。

修正点（回应审查）：
- health 用真实路径 /health（不是 /api/store-manager/health）；
- 主验收使用非零有效经营数据；全零仅作边界测试；
- 电话/store_id/日期每次唯一，避免重复数据污染；
- 验收以 100% PASS 为通过；任一失败 exit 1。

两种运行方式：
1) 对已部署服务（ECS 18081）：GATE_BASE_URL=http://127.0.0.1:18081 python four_gate_check_v013.py
2) 本机进程内自检（无 GATE_BASE_URL）：自动用真实 app.main + TestClient（无 weasyprint 时 stub）。
"""
import os
import sys
import time
import types
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_URL = os.getenv("GATE_BASE_URL", "").rstrip("/")

if BASE_URL:
    import httpx
    client = httpx.Client(base_url=BASE_URL, timeout=20.0)
    MODE = f"HTTP {BASE_URL}"
else:
    # 进程内：真实 app.main（缺 weasyprint 时 stub），独立测试库
    try:
        import weasyprint  # noqa: F401
    except Exception:
        fake = types.ModuleType("weasyprint")
        fake.HTML = lambda *a, **k: types.SimpleNamespace(write_pdf=lambda *a, **k: b"")
        sys.modules["weasyprint"] = fake
    tmp = tempfile.gettempdir()
    os.environ.setdefault("STORE_MANAGER_V013_DB_PATH", os.path.join(tmp, "v013_gate.db"))
    os.environ.setdefault("STORE_MANAGER_DB_PATH", os.path.join(tmp, "v012_gate.db"))
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(tmp, "gate_main.db"))
    for f in (os.environ["STORE_MANAGER_V013_DB_PATH"], os.path.join(tmp, "gate_main.db")):
        try:
            os.remove(f)
        except OSError:
            pass
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    MODE = "in-process TestClient"

B = "/api/store-manager"
_p = _f = 0


def ck(name, cond, detail=""):
    global _p, _f
    ok = bool(cond)
    _p += ok
    _f += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    return ok


def g(path, **params):
    return client.get(path, params=params)


def p(path, **kw):
    return client.post(path, **kw)


# 唯一标识，避免重复数据污染
UNIQ = time.strftime("%Y%m%d%H%M%S") + str(int(time.time() * 1000) % 1000)
SID = f"gate_{UNIQ}"
DATE = "2026-06-13"
PHONE = "139" + UNIQ[-8:]

# 非零有效经营数据（主验收）
RAW = {
    "daily_revenue": 32000, "daily_recharge_amount": 12500, "daily_product_retail": 4500,
    "daily_visits": 35, "daily_new_customers": 8, "daily_valid_appointments": 20,
    "daily_appointment_arrivals": 17, "daily_transaction_customers": 18, "daily_transaction_orders": 18,
    "daily_new_transaction": 5, "daily_project_sales": 15000, "daily_main_project_sales": 7500,
    "daily_service_count": 50, "daily_staff_count": 15, "daily_complaints": 2,
}


def run():
    print(f"=== V0.1.3 第四闸门验收（{MODE}）store={SID} ===")

    # 闸门1：health（真实 /health）
    r = g("/health")
    ck("[闸门1] GET /health == 200", r.status_code == 200, str(r.status_code))

    # 闸门2：经营诊断（非零数据）→ issue
    r = p(f"{B}/monthly-diagnoses", json={"store_id": SID, "report_date": DATE, "form_data": RAW})
    ck("[闸门2] 诊断 200 + 生成 issue", r.status_code == 200 and len(r.json()["data"]["issues"]) > 0)

    # 闸门2.1：诊断 → 任务桥接，today-tasks 非空
    tt = g(f"{B}/today-tasks", store_id=SID, date=DATE).json()["data"]
    ck("[闸门2] 诊断后 today-tasks 非空(issue→task)", len(tt) > 0, f"{len(tt)}条")
    ck("[闸门2] 含 diagnosis_issue 任务", any(t["source_type"] == "diagnosis_issue" for t in tt))

    # 闸门3：顾客经营全链路（唯一手机号）
    cid = p(f"{B}/customers", json={"store_id": SID, "name": "闸门顾客", "phone": PHONE}).json()["data"]["id"]
    ck("[闸门3] 建档(phone唯一)", isinstance(cid, int))
    ck("[闸门3] phone 唯一冲突→400",
       p(f"{B}/customers", json={"store_id": SID, "name": "dup", "phone": PHONE}).status_code == 400)
    pid = p(f"{B}/customers/{cid}/projects",
            json={"project_name": "颈肩", "total_quantity": 3, "total_amount": 3000}).json()["data"]["id"]
    ck("[闸门3] 录入项目", isinstance(pid, int))
    rem = p(f"{B}/customers/{cid}/projects/{pid}/consume").json()["data"]["remaining_quantity"]
    ck("[闸门3] 消耗 remaining-1", rem == 2)
    p(f"{B}/customers/{cid}/projects/{pid}/consume")
    p(f"{B}/customers/{cid}/projects/{pid}/consume")
    warns = g(f"{B}/warnings", store_id=SID).json()["data"]
    ck("[闸门3] 消耗至0生成 red 预警", any(w["warning_level"] == "red" and w["customer_id"] == cid for w in warns))
    ck("[闸门3] 录入家居产品",
       p(f"{B}/customers/{cid}/home-products", json={"product_name": "精华", "purchase_date": "2026-06-01", "estimated_cycle": 30}).status_code == 200)
    did = p(f"{B}/customers/{cid}/demands", json={"demand_desc": "改善法令纹", "progress_score": 5}).json()["data"]["id"]
    client.put(f"{B}/customers/{cid}/demands/{did}", json={"progress_score": 9})
    board = g(f"{B}/demand-board", store_id=SID).json()["data"]
    ck("[闸门3] 看板可成交标💰", board["summary"]["dealable_count"] >= 1)

    # 闸门4：今日任务聚合 + P0限流 + 完成 + 幂等 + 复盘 + 明日3件事
    tasks = client.post(f"{B}/today-tasks/generate", params={"store_id": SID, "date": DATE}).json()["data"]
    ck("[闸门4] 今日任务 >0", len(tasks) > 0, f"{len(tasks)}条")
    ck("[闸门4] 聚合两类来源",
       any(t["source_type"] == "diagnosis_issue" for t in tasks) and any(t["source_type"] == "customer_ops" for t in tasks))
    p0 = [t for t in tasks if t["priority"] == 0]
    ck("[闸门4] P0限流: 非豁免P0≤3", len([t for t in p0 if not t.get("force_p0")]) <= 3, f"P0={len(p0)}")
    done_id = tasks[0]["id"]
    ck("[闸门4] 标记任务 done",
       client.put(f"{B}/tasks/{done_id}/status", json={"status": "done"}).status_code == 200)
    regen = client.post(f"{B}/today-tasks/generate", params={"store_id": SID, "date": DATE}).json()["data"]
    still = next((t for t in regen if t["id"] == done_id), None)
    ck("[闸门4] 幂等: 重复generate保留done", still is not None and still["status"] == "done")
    rev = p(f"{B}/daily-review", json={"store_id": SID, "report_date": DATE, "review_content": "gate"}).json()["data"]
    ck("[闸门4] 复盘后明日3件事非空", len(rev["tomorrow_actions"]) > 0, f"{len(rev['tomorrow_actions'])}条")

    # 边界测试（全零数据仅验证不崩，不计入主验收阈值）
    rz = p(f"{B}/monthly-diagnoses", json={"store_id": f"{SID}_zero", "report_date": DATE,
                                           "form_data": {k: 0 for k in RAW}})
    ck("[边界] 全零数据不 5xx", rz.status_code < 500, str(rz.status_code))

    print(f"\n=== 第四闸门结果：{_p} PASS / {_f} FAIL（通过标准=100% PASS）===")
    return _f == 0


if __name__ == "__main__":
    ok = run()
    print("✅ 第四闸门 PASS" if ok else "❌ 第四闸门 FAIL")
    sys.exit(0 if ok else 1)
