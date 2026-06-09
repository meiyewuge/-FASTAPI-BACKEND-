"""V0.1.3 pydantic 请求模型（兼容 v1/v2）。"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class DailyRawDataRequest(BaseModel):
    store_id: str = "default_store"
    report_date: Optional[str] = None
    form_data: Dict[str, Any] = Field(default_factory=dict)


class MonthlyDiagnosisRequest(BaseModel):
    store_id: str = "default_store"
    report_date: Optional[str] = None
    diagnosis_month: Optional[str] = None
    form_data: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkConfigUpdate(BaseModel):
    store_type: Optional[str] = None
    store_stage: Optional[str] = None
    staff_count: Optional[int] = None
    monthly_target: Optional[float] = None
    avg_order_target: Optional[float] = None
    per_capita_target: Optional[float] = None
    new_customer_ratio_green_low: Optional[float] = None
    new_customer_ratio_green_high: Optional[float] = None
    return_customer_ratio_green_low: Optional[float] = None
    return_customer_ratio_green_high: Optional[float] = None
    conversion_rate_green: Optional[float] = None
    repurchase_rate_green: Optional[float] = None
    appointment_arrival_rate_green: Optional[float] = None
    complaint_risk_max: Optional[float] = None


class CustomerCreate(BaseModel):
    store_id: str = "default_store"
    name: str
    phone: str
    nickname: Optional[str] = ""
    gender: Optional[str] = "女"
    age_range: Optional[str] = ""
    skin_type: Optional[str] = ""
    source_channel: Optional[str] = ""
    first_visit_date: Optional[str] = None
    customer_no: Optional[str] = None
    preferred_projects: Optional[str] = ""
    preferred_staff: Optional[str] = ""
    preferred_time: Optional[str] = ""
    price_sensitivity: Optional[str] = ""
    comm_preference: Optional[str] = ""


class ProjectCreate(BaseModel):
    project_name: str
    project_type: str = ""
    purchase_date: Optional[str] = None
    total_quantity: int = 1
    total_amount: float = 0
    unit_amount: Optional[float] = None
    used_quantity: int = 0
    expiry_date: Optional[str] = None
    responsible_staff: Optional[str] = ""
    notes: Optional[str] = ""


class HomeProductCreate(BaseModel):
    product_name: str
    product_type: Optional[str] = ""
    brand: Optional[str] = ""
    specification: Optional[str] = ""
    purchase_date: Optional[str] = None
    estimated_cycle: int = 30
    estimated_end_date: Optional[str] = None
    usage_feedback: Optional[str] = ""
    repurchase_status: Optional[str] = "normal"
    notes: Optional[str] = ""


class DemandCreate(BaseModel):
    demand_desc: str
    demand_type: Optional[str] = ""
    related_project: Optional[str] = ""
    progress_score: int = 0
    created_by_staff: Optional[str] = ""
    responsible_staff: Optional[str] = ""
    notes: Optional[str] = ""


class DemandProgressUpdate(BaseModel):
    progress_score: int


class TaskStatusUpdate(BaseModel):
    status: str
    review_note: Optional[str] = ""


class DailyReviewRequest(BaseModel):
    store_id: str = "default_store"
    report_date: Optional[str] = None
    review_content: Optional[str] = ""
