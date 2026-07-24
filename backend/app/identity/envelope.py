"""W1 unified response envelope {code, message, trace_id, data} (W3-01 §4).

All four fields are ALWAYS present. Success uses the reserved code "OK"; `data`
may be an object or null but is never missing/undefined. trace_id is per-request
(set by middleware) and echoed on every response, success or error.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import Request

OK = "OK"


def new_trace_id() -> str:
    return "trace_" + uuid.uuid4().hex


def trace_id_of(request: Optional[Request]) -> str:
    """The request-scoped trace id set by TraceIdMiddleware, or a fresh one."""
    if request is not None:
        tid = getattr(request.state, "trace_id", None)
        if tid:
            return tid
    return new_trace_id()


def ok(data: Any, request: Optional[Request] = None, message: str = "ok") -> dict:
    return {"code": OK, "message": message,
            "trace_id": trace_id_of(request), "data": data}
