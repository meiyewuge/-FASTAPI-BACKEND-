"""美业AI视频系统 V4.0 · FastAPI 入口。

装配应用、建表、挂载统一 API 路由 /api/*，并统一错误结构 {code, message, data}。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import api_router
from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # P2A：幂等播种 skill_registry 12 条 canonical 技能（只读种子，重复启动不重复插入）
    from db import SessionLocal
    from services.skill_registry_service import seed_skills

    _db = SessionLocal()
    try:
        seed_skills(_db)
    finally:
        _db.close()
    # B3：启动时后台恢复未完成任务（防 systemd 重启丢任务），不阻塞启动
    from tasks.recovery import recover_in_background

    recover_in_background()
    yield


app = FastAPI(title="美业AI视频系统 V4.0", version="4.0.0", lifespan=lifespan)


# ---- 统一错误结构（所有响应均为 {code, message, data}）----
@app.exception_handler(RequestValidationError)
async def _on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "code": 2001,
            "message": "参数校验失败",
            "data": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()],
        },
    )


@app.exception_handler(StarletteHTTPException)
async def _on_http_error(request: Request, exc: StarletteHTTPException):
    """HTTP 异常（含鉴权 401/403）也走统一 {code, message, data} 结构。"""
    code = 1001 if exc.status_code in (401, 403) else exc.status_code
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": str(exc.detail), "data": None},
    )


@app.exception_handler(Exception)
async def _on_unhandled_error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 5000, "message": "服务器内部错误", "data": None},
    )


# 统一 API 出口：所有请求走 /api/*
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "meiye-ai-video-engine-v4"}
