from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .config import settings
from .routers import diagnoses, monthly, admin, weapp
from .store_manager.router import router as store_manager_router
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
app.include_router(store_manager_router)

app.mount("/reports", StaticFiles(directory=settings.report_storage_path), name="reports")


@app.get("/health")
def health():
    return {"status": "ok", "app": "store-coach-system", "version": "0.1.0"}
