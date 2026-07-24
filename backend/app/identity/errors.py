"""Structured identity errors — W1 unified envelope {code, message, trace_id, data}.

`code` is a STABLE machine string (never an int); HTTP status separates the class.
Three distinct 403 codes (STORE_UNBOUND / ROLE_FORBIDDEN / RESOURCE_FORBIDDEN) are
never collapsed into a generic "forbidden". No secret, token, code, session_key,
openid, table name, SQL, path or stack ever appears in a message.
"""
from __future__ import annotations

# machine codes (W3-01 §7). Success is the reserved code "OK".
SESSION_INVALID = "SESSION_INVALID"
SESSION_EXPIRED = "SESSION_EXPIRED"
STORE_UNBOUND = "STORE_UNBOUND"
ROLE_FORBIDDEN = "ROLE_FORBIDDEN"
RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
VALIDATION_ERROR = "VALIDATION_ERROR"
BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
RATE_LIMITED = "RATE_LIMITED"
INTERNAL_ERROR = "INTERNAL_ERROR"
DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"

# fixed, user-facing business message for an authenticated user whose account has
# no active store/member binding (used only where an endpoint requires a binding).
UNBOUND_MESSAGE = "账号尚未绑定门店/员工身份，请联系门店管理员"


class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        super().__init__(f"{http_status}/{code}: {message}")
        self.http_status = http_status
        self.code = code
        self.message = message

    def envelope(self, trace_id: str) -> dict:
        return {"code": self.code, "message": self.message,
                "trace_id": trace_id, "data": None}


def session_invalid(message: str = "未登录或登录已失效") -> ApiError:
    return ApiError(401, SESSION_INVALID, message)


def session_expired(message: str = "登录已过期，请重新登录") -> ApiError:
    return ApiError(401, SESSION_EXPIRED, message)


def store_unbound(message: str = UNBOUND_MESSAGE) -> ApiError:
    return ApiError(403, STORE_UNBOUND, message)


def role_forbidden(message: str = "当前角色无权访问") -> ApiError:
    return ApiError(403, ROLE_FORBIDDEN, message)


def resource_forbidden(message: str = "无权访问该资源") -> ApiError:
    return ApiError(403, RESOURCE_FORBIDDEN, message)


def account_disabled(message: str = "账号已停用，请联系门店管理员") -> ApiError:
    # an authenticated but disabled account/binding -> 403 ROLE_FORBIDDEN class
    return ApiError(403, ROLE_FORBIDDEN, message)


def validation_error(message: str = "请求参数错误") -> ApiError:
    return ApiError(422, VALIDATION_ERROR, message)


def rate_limited(message: str = "操作过于频繁，请稍后重试") -> ApiError:
    return ApiError(429, RATE_LIMITED, message)


def dependency_unavailable(message: str = "服务暂不可用，请稍后重试") -> ApiError:
    return ApiError(503, DEPENDENCY_UNAVAILABLE, message)


def internal_error(message: str = "服务内部错误") -> ApiError:
    return ApiError(500, INTERNAL_ERROR, message)


def wechat_failed(message: str = "微信登录失败，请重试") -> ApiError:
    # never carries the underlying wechat errcode/errmsg detail; PUBLIC login
    # failure is a validation-class rejection (bad/expired code) -> 422.
    return ApiError(422, VALIDATION_ERROR, message)
