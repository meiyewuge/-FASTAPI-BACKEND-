from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .config import settings
from .routers import diagnoses, monthly, admin, weapp
from .store_manager.router import router as store_manager_router
from .store_manager.router_v013 import router as store_manager_v013_router
import os

Base.metadata.create_all(bind=engine)
os.makedirs(settings.report_storage_path, exist_ok=True)

app = FastAPI(title="门店经营陪跑系统 MVP V0.1", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(diagnoses.router)
app.include_router(monthly.router)
app.include_router(admin.router)
app.include_router(weapp.router, prefix="/api", tags=["weapp"])
# V0.1.3 路由先注册：与 V0.1.2 store_manager 在 /api/store-manager 下有 4 个同 path+method
# 重叠端点(monthly-diagnoses[POST]、today-tasks[GET]、today-tasks/generate[POST]、
# tasks/{id}/status[PUT])。FastAPI 首个匹配生效，故 V0.1.3 先注册以保证其为权威实现；
# V0.1.2 独有端点(history、monthly-diagnoses/{id}、tasks/{id}/review、admin/mark)仍由老 router 提供。
# 注：V0.1.2 测试服务(18080)运行 V0.1.2 分支、不含 v013 路由，不受此顺序影响。
# Stage I1-R1: authoritative identity + Daily Loop Facade.
# Gated behind IDENTITY_I1_ENABLED (default OFF). Identity tables live on a
# SEPARATE metadata and are created ONLY by the reviewed migration — never by the
# legacy Base.metadata.create_all() above. When enabled, the schema must already
# be migrated or the app fails closed at startup (no half-usable state).
if settings.identity_i1_enabled:
    from .routers import auth_identity, daily_loop_facade
    from .identity import models as identity_models  # noqa: F401
    from .identity.errors import ApiError
    from .identity.readiness import check_ready, check_identity_config

    # P0-1: single Settings config source; complete + independent, else fail closed.
    # P0-2: DM_MAIN_BACKEND enforced inside check_identity_config.
    check_identity_config(settings, os.environ)
    # migrated schema at the exact machine version, else fail closed.
    check_ready(engine)

    app.include_router(auth_identity.router)
    app.include_router(daily_loop_facade.router)

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        """Uniform {code,msg,data} envelope for identity/Facade errors."""
        return JSONResponse(status_code=exc.http_status, content=exc.envelope())

app.include_router(store_manager_v013_router)
app.include_router(store_manager_router)

app.mount("/reports", StaticFiles(directory=settings.report_storage_path), name="reports")


@app.get("/health")
def health():
    return {"status": "ok", "app": "store-coach-system", "version": "0.1.0"}
