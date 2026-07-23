from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
app.include_router(store_manager_v013_router)
app.include_router(store_manager_router)

# ── DSM W3-01 authoritative employee-identity chain ───────────────────────────
# Gated behind IDENTITY_I1_ENABLED (default OFF). Identity + store-registry tables
# live on a SEPARATE metadata and are created ONLY by the reviewed migration —
# never by the legacy Base.metadata.create_all() above. When enabled, the schema
# must already be migrated and the config must be complete + independent, or the
# app fails closed at startup (no half-usable state). When disabled, nothing below
# is registered and legacy behavior is byte-for-byte unchanged.
if settings.identity_i1_enabled:
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError
    from fastapi.encoders import jsonable_encoder
    from .routers import auth_identity
    from .identity import models as identity_models  # noqa: F401
    from .identity import envelope as identity_envelope
    from .identity.errors import ApiError, VALIDATION_ERROR
    from .identity.readiness import check_ready, check_identity_config

    # single Settings config source; complete + independent + main-backend, else
    # fail closed. Then require the migrated schema at the exact machine version.
    check_identity_config(settings, os.environ)
    check_ready(engine)

    _IDENTITY_PREFIX = "/api/auth"

    @app.middleware("http")
    async def _trace_id_middleware(request: Request, call_next):
        # one trace id per request; honor a caller-supplied X-Trace-Id if present.
        incoming = request.headers.get("x-trace-id") or request.headers.get("X-Trace-Id")
        request.state.trace_id = incoming or identity_envelope.new_trace_id()
        return await call_next(request)

    app.include_router(auth_identity.router)

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        """Unified {code, message, trace_id, data} envelope for identity errors."""
        trace_id = identity_envelope.trace_id_of(request)
        return JSONResponse(status_code=exc.http_status, content=exc.envelope(trace_id))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        """Identity routes get the unified 422 VALIDATION_ERROR envelope; every other
        route keeps FastAPI's default validation response so legacy behavior is
        unchanged."""
        if request.url.path.startswith(_IDENTITY_PREFIX):
            trace_id = identity_envelope.trace_id_of(request)
            return JSONResponse(status_code=422, content={
                "code": VALIDATION_ERROR, "message": "请求参数错误",
                "trace_id": trace_id, "data": None})
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

app.mount("/reports", StaticFiles(directory=settings.report_storage_path), name="reports")


@app.get("/health")
def health():
    return {"status": "ok", "app": "store-coach-system", "version": "0.1.0"}
