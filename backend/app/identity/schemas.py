"""OpenAPI response models for the W3-01 identity operations (R1 P1-2).

These pin a real machine contract for the three operations so the generated
OpenAPI carries concrete success/error envelope schemas (not empty {} or the
default HTTPValidationError). They mirror the runtime responses produced by
identity.envelope and AUTH_CONTRACT_MATRIX.csv exactly.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginData(BaseModel):
    token: str = Field(..., description="opaque bearer token (256-bit)")
    expires_at: str = Field(..., description="ISO-8601 session expiry")
    expires_in: int = Field(..., description="seconds until expiry (86400)")
    bound: bool = Field(..., description="true iff an active store binding exists")


class MeData(BaseModel):
    bound: bool = Field(..., description="true iff an active store binding exists")
    role: Optional[str] = Field(None, description="owner|manager|staff (bound only)")
    store_id: Optional[str] = Field(None, description="opaque store_<opaque12> (bound only)")
    member_id: Optional[str] = Field(None, description="opaque mbr_<opaque12> (bound only)")


class LoginResponse(BaseModel):
    code: str = Field("OK", description="machine code; 'OK' on success")
    message: str = "ok"
    trace_id: str
    data: LoginData


class MeResponse(BaseModel):
    code: str = Field("OK", description="machine code; 'OK' on success")
    message: str = "ok"
    trace_id: str
    data: MeData


class LogoutResponse(BaseModel):
    code: str = Field("OK", description="machine code; 'OK' on success")
    message: str = "ok"
    trace_id: str
    data: Optional[dict] = Field(None, description="always null on logout")


class ErrorEnvelope(BaseModel):
    code: str = Field(..., description="machine error code, e.g. SESSION_INVALID")
    message: str = Field(..., description="safe human message; no secret/stack/SQL")
    trace_id: str
    data: Optional[dict] = Field(None, description="always null on error")
