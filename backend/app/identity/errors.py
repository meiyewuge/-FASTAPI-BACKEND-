"""Structured identity/Facade errors — uniform {code, msg, data} envelope.

Business codes are stable and safe to show; HTTP status separates the classes:
  401 unauthenticated (missing/invalid/expired/revoked/version-drift session)
  403 authenticated but not authorized (disabled/left/unbound/cross-store/actor)
  400 bad request (invalid date, forbidden client-supplied identity params)
  503 dependency not ready (Daily Loop unavailable)  -> NO internal detail

No secret, token, code, session_key, openid, table name, SQL, path or stack ever
appears in a message.
"""
from __future__ import annotations

# fixed, user-facing business message for an authenticated WeChat user that has
# no active store/member binding yet
UNBOUND_MESSAGE = "账号尚未绑定门店/员工身份，请联系门店管理员"


class ApiError(Exception):
    def __init__(self, http_status: int, code: int, msg: str):
        super().__init__(f"{http_status}/{code}: {msg}")
        self.http_status = http_status
        self.code = code
        self.msg = msg

    def envelope(self) -> dict:
        return {"code": self.code, "msg": self.msg, "data": None}


def unauthenticated(msg: str = "未登录或登录已失效", code: int = 40100) -> ApiError:
    return ApiError(401, code, msg)


def forbidden(msg: str = "无权访问", code: int = 40300) -> ApiError:
    return ApiError(403, code, msg)


def unbound() -> ApiError:
    return ApiError(403, 40301, UNBOUND_MESSAGE)


def bad_request(msg: str = "请求参数错误", code: int = 40000) -> ApiError:
    return ApiError(400, code, msg)


def dependency_unavailable(msg: str = "服务暂不可用，请稍后重试", code: int = 50300) -> ApiError:
    return ApiError(503, code, msg)


def wechat_failed(msg: str = "微信登录失败，请重试", code: int = 40010) -> ApiError:
    # never carries the underlying wechat errcode/errmsg detail
    return ApiError(400, code, msg)
