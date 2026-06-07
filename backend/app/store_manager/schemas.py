from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class MonthlyDiagnosisRequest(BaseModel):
    store_id: str = Field(default="default_store")
    store_name: Optional[str] = None
    diagnosis_month: Optional[str] = None
    form_data: Dict[str, Any]


class CoreIssue(BaseModel):
    id: int
    title: str
    reason: str
    data_basis: str


class WeeklyAction(BaseModel):
    issue_id: int
    action: str


class TodayTask(BaseModel):
    task_id: str
    issue_id: int
    type: str
    related: Optional[str] = ""
    priority: str
    action: str
    script: Optional[str] = ""
    deadline: Optional[str] = ""
    status: str = "待执行"


class StaffSuggestion(BaseModel):
    role: str
    suggestion: str


class StructuredReport(BaseModel):
    report_id: str
    store_id: str
    diagnosis_month: str
    generated_at: str
    core_issues: List[CoreIssue]
    weekly_actions: List[WeeklyAction]
    today_tasks: List[TodayTask]
    staff_suggestions: List[StaffSuggestion]
    risk_notes: List[str]


class MonthlyDiagnosisResponse(BaseModel):
    report_id: str
    store_id: str
    store_name: Optional[str] = None
    diagnosis_month: str
    generated_at: str
    display_text: Dict[str, str]
    structured_json: StructuredReport


class GenerateTodayTasksRequest(BaseModel):
    store_id: str = "default_store"
    report_id: Optional[str] = None
    manual_tasks: List[Dict[str, Any]] = []


class UpdateTaskStatusRequest(BaseModel):
    status: str


class TaskReviewRequest(BaseModel):
    review_status: str
    note: Optional[str] = ""
    arrived: Optional[str] = ""
    converted: Optional[str] = ""


class AdminMarkRequest(BaseModel):
    mark: str
    note: Optional[str] = ""
