"""V0.1.3 店长工作台 API 路由。

补丁4：前缀沿用 /api/store-manager，不启 /api/v2；内部标记 api_version='v0.1.3'。
所有接口走独立 SQLite，不动主库、不动 V0.1.1。
"""
from fastapi import APIRouter, HTTPException

from . import db_v013 as db
from . import pipeline_v013 as pipe
from . import diagnosis_v013 as dg
from . import customer_ops_v013 as ops
from . import tasks_v013 as tk
from . import model_to_dict
from .schemas_v013 import (
    DailyRawDataRequest, MonthlyDiagnosisRequest, BenchmarkConfigUpdate,
    CustomerCreate, ProjectCreate, HomeProductCreate, DemandCreate,
    DemandProgressUpdate, TaskStatusUpdate, DailyReviewRequest,
)

router = APIRouter(prefix="/api/store-manager", tags=["store-manager-v0.1.3"])


def ok(data):
    return {"code": 1000, "msg": "success", "data": data, "api_version": db.API_VERSION}


# ---------- 经营诊断 ----------
@router.post("/daily-raw-data")
def post_daily_raw_data(req: DailyRawDataRequest):
    conn = db.connect()
    try:
        raw = pipe.save_daily_raw_data(conn, req.store_id, req.report_date, req.form_data)
        return ok(raw)
    finally:
        conn.close()


@router.get("/computed-metrics")
def get_computed_metrics(store_id: str = "default_store", report_date: str = ""):
    conn = db.connect()
    try:
        return ok(pipe.get_computed_metrics(conn, store_id, report_date or None))
    finally:
        conn.close()


@router.post("/monthly-diagnoses")
def post_monthly_diagnosis(req: MonthlyDiagnosisRequest):
    conn = db.connect()
    try:
        return ok(pipe.create_diagnosis(conn, model_to_dict(req)))
    finally:
        conn.close()


@router.get("/diagnosis/{diagnosis_id}")
def get_diagnosis(diagnosis_id: int):
    conn = db.connect()
    try:
        d = pipe.get_diagnosis(conn, diagnosis_id)
        if not d:
            raise HTTPException(status_code=404, detail="diagnosis not found")
        return ok(d)
    finally:
        conn.close()


# ---------- 阈值配置（补丁1） ----------
@router.get("/benchmark-config")
def get_benchmark_config(store_id: str = "default_store"):
    conn = db.connect()
    try:
        return ok(dg.get_benchmark(conn, store_id))
    finally:
        conn.close()


@router.put("/benchmark-config")
def put_benchmark_config(req: BenchmarkConfigUpdate, store_id: str = "default_store"):
    conn = db.connect()
    try:
        return ok(dg.update_benchmark(conn, store_id, model_to_dict(req)))
    finally:
        conn.close()


# ---------- 今日任务 + 复盘 ----------
@router.get("/today-tasks")
def get_today_tasks(store_id: str = "default_store", date: str = "", generate: int = 0):
    conn = db.connect()
    try:
        if generate:
            return ok(tk.generate_today_tasks(conn, store_id, date or None))
        return ok(tk.get_today_tasks(conn, store_id, date or None))
    finally:
        conn.close()


@router.post("/today-tasks/generate")
def post_generate_today_tasks(store_id: str = "default_store", date: str = ""):
    conn = db.connect()
    try:
        return ok(tk.generate_today_tasks(conn, store_id, date or None))
    finally:
        conn.close()


@router.put("/tasks/{task_id}/status")
def put_task_status(task_id: int, req: TaskStatusUpdate):
    conn = db.connect()
    try:
        t = tk.update_task_status(conn, task_id, req.status, req.review_note or "")
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        return ok(t)
    finally:
        conn.close()


@router.post("/daily-review")
def post_daily_review(req: DailyReviewRequest):
    conn = db.connect()
    try:
        return ok(tk.submit_daily_review(conn, req.store_id, req.report_date, req.review_content or ""))
    finally:
        conn.close()


@router.get("/daily-review/history")
def get_daily_review_history(store_id: str = "default_store"):
    conn = db.connect()
    try:
        return ok(tk.get_review_history(conn, store_id))
    finally:
        conn.close()


# ---------- 顾客经营 ----------
@router.post("/customers")
def post_customer(req: CustomerCreate):
    conn = db.connect()
    try:
        try:
            c = ops.create_customer(conn, model_to_dict(req))
        except Exception as e:
            # phone 唯一约束冲突等
            raise HTTPException(status_code=400, detail=f"创建失败：{e}")
        return ok(c)
    finally:
        conn.close()


@router.get("/customers")
def list_customers(store_id: str = "default_store", keyword: str = ""):
    conn = db.connect()
    try:
        return ok(ops.list_customers(conn, store_id, keyword or None))
    finally:
        conn.close()


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int):
    conn = db.connect()
    try:
        c = ops.get_customer(conn, customer_id)
        if not c:
            raise HTTPException(status_code=404, detail="customer not found")
        c["projects"] = ops.list_projects(conn, customer_id)
        c["home_products"] = ops.list_home_products(conn, customer_id)
        c["demands"] = ops.list_demands(conn, customer_id)
        return ok(c)
    finally:
        conn.close()


@router.post("/customers/{customer_id}/projects")
def post_project(customer_id: int, req: ProjectCreate):
    conn = db.connect()
    try:
        if not ops.get_customer(conn, customer_id):
            raise HTTPException(status_code=404, detail="customer not found")
        return ok(ops.add_project(conn, customer_id, model_to_dict(req)))
    finally:
        conn.close()


@router.post("/customers/{customer_id}/projects/{project_id}/consume")
def post_consume(customer_id: int, project_id: int):
    conn = db.connect()
    try:
        proj = ops.get_project(conn, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="project not found")
        # 校验归属：项目必须属于 URL 中的 customer_id，防止跨顾客串改
        if int(proj["customer_id"]) != int(customer_id):
            raise HTTPException(status_code=404, detail="project not found for this customer")
        return ok(ops.consume_project(conn, project_id))
    finally:
        conn.close()


@router.post("/customers/{customer_id}/home-products")
def post_home_product(customer_id: int, req: HomeProductCreate):
    conn = db.connect()
    try:
        if not ops.get_customer(conn, customer_id):
            raise HTTPException(status_code=404, detail="customer not found")
        return ok(ops.add_home_product(conn, customer_id, model_to_dict(req)))
    finally:
        conn.close()


@router.post("/customers/{customer_id}/demands")
def post_demand(customer_id: int, req: DemandCreate):
    conn = db.connect()
    try:
        if not ops.get_customer(conn, customer_id):
            raise HTTPException(status_code=404, detail="customer not found")
        return ok(ops.add_demand(conn, customer_id, model_to_dict(req)))
    finally:
        conn.close()


@router.put("/customers/{customer_id}/demands/{demand_id}")
def put_demand_progress(customer_id: int, demand_id: int, req: DemandProgressUpdate):
    conn = db.connect()
    try:
        dm = ops.get_demand(conn, demand_id)
        if not dm:
            raise HTTPException(status_code=404, detail="demand not found")
        # 校验归属：需求必须属于 URL 中的 customer_id
        if int(dm["customer_id"]) != int(customer_id):
            raise HTTPException(status_code=404, detail="demand not found for this customer")
        return ok(ops.update_demand_progress(conn, demand_id, req.progress_score))
    finally:
        conn.close()


# ---------- 看板与预警 ----------
@router.get("/warnings")
def get_warnings(store_id: str = "default_store"):
    conn = db.connect()
    try:
        return ok(ops.list_warnings(conn, store_id, only_unresolved=True))
    finally:
        conn.close()


@router.get("/demand-board")
def get_demand_board(store_id: str = "default_store"):
    conn = db.connect()
    try:
        return ok(ops.build_demand_board(conn, store_id))
    finally:
        conn.close()
