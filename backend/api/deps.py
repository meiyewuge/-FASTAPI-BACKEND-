"""API 依赖：DB 会话 + 租户解析（Patch4：JWT 强制鉴权）+ 管理员守卫。"""

from __future__ import annotations

from fastapi import Header, HTTPException

from config import settings
from db import get_db  # noqa: F401  re-export 供路由使用
from utils import jwt_util


def get_tenant_id(authorization: str | None = Header(default=None)) -> str:
    """从 Authorization: Bearer <JWT> 解析 tenant_id。

    无 token / 格式错 / 过期 / 验签失败 → 401。
    （settings.auth_required=False 时回落默认租户，仅供本地/测试。）
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        if not settings.auth_required:
            return settings.default_tenant
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")

    try:
        payload = jwt_util.decode(token, settings.jwt_secret)
    except jwt_util.JWTError as e:
        raise HTTPException(status_code=401, detail=f"令牌无效：{e}")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="令牌缺少 tenant_id")
    return tenant_id


def require_admin(x_admin_key: str | None = Header(default=None)) -> bool:
    """管理员守卫：校验 X-Admin-Key。未配置 admin_key 则禁用管理端点。"""
    if not settings.admin_key:
        raise HTTPException(status_code=403, detail="管理端点未启用")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="管理员口令错误")
    return True
