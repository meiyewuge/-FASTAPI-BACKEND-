from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import settings
from .. import models
from ..schemas import FollowupCreate
from .diagnoses import mask_phone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(x_admin_key: str | None = Header(default=None)):
    if not x_admin_key or x_admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="后台权限不足")


def mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


@router.get("/stores", dependencies=[Depends(require_admin)])
def list_stores(page: int = 1, page_size: int = 20, keyword: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Store)
    if keyword:
        q = q.filter(models.Store.store_name.contains(keyword))
    total = q.count()
    stores = q.order_by(models.Store.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    data = []
    for s in stores:
        latest_diagnosis = db.query(models.Diagnosis).filter_by(store_id=s.id).order_by(models.Diagnosis.id.desc()).first()
        latest_monthly = db.query(models.MonthlyCheckup).filter_by(store_id=s.id).order_by(models.MonthlyCheckup.check_month.desc()).first()
        data.append({
            "id": s.id,
            "store_name": s.store_name,
            "city": s.city,
            "contact_person": s.contact_person,
            "contact_phone": mask_phone(s.contact_phone),
            "store_type": s.store_type,
            "diagnosis_score": latest_diagnosis.total_score if latest_diagnosis else None,
            "monthly_score": latest_monthly.total_score if latest_monthly else None,
            "latest_month": latest_monthly.check_month if latest_monthly else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"code": 200, "data": {"items": data, "total": total}}


@router.get("/stores/{store_id}", dependencies=[Depends(require_admin)])
def get_store_detail(store_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Store, store_id)
    if not s:
        raise HTTPException(status_code=404, detail="门店不存在")
    diagnoses = db.query(models.Diagnosis).filter_by(store_id=store_id).order_by(models.Diagnosis.id.desc()).all()
    monthly = db.query(models.MonthlyCheckup).filter_by(store_id=store_id).order_by(models.MonthlyCheckup.check_month.desc()).all()
    followups = db.query(models.Followup).filter_by(store_id=store_id).order_by(models.Followup.id.desc()).all()
    return {"code": 200, "data": {
        "store": {"id": s.id, "store_name": s.store_name, "city": s.city, "contact_person": s.contact_person, "contact_phone": mask_phone(s.contact_phone), "store_type": s.store_type},
        "diagnoses": [{"id": d.id, "total_score": d.total_score, "rating": d.rating, "report_url": d.report_url, "created_at": d.created_at.isoformat() if d.created_at else None} for d in diagnoses],
        "monthly_checkups": [{"id": m.id, "check_month": m.check_month, "total_score": m.total_score, "revenue": float(m.revenue or 0), "report_url": m.report_url} for m in monthly],
        "followups": [{"id": f.id, "admin_name": f.admin_name, "followup_status": f.followup_status, "followup_note": f.followup_note, "recommended_service": f.recommended_service, "created_at": f.created_at.isoformat() if f.created_at else None} for f in followups]
    }}


@router.post("/stores/{store_id}/followups", dependencies=[Depends(require_admin)])
def create_followup(store_id: int, payload: FollowupCreate, db: Session = Depends(get_db)):
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="门店不存在")
    f = models.Followup(store_id=store_id, **payload.model_dump())
    db.add(f)
    db.commit()
    db.refresh(f)
    logger.info("Followup created: id=%s, store_id=%s", f.id, store_id)
    return {"code": 200, "message": "跟进记录已保存", "data": {"id": f.id}}


@router.get("/diagnoses", dependencies=[Depends(require_admin)])
def list_diagnoses(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    q = db.query(models.Diagnosis).order_by(models.Diagnosis.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [{"id": x.id, "store_id": x.store_id, "store_name": x.store.store_name, "total_score": x.total_score, "rating": x.rating, "report_url": x.report_url, "created_at": x.created_at.isoformat() if x.created_at else None} for x in items], "total": total}}


@router.get("/monthly-checkups", dependencies=[Depends(require_admin)])
def list_monthly(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    q = db.query(models.MonthlyCheckup).order_by(models.MonthlyCheckup.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"items": [{"id": x.id, "store_id": x.store_id, "store_name": x.store.store_name, "check_month": x.check_month, "total_score": x.total_score, "revenue": float(x.revenue or 0), "report_url": x.report_url} for x in items], "total": total}}
