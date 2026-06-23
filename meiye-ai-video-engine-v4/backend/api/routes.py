"""API 统一出口（skeleton）。

所有路由集中在此装配，前端只通过 /api/* 访问。
当前为占位实现：返回 not_implemented，真实逻辑在 services + engine + tasks 落地。
分层约束：api 层不直接调用 a_engine / b_engine，统一经 services 编排。
"""

from fastapi import APIRouter

api_router = APIRouter()


@api_router.post("/auth/login")
def login() -> dict:
    """手机号 / token 登录，自动绑定 tenant_id。"""
    return {"code": 0, "msg": "not_implemented", "data": None}


@api_router.post("/a/generate")
def a_generate() -> dict:
    """A台：一句话 → 母视频（异步，返回 task_id）。"""
    return {"code": 0, "msg": "not_implemented", "data": {"task_id": None}}


@api_router.post("/b/generate")
def b_generate() -> dict:
    """B台：母视频 → 批量裂变视频（异步，返回 task_id）。"""
    return {"code": 0, "msg": "not_implemented", "data": {"task_id": None}}


@api_router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    """查询任务状态：pending / running / done / failed。"""
    return {"code": 0, "msg": "not_implemented", "data": {"task_id": task_id, "status": "pending"}}


@api_router.get("/videos")
def list_videos(type: str = "mother", page: int = 1) -> dict:
    """历史视频列表：母视频 / 裂变视频，按 tenant_id 隔离。"""
    return {"code": 0, "msg": "not_implemented", "data": {"items": [], "total": 0}}
