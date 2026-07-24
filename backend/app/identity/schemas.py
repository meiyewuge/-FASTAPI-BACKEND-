"""OpenAPI response models for the W3-01 identity operations (R1 P1-2 / R2 P1-1).

These pin a real machine contract so the generated OpenAPI carries concrete
success/error envelope schemas that match the runtime responses and
AUTH_CONTRACT_MATRIX.csv exactly.

R2 P1-1 hardening:
  - all four envelope fields (code, message, trace_id, data) are REQUIRED on every
    success and error schema (no field carries a default, so none drops out of
    `required`);
  - success `code` is the literal "OK";
  - logout success `data` and every error `data` are typed null-only and required.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class LoginData(BaseModel):
    token: str
    expires_at: str
    expires_in: int
    bound: bool


class MeData(BaseModel):
    bound: bool
    role: Optional[str] = None        # present but nullable when unbound
    store_id: Optional[str] = None    # opaque store_<opaque12> (bound only)
    member_id: Optional[str] = None   # opaque mbr_<opaque12> (bound only)


class LoginResponse(BaseModel):
    code: Literal["OK"]
    message: str
    trace_id: str
    data: LoginData


class MeResponse(BaseModel):
    code: Literal["OK"]
    message: str
    trace_id: str
    data: MeData


class LogoutResponse(BaseModel):
    code: Literal["OK"]
    message: str
    trace_id: str
    data: None  # required and only null


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    trace_id: str
    data: None  # required and only null
