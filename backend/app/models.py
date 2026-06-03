from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
from .config import settings

JSONType = JSON().with_variant(JSONB, "postgresql")

# SQLite only auto-increments INTEGER PRIMARY KEY, not BIGINT
_PK_TYPE = Integer if settings.database_url.startswith("sqlite") else BigInteger
_FK_TYPE = Integer if settings.database_url.startswith("sqlite") else BigInteger


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    store_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(50), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    store_type: Mapped[str | None] = mapped_column(String(50))
    source_channel: Mapped[str | None] = mapped_column(String(50))
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    diagnoses = relationship("Diagnosis", back_populates="store")
    monthly_checkups = relationship("MonthlyCheckup", back_populates="store")


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(_FK_TYPE, ForeignKey("stores.id"), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    traffic_score: Mapped[int] = mapped_column(Integer, default=0)
    conversion_score: Mapped[int] = mapped_column(Integer, default=0)
    ticket_score: Mapped[int] = mapped_column(Integer, default=0)
    retention_score: Mapped[int] = mapped_column(Integer, default=0)
    team_score: Mapped[int] = mapped_column(Integer, default=0)
    product_score: Mapped[int] = mapped_column(Integer, default=0)
    digital_score: Mapped[int] = mapped_column(Integer, default=0)
    warning_level: Mapped[str | None] = mapped_column(String(20))
    confidence_level: Mapped[str | None] = mapped_column(String(20))
    report_url: Mapped[str | None] = mapped_column(String(255))
    ai_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at = mapped_column(DateTime, server_default=func.now())

    store = relationship("Store", back_populates="diagnoses")
    form = relationship("DiagnosisForm", back_populates="diagnosis", uselist=False)


class DiagnosisForm(Base):
    __tablename__ = "diagnosis_forms"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    diagnosis_id: Mapped[int] = mapped_column(_FK_TYPE, ForeignKey("diagnoses.id"), nullable=False)
    form_data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    calculated_metrics: Mapped[dict | None] = mapped_column(JSONType)
    validation_warnings: Mapped[list | None] = mapped_column(JSONType)
    created_at = mapped_column(DateTime, server_default=func.now())

    diagnosis = relationship("Diagnosis", back_populates="form")


class MonthlyCheckup(Base):
    __tablename__ = "monthly_checkups"
    __table_args__ = (UniqueConstraint("store_id", "check_month", name="uq_store_month"),)

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(_FK_TYPE, ForeignKey("stores.id"), nullable=False)
    check_month: Mapped[str] = mapped_column(String(7), nullable=False)
    revenue: Mapped[float | None] = mapped_column(Numeric(12, 2))
    customer_visits: Mapped[int | None] = mapped_column(Integer)
    paying_customers: Mapped[int | None] = mapped_column(Integer)
    new_customers: Mapped[int | None] = mapped_column(Integer)
    old_customers: Mapped[int | None] = mapped_column(Integer)
    average_ticket: Mapped[float | None] = mapped_column(Numeric(10, 2))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    marketing_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    product_revenue: Mapped[dict | None] = mapped_column(JSONType)
    staff_data: Mapped[dict | None] = mapped_column(JSONType)
    customer_data: Mapped[dict | None] = mapped_column(JSONType)
    channel_data: Mapped[dict | None] = mapped_column(JSONType)
    cost_data: Mapped[dict | None] = mapped_column(JSONType)
    calculated_metrics: Mapped[dict | None] = mapped_column(JSONType)
    total_score: Mapped[int | None] = mapped_column(Integer)
    people_score: Mapped[int | None] = mapped_column(Integer)
    product_score: Mapped[int | None] = mapped_column(Integer)
    place_score: Mapped[int | None] = mapped_column(Integer)
    customer_score: Mapped[int | None] = mapped_column(Integer)
    finance_score: Mapped[int | None] = mapped_column(Integer)
    digital_score: Mapped[int | None] = mapped_column(Integer)
    mom_changes: Mapped[dict | None] = mapped_column(JSONType)
    report_url: Mapped[str | None] = mapped_column(String(255))
    created_at = mapped_column(DateTime, server_default=func.now())

    store = relationship("Store", back_populates="monthly_checkups")


class AIReport(Base):
    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int] = mapped_column(_FK_TYPE, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    structured_content: Mapped[dict | None] = mapped_column(JSONType)
    raw_ai_response: Mapped[dict | None] = mapped_column(JSONType)
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_at = mapped_column(DateTime, server_default=func.now())


class Followup(Base):
    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(_PK_TYPE, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(_FK_TYPE, ForeignKey("stores.id"), nullable=False)
    admin_name: Mapped[str | None] = mapped_column(String(50))
    followup_status: Mapped[str | None] = mapped_column(String(50))
    followup_note: Mapped[str | None] = mapped_column(Text)
    recommended_service: Mapped[str | None] = mapped_column(String(100))
    created_at = mapped_column(DateTime, server_default=func.now())
