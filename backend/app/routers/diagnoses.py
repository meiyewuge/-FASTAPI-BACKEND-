from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..schemas import DiagnosisCreate
from ..scoring import score_diagnosis
from ..mba_models import diagnosis_mba_analysis
from ..ai import call_llm
from ..report import render_pdf
from ..auth import generate_access_token, verify_result_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diagnoses", tags=["diagnoses"])


def mask_phone(phone: str | None) -> str | None:
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


def store_to_dict(store: models.Store) -> dict:
    return {
        "id": store.id,
        "store_name": store.store_name,
        "city": store.city,
        "contact_person": store.contact_person,
        "contact_phone": mask_phone(store.contact_phone),
        "store_type": store.store_type,
        "source_channel": store.source_channel,
    }


@router.post("")
async def create_diagnosis(payload: DiagnosisCreate, db: Session = Depends(get_db)):
    store = models.Store(**payload.store_info.model_dump())
    db.add(store)
    db.flush()

    scored = score_diagnosis(payload.form_data)
    # P0B-2: 生成 access_token
    access_token = generate_access_token()
    diagnosis = models.Diagnosis(
        store_id=store.id,
        total_score=scored["total_score"],
        rating=scored["rating"],
        traffic_score=scored["scores"]["traffic_score"],
        conversion_score=scored["scores"]["conversion_score"],
        ticket_score=scored["scores"]["ticket_score"],
        retention_score=scored["scores"]["retention_score"],
        team_score=scored["scores"]["team_score"],
        product_score=scored["scores"]["product_score"],
        digital_score=scored["scores"]["digital_score"],
        warning_level=scored["warning_level"],
        confidence_level=scored["confidence_level"],
        ai_status="generating",
        access_token=access_token,  # P0B-2: 存储 access_token
    )
    db.add(diagnosis)
    db.flush()

    form = models.DiagnosisForm(
        diagnosis_id=diagnosis.id,
        form_data=payload.form_data,
        calculated_metrics=scored["metrics"],
        validation_warnings=scored["validation_warnings"],
    )
    db.add(form)
    db.flush()

    mba = diagnosis_mba_analysis(scored, payload.form_data)
    ai_payload = {
        "report_type": "diagnosis",
        "store_info": store_to_dict(store),
        "raw_data": payload.form_data,
        "total_score": scored["total_score"],
        "rating": scored["rating"],
        "dimensions": scored["dimensions"],
        "scores": {**scored["scores"], "total_score": scored["total_score"], "rating": scored["rating"]},
        "metrics": scored["metrics"],
        "risk_tags": scored["risk_tags"],
        "lowest_dimension": scored["lowest_dimension"],
        "mba_diagnosis": mba,
        "confidence_level": scored["confidence_level"],
        "validation_warnings": scored["validation_warnings"],
    }
    ai_content = await call_llm(ai_payload, "diagnosis")
    ai_report = models.AIReport(
        report_type="diagnosis",
        target_id=diagnosis.id,
        summary=ai_content.get("one_sentence_summary"),
        structured_content=ai_content,
        raw_ai_response=ai_content,
    )
    db.add(ai_report)
    report_url = render_pdf("diagnosis", store_to_dict(store), ai_payload, ai_content)
    diagnosis.report_url = report_url
    diagnosis.ai_status = "done"
    db.commit()
    db.refresh(diagnosis)

    # P0B-2: 日志脱敏（仅输出 token 前 8 字符）
    logger.info("Diagnosis created: id=%s, store=%s, token=%s****", diagnosis.id, store.store_name, diagnosis.access_token[:8] if diagnosis.access_token else "None")
    # P0B-2: 返回 access_token 给前端
    return {"code": 200, "message": "诊断创建成功", "data": {
        "diagnosis_id": diagnosis.id,
        "store_id": store.id,
        "total_score": diagnosis.total_score,
        "rating": diagnosis.rating,
        "report_url": report_url,
        "access_token": diagnosis.access_token,  # P0B-2: 返回 token
    }}


@router.get("/{diagnosis_id}")
def get_diagnosis(
    diagnosis_id: int,
    token: Optional[str] = Query(None, description="P0B-2: access_token"),
    ticket: Optional[str] = Query(None, description="P0B-2: Redis ticket"),
    db: Session = Depends(get_db),
):
    # P0B-2: 鉴权
    diagnosis = verify_result_auth(
        record_id=diagnosis_id,
        record_type="diagnosis",
        model=models.Diagnosis,
        token=token,
        ticket=ticket,
        db=db,
    )
    form = db.query(models.DiagnosisForm).filter_by(diagnosis_id=diagnosis_id).first()
    ai = db.query(models.AIReport).filter_by(report_type="diagnosis", target_id=diagnosis_id).order_by(models.AIReport.id.desc()).first()
    dimensions = [
        {"key": "traffic", "name": "流量力", "score": diagnosis.traffic_score, "max_score": 15},
        {"key": "conversion", "name": "转化力", "score": diagnosis.conversion_score, "max_score": 15},
        {"key": "ticket", "name": "客单力", "score": diagnosis.ticket_score, "max_score": 15},
        {"key": "retention", "name": "复购力", "score": diagnosis.retention_score, "max_score": 20},
        {"key": "team", "name": "团队力", "score": diagnosis.team_score, "max_score": 10},
        {"key": "product", "name": "产品力", "score": diagnosis.product_score, "max_score": 15},
        {"key": "digital", "name": "数字化力", "score": diagnosis.digital_score, "max_score": 10},
    ]
    # P0B-2: 如果 ticket 通过，返回 access_token 供前端升级 URL
    response_data = {
        "diagnosis_id": diagnosis.id,
        "store": store_to_dict(diagnosis.store),
        "total_score": diagnosis.total_score,
        "rating": diagnosis.rating,
        "dimensions": dimensions,
        "metrics": form.calculated_metrics if form else {},
        "validation_warnings": form.validation_warnings if form else [],
        "ai_report": ai.structured_content if ai else {},
        "report_url": diagnosis.report_url,
        "created_at": diagnosis.created_at.isoformat() if diagnosis.created_at else None,
    }
    # ticket 通过后返回 access_token（用于 URL 升级）
    if ticket and diagnosis.access_token:
        response_data["access_token"] = diagnosis.access_token
    return {"code": 200, "message": "success", "data": response_data}
