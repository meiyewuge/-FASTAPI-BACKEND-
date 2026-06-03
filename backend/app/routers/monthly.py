from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..schemas import MonthlyCheckupCreate
from ..scoring import score_monthly, num
from ..mba_models import monthly_mba_analysis
from ..ai import call_llm
from ..report import render_pdf
from .diagnoses import store_to_dict

router = APIRouter(prefix="/api/monthly-checkups", tags=["monthly-checkups"])


@router.post("")
async def create_monthly_checkup(payload: MonthlyCheckupCreate, db: Session = Depends(get_db)):
    if payload.store_id:
        store = db.get(models.Store, payload.store_id)
        if not store:
            raise HTTPException(status_code=404, detail="门店不存在")
    else:
        if not payload.store_info:
            raise HTTPException(status_code=400, detail="缺少门店信息")
        store = models.Store(**payload.store_info.model_dump())
        db.add(store)
        db.flush()

    previous = db.query(models.MonthlyCheckup).filter(models.MonthlyCheckup.store_id == store.id, models.MonthlyCheckup.check_month < payload.check_month).order_by(models.MonthlyCheckup.check_month.desc()).first()
    previous_metrics = previous.calculated_metrics if previous else None
    scored = score_monthly(payload.form_data, previous=previous_metrics)

    checkup = models.MonthlyCheckup(
        store_id=store.id,
        check_month=payload.check_month,
        revenue=num(payload.form_data, "revenue"),
        customer_visits=int(num(payload.form_data, "customer_visits")),
        paying_customers=int(num(payload.form_data, "paying_customers")),
        new_customers=int(num(payload.form_data, "new_customers")),
        old_customers=int(num(payload.form_data, "old_customers")),
        average_ticket=scored["metrics"].get("average_ticket"),
        employee_count=int(num(payload.form_data, "employee_count")),
        marketing_cost=num(payload.form_data, "marketing_cost"),
        product_revenue={k: payload.form_data.get(k) for k in ["traffic_project_revenue", "profit_project_revenue", "premium_project_revenue", "main_project_revenue"]},
        staff_data={k: payload.form_data.get(k) for k in ["resigned_count", "champion_sales", "staff_avg_sales", "training_count", "complaint_count"]},
        customer_data={k: payload.form_data.get(k) for k in ["active_members", "repurchase_customers", "reactivated_members", "referral_customers", "private_domain_customers", "churn_risk_members"]},
        channel_data={k: payload.form_data.get(k) for k in ["douyin_views", "douyin_orders", "meituan_orders", "private_domain_new_contacts", "live_sessions", "short_video_count"]},
        cost_data={k: payload.form_data.get(k) for k in ["rent_cost", "labor_cost", "platform_commission", "water_electric_cost", "gross_margin_rate", "consumable_cost"]},
        calculated_metrics=scored["metrics"],
        total_score=scored["total_score"],
        people_score=scored["scores"]["people_score"],
        product_score=scored["scores"]["product_score"],
        place_score=scored["scores"]["place_score"],
        customer_score=scored["scores"]["customer_score"],
        finance_score=scored["scores"]["finance_score"],
        digital_score=scored["scores"]["digital_score"],
        mom_changes=scored["mom_changes"],
    )
    db.add(checkup)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该门店该月份已提交月度体检")

    mba = monthly_mba_analysis(scored, payload.form_data)
    ai_payload = {
        "report_type": "monthly_checkup",
        "store_info": store_to_dict(store),
        "check_month": payload.check_month,
        "raw_data": payload.form_data,
        "total_score": scored["total_score"],
        "rating": scored["rating"],
        "dimensions": scored["dimensions"],
        "scores": {**scored["scores"], "total_score": scored["total_score"], "rating": scored["rating"]},
        "metrics": scored["metrics"],
        "mom_changes": scored["mom_changes"],
        "risk_tags": scored["risk_tags"],
        "lowest_dimension": scored["lowest_dimension"],
        "mba_diagnosis": mba,
        "validation_warnings": scored["validation_warnings"],
    }
    ai_content = await call_llm(ai_payload, "monthly_checkup")
    db.add(models.AIReport(report_type="monthly_checkup", target_id=checkup.id, summary=ai_content.get("monthly_summary"), structured_content=ai_content, raw_ai_response=ai_content))
    report_url = render_pdf("monthly_checkup", store_to_dict(store), ai_payload, ai_content)
    checkup.report_url = report_url
    db.commit()
    db.refresh(checkup)
    return {"code": 200, "message": "月度体检提交成功", "data": {"checkup_id": checkup.id, "store_id": store.id, "total_score": checkup.total_score, "report_url": report_url}}


@router.get("/{checkup_id}")
def get_monthly_checkup(checkup_id: int, db: Session = Depends(get_db)):
    checkup = db.get(models.MonthlyCheckup, checkup_id)
    if not checkup:
        raise HTTPException(status_code=404, detail="月度体检不存在")
    ai = db.query(models.AIReport).filter_by(report_type="monthly_checkup", target_id=checkup_id).order_by(models.AIReport.id.desc()).first()
    dimensions = [
        {"key": "people", "name": "人", "score": checkup.people_score, "max_score": 15},
        {"key": "product", "name": "货", "score": checkup.product_score, "max_score": 15},
        {"key": "place", "name": "场", "score": checkup.place_score, "max_score": 15},
        {"key": "customer", "name": "客", "score": checkup.customer_score, "max_score": 20},
        {"key": "finance", "name": "财", "score": checkup.finance_score, "max_score": 20},
        {"key": "digital", "name": "数", "score": checkup.digital_score, "max_score": 15},
    ]
    return {"code": 200, "data": {
        "checkup_id": checkup.id,
        "store": store_to_dict(checkup.store),
        "check_month": checkup.check_month,
        "total_score": checkup.total_score,
        "rating": "A+" if checkup.total_score >= 90 else "A" if checkup.total_score >= 80 else "B" if checkup.total_score >= 70 else "C" if checkup.total_score >= 60 else "D",
        "dimensions": dimensions,
        "metrics": checkup.calculated_metrics,
        "mom_changes": checkup.mom_changes,
        "ai_report": ai.structured_content if ai else {},
        "report_url": checkup.report_url,
        "created_at": checkup.created_at.isoformat() if checkup.created_at else None,
    }}


@router.get("/store/{store_id}")
def list_monthly_checkups(store_id: int, db: Session = Depends(get_db)):
    items = db.query(models.MonthlyCheckup).filter_by(store_id=store_id).order_by(models.MonthlyCheckup.check_month.desc()).all()
    return {"code": 200, "data": [{"id": x.id, "check_month": x.check_month, "total_score": x.total_score, "revenue": float(x.revenue or 0), "report_url": x.report_url} for x in items]}


@router.get("/store/{store_id}/trends")
def get_trends(store_id: int, months: int = 6, db: Session = Depends(get_db)):
    items = db.query(models.MonthlyCheckup).filter_by(store_id=store_id).order_by(models.MonthlyCheckup.check_month.desc()).limit(months).all()
    items = list(reversed(items))
    return {"code": 200, "data": {
        "months": [x.check_month for x in items],
        "revenue": [float(x.revenue or 0) for x in items],
        "scores": [x.total_score for x in items],
        "average_ticket": [float(x.average_ticket or 0) for x in items],
        "repurchase_rate": [float((x.calculated_metrics or {}).get("repurchase_rate") or 0) for x in items],
        "staff_efficiency": [float((x.calculated_metrics or {}).get("staff_efficiency") or 0) for x in items],
    }}
