import os

from fastapi import APIRouter, Depends, Header, HTTPException

from .schemas import (
    MonthlyDiagnosisRequest,
    GenerateTodayTasksRequest,
    UpdateTaskStatusRequest,
    TaskReviewRequest,
    AdminMarkRequest,
)
from .engine import generate_report
from . import storage
from . import model_to_dict


router = APIRouter(prefix="/api/store-manager", tags=["store-manager-workbench"])


def require_admin(x_admin_key: str | None = Header(default=None)):
    """后台接口轻量保护：校验 X-Admin-Key 是否匹配环境变量 STORE_MANAGER_ADMIN_KEY。

    未配置环境变量时默认拒绝（安全锁定），避免 /admin/* 裸奔。
    """
    expected = os.getenv("STORE_MANAGER_ADMIN_KEY")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=401, detail="后台权限不足")


def ok(data):
    return {"code": 1000, "msg": "success", "data": data}


@router.post("/monthly-diagnoses")
def create_monthly_diagnosis(req: MonthlyDiagnosisRequest):
    payload = model_to_dict(req)
    report = generate_report(payload)
    storage.save_report(payload, report)
    return ok(report)


@router.get("/monthly-diagnoses/{report_id}")
def get_monthly_diagnosis(report_id: str):
    report = storage.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return ok(report)


@router.get("/history")
def get_history(store_id: str):
    return ok(storage.list_reports(store_id))


@router.post("/today-tasks/generate")
def generate_today_tasks(req: GenerateTodayTasksRequest):
    report = None
    if req.report_id:
        report = storage.get_report(req.report_id)
    tasks = []
    if report:
        tasks = report.get("structured_json", {}).get("today_tasks", []) or []
    tasks.extend(req.manual_tasks or [])
    return ok(tasks[:5])


@router.get("/today-tasks")
def get_today_tasks(store_id: str, date: str = ""):
    return ok(storage.list_tasks(store_id))


@router.put("/tasks/{task_id}/status")
def update_task_status(task_id: str, req: UpdateTaskStatusRequest):
    task = storage.update_task_status(task_id, req.status)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return ok(task)


@router.post("/tasks/{task_id}/review")
def submit_task_review(task_id: str, req: TaskReviewRequest):
    review = storage.save_task_review(task_id, model_to_dict(req))
    if not review:
        raise HTTPException(status_code=404, detail="task not found")
    return ok(review)


@router.post("/admin/reports/{report_id}/mark", dependencies=[Depends(require_admin)])
def admin_mark_report(report_id: str, req: AdminMarkRequest):
    result = storage.mark_report(report_id, req.mark, req.note or "")
    if not result:
        raise HTTPException(status_code=404, detail="report not found")
    return ok(result)
