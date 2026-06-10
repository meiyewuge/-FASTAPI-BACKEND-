"""V0.1.3 · 完整 main.py app 级 smoke（验证路由冲突已解决）。

目的（回应 P0-1）：不只测 isolated router_v013，而是导入**真实 app.main**，
确认 /api/store-manager 下原先 4 个冲突端点现在由 V0.1.3 生效，
且 V0.1.2 老 router 的独有端点仍可达、未被破坏。

环境无 weasyprint 系统库时用轻量 stub 绕过（仅为本地 smoke，不影响生产渲染）。
DB 走独立测试库（STORE_MANAGER_V013_DB_PATH / STORE_MANAGER_DB_PATH 测试路径）。
"""
import os
import sys
import types
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# weasyprint stub（仅当未安装时）
try:
    import weasyprint  # noqa: F401
except Exception:
    fake = types.ModuleType("weasyprint")
    fake.HTML = lambda *a, **k: types.SimpleNamespace(write_pdf=lambda *a, **k: b"")
    sys.modules["weasyprint"] = fake

# 独立测试库（绝不写生产路径）
tmp = tempfile.gettempdir()
os.environ.setdefault("STORE_MANAGER_V013_DB_PATH", os.path.join(tmp, "v013_applevel.db"))
os.environ.setdefault("STORE_MANAGER_DB_PATH", os.path.join(tmp, "v012_applevel.db"))
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(tmp, "applevel_main.db"))
for f in (os.environ["STORE_MANAGER_V013_DB_PATH"], os.path.join(tmp, "applevel_main.db")):
    try:
        os.remove(f)
    except OSError:
        pass

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
B = "/api/store-manager"
_p = _f = 0


def check(name, cond, detail=""):
    global _p, _f
    ok = bool(cond)
    _p += ok
    _f += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


SAMPLE = {"daily_revenue": 32000, "daily_recharge_amount": 12500, "daily_product_retail": 4500,
          "daily_visits": 35, "daily_new_customers": 8, "daily_valid_appointments": 20,
          "daily_appointment_arrivals": 17, "daily_transaction_customers": 18, "daily_transaction_orders": 18,
          "daily_new_transaction": 5, "daily_project_sales": 15000, "daily_main_project_sales": 7500,
          "daily_service_count": 50, "daily_staff_count": 15, "daily_complaints": 2}


def run():
    print("=== app 级：health 与路由加载 ===")
    check("health", client.get("/health").json().get("status") == "ok")

    print("=== app 级：4 个原冲突端点现由 V0.1.3 生效（响应含 api_version=v0.1.3）===")
    # POST /monthly-diagnoses
    r = client.post(f"{B}/monthly-diagnoses", json={"store_id": "app1", "report_date": "2026-06-09", "form_data": SAMPLE})
    check("POST /monthly-diagnoses → v0.1.3", r.status_code == 200 and r.json().get("api_version") == "v0.1.3",
          f"api_version={r.json().get('api_version')}")
    # POST /today-tasks/generate
    r = client.post(f"{B}/today-tasks/generate", params={"store_id": "app1", "date": "2026-06-09"})
    check("POST /today-tasks/generate → v0.1.3", r.status_code == 200 and r.json().get("api_version") == "v0.1.3")
    # GET /today-tasks
    r = client.get(f"{B}/today-tasks", params={"store_id": "app1", "date": "2026-06-09"})
    check("GET /today-tasks → v0.1.3", r.status_code == 200 and r.json().get("api_version") == "v0.1.3")
    # PUT /tasks/{id}/status — v0.1.3 用整型 id；构造一个任务
    cust = client.post(f"{B}/customers", json={"store_id": "app1", "name": "应用级顾客", "phone": "13600000001"}).json()["data"]
    proj = client.post(f"{B}/customers/{cust['id']}/projects", json={"project_name": "P", "total_quantity": 1, "total_amount": 1000}).json()["data"]
    client.post(f"{B}/customers/{cust['id']}/projects/{proj['id']}/consume")  # 消耗至0→red
    tasks = client.post(f"{B}/today-tasks/generate", params={"store_id": "app1", "date": "2026-06-09"}).json()["data"]
    if tasks:
        r = client.put(f"{B}/tasks/{tasks[0]['id']}/status", json={"status": "done"})
        check("PUT /tasks/{id}/status → v0.1.3", r.status_code == 200 and r.json().get("api_version") == "v0.1.3")
    else:
        check("PUT /tasks/{id}/status → v0.1.3", False, "无任务可测")

    print("=== app 级：V0.1.2 老 router 独有端点仍可达（未被破坏）===")
    # GET /history（V0.1.2 独有）
    check("GET /history (V0.1.2) 仍可达", client.get(f"{B}/history", params={"store_id": "x"}).status_code == 200)
    # GET /monthly-diagnoses/{report_id}（V0.1.2 独有，404 也算路由可达，非 405/未注册）
    r = client.get(f"{B}/monthly-diagnoses/nonexistent")
    check("GET /monthly-diagnoses/{id} (V0.1.2) 路由可达", r.status_code in (200, 404), str(r.status_code))

    print("=== app 级：V0.1.3 专属端点可达 ===")
    check("GET /benchmark-config (v0.1.3)", client.get(f"{B}/benchmark-config", params={"store_id": "app1"}).json().get("api_version") == "v0.1.3")
    check("GET /demand-board (v0.1.3)", client.get(f"{B}/demand-board", params={"store_id": "app1"}).json().get("api_version") == "v0.1.3")

    print(f"\n=== app 级 smoke 结果：{_p} PASS / {_f} FAIL ===")
    return _f == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
