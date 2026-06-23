"""美业AI视频系统 V4.0 · FastAPI 入口。

唯一职责：装配应用、挂载统一 API 路由 /api/*。
真实业务逻辑下沉到 api/services/engine/tasks，本文件保持极薄。
"""

from fastapi import FastAPI

from api.routes import api_router

app = FastAPI(title="美业AI视频系统 V4.0", version="4.0.0")

# 统一 API 出口：所有请求走 /api/*
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "meiye-ai-video-engine-v4"}
