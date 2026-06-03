from pydantic import BaseModel, Field
from typing import Any


class StoreInfo(BaseModel):
    store_name: str
    city: str
    contact_person: str
    contact_phone: str
    store_type: str | None = None
    source_channel: str | None = None


class DiagnosisCreate(BaseModel):
    store_info: StoreInfo
    form_data: dict[str, Any]


class MonthlyCheckupCreate(BaseModel):
    store_id: int | None = None
    store_info: StoreInfo | None = None
    check_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    form_data: dict[str, Any]


class FollowupCreate(BaseModel):
    admin_name: str | None = None
    followup_status: str | None = None
    followup_note: str
    recommended_service: str | None = None
