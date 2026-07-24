"""Structured identity audit logging (W3-01 §6).

Emits one structured log line per identity security event (login success/failure,
session issue, session revoke, binding-status rejection). NEVER includes a raw
code, token, openid, session_key, secret, or Authorization header — only
non-sensitive fields (event name, app_user_id, machine code, trace_id, a client
key that is already an opaque hash).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("identity_audit")

# fields that must never be logged even if a caller passes them by mistake.
_FORBIDDEN = {"token", "raw_token", "code", "openid", "session_key", "secret",
              "authorization", "app_secret", "wechat_app_secret"}


def audit(event: str, *, trace_id: Optional[str] = None,
          app_user_id: Optional[int] = None, code: Optional[str] = None,
          **fields: Any) -> None:
    payload: Dict[str, Any] = {"event": event}
    if trace_id is not None:
        payload["trace_id"] = trace_id
    if app_user_id is not None:
        payload["app_user_id"] = app_user_id
    if code is not None:
        payload["code"] = code
    for k, v in fields.items():
        if k.lower() in _FORBIDDEN:
            continue
        payload[k] = v
    logger.info("identity_audit %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
