"""V0.1.3 店长工作台 · 后端 smoke_test。

覆盖：health / daily-raw-data / computed-metrics / benchmark-config /
monthly-diagnosis / today-tasks / customer / project / home-product /
demand / warnings / demand-board / task-status / review +
第四闸门「顾客经营全链路 11 步」（补丁3）。

用法：
    STORE_MANAGER_DB_PATH=/tmp/smoke.db STORE_MANAGER_ADMIN_KEY=k python smoke_test_v013.py

说明：本脚本用最小 FastAPI app 挂载 v0.1.3 路由 + health 进行隔离 smoke，
不依赖 weasyprint 等无关系统库；整库启动冒烟由部署前环境执行。
零容忍项：任何 5xx / traceback / 写入失败 / 计算除零错误。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if not os.getenv("STORE_MANAGER_V013_DB_PATH"):
    os.environ["STORE_MANAGER_V013_DB_PATH"] = os.path.join(tempfile.gettempdir(), "store_manager_v013_smoke.db")
    # 干净起点
    try:
        os.remove(os.environ["STORE_MANAGER_V013_DB_PATH"])
    except OSError:
        pass

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.store_manager.router_v013 import router as v013_router

app = FastAPI(title="store-manager-v0.1.3-smoke")
app.include_router(v013_router)


@app.get("/health")
def health():
    return {"status": "ok", "module": "store-manager", "version": "v0.1.3"}


client = TestClient(app)

_passed = 0
_failed = 0
_results = []


def check(name, cond, detail=""):
    global _passed, _failed
    ok = bool(cond)
    _passed += ok
    _failed += (not ok)
    _results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    return ok


def no5xx(resp):
    return resp.status_code < 500


SAMPLE_RAW = {
    "daily_revenue": 32000, "daily_recharge_amount": 12500, "daily_product_retail": 4500,
    "daily_visits": 35, "daily_new_customers": 8, "daily_valid_appointments": 20,
    "daily_appointment_arrivals": 17, "daily_transaction_customers": 18, "daily_transaction_orders": 18,
    "daily_new_transaction": 5, "daily_project_sales": 15000, "daily_main_project_sales": 7500,
    "daily_service_count": 50, "daily_staff_count": 15, "daily_complaints": 2,
}
SID = "smoke_store"
DATE = "2026-06-09"
B = "/api/store-manager"


def run():
    print("=== 基础端点 ===")
    check("health", client.get("/health").json().get("status") == "ok")

    r = client.post(f"{B}/daily-raw-data", json={"store_id": SID, "report_date": DATE, "form_data": SAMPLE_RAW})
    check("daily-raw-data", no5xx(r) and r.status_code == 200, str(r.status_code))

    r = client.post(f"{B}/monthly-diagnoses", json={"store_id": SID, "report_date": DATE, "form_data": SAMPLE_RAW})
    check("monthly-diagnosis", no5xx(r) and r.status_code == 200, str(r.status_code))
    diag = r.json()["data"]
    check("诊断含 top3 + 规则文案(非AI智能)", len(diag["top_issues"]) <= 3 and diag["method"] == "规则诊断"
          and "AI智能" not in diag["source_label"])
    check("get diagnosis", client.get(f"{B}/diagnosis/{diag['id']}").status_code == 200)

    r = client.get(f"{B}/computed-metrics", params={"store_id": SID, "report_date": DATE})
    m = r.json()["data"]
    check("computed-metrics 13项", no5xx(r) and len(m) >= 13 and "conversion_rate" in m)
    check("除零安全(指标均数值)", all(isinstance(m[k], (int, float)) for k in
          ["conversion_rate", "avg_order_value", "complaint_risk_index"]))

    r = client.get(f"{B}/benchmark-config", params={"store_id": SID})
    check("benchmark-config GET 默认值", r.json()["data"]["conversion_rate_green"] == 60)
    check("benchmark-config PUT", client.put(f"{B}/benchmark-config", params={"store_id": SID},
          json={"conversion_rate_green": 65}).status_code == 200)

    print("=== 第四闸门：顾客经营全链路 11 步 ===")
    # 1 新建顾客
    r = client.post(f"{B}/customers", json={"store_id": SID, "name": "闸门顾客", "phone": "13700000001"})
    check("G1 POST /customers 201/200 + phone唯一", r.status_code in (200, 201))
    cid = r.json()["data"]["id"]
    dup = client.post(f"{B}/customers", json={"store_id": SID, "name": "重复", "phone": "13700000001"})
    check("G1 phone唯一约束生效(400)", dup.status_code == 400, str(dup.status_code))
    # 2 录入在店项目
    r = client.post(f"{B}/customers/{cid}/projects", json={"project_name": "颈肩调理", "project_type": "理疗",
                    "total_quantity": 3, "total_amount": 3000})
    check("G2 POST projects", r.status_code == 200)
    pid = r.json()["data"]["id"]
    # 3 项目消耗 remaining-1
    r = client.post(f"{B}/customers/{cid}/projects/{pid}/consume")
    check("G3 consume remaining-1", r.json()["data"]["remaining_quantity"] == 2)
    # 4 消耗至0触发红警
    client.post(f"{B}/customers/{cid}/projects/{pid}/consume")
    client.post(f"{B}/customers/{cid}/projects/{pid}/consume")
    w = client.get(f"{B}/warnings", params={"store_id": SID}).json()["data"]
    check("G4 消耗至0生成red预警", any(x["warning_level"] == "red" and x["customer_id"] == cid for x in w))
    # 5 录入家居产品
    check("G5 POST home-products", client.post(f"{B}/customers/{cid}/home-products",
          json={"product_name": "精华", "purchase_date": "2026-06-01", "estimated_cycle": 30}).status_code == 200)
    # 6 录入需求
    r = client.post(f"{B}/customers/{cid}/demands", json={"demand_desc": "想改善法令纹", "demand_type": "抗衰", "progress_score": 5})
    check("G6 POST demands", r.status_code == 200)
    demand_id = r.json()["data"]["id"]
    # 7 需求进度≥8进可成交
    client.put(f"{B}/customers/{cid}/demands/{demand_id}", json={"progress_score": 9})
    # 8 今日需求看板
    board = client.get(f"{B}/demand-board", params={"store_id": SID}).json()["data"]
    check("G7+G8 demand-board 可成交标💰", board["summary"]["dealable_count"] >= 1
          and any(d.get("flag") == "💰" for d in board["dealable_demands"]))
    # P1-5 归属校验：用错误 customer 消耗项目 / 改需求 → 404
    check("归属校验：错误customer消耗项目→404",
          client.post(f"{B}/customers/999999/projects/{pid}/consume").status_code == 404)
    check("归属校验：错误customer改需求→404",
          client.put(f"{B}/customers/999999/demands/{demand_id}", json={"progress_score": 7}).status_code == 404)

    # 9 生成顾客经营任务
    tasks = client.post(f"{B}/today-tasks/generate", params={"store_id": SID, "date": DATE}).json()["data"]
    check("G9 预警触发生成 store_action_task", len(tasks) >= 1)
    # P1-6 优先级数字统一：P0=0 / P1=1
    check("优先级数字 P0=0/P1=1 且 label 一致",
          all(t["priority"] in (0, 1, 2, 3) for t in tasks)
          and all((t["priority"] == 0) == (t["priority_label"] == "P0") for t in tasks))
    # 10 完成任务 + 提交复盘
    if tasks:
        check("G10 PUT task status", client.put(f"{B}/tasks/{tasks[0]['id']}/status",
              json={"status": "done"}).status_code == 200)
    rev = client.post(f"{B}/daily-review", json={"store_id": SID, "report_date": DATE, "review_content": "smoke"}).json()["data"]
    # 11 复盘含 tomorrow_actions
    check("G11 复盘返回 tomorrow_actions", "tomorrow_actions" in rev)
    check("today-tasks GET", client.get(f"{B}/today-tasks", params={"store_id": SID, "date": DATE}).status_code == 200)
    check("daily-review/history", client.get(f"{B}/daily-review/history", params={"store_id": SID}).status_code == 200)
    check("customers list", client.get(f"{B}/customers", params={"store_id": SID}).status_code == 200)
    check("customer detail", client.get(f"{B}/customers/{cid}").status_code == 200)

    print(f"\n=== smoke 结果：{_passed} PASS / {_failed} FAIL ===")
    return _failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
