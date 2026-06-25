"""API 依赖：DB 会话 + 租户解析（JWT 强制鉴权）+ 角色权限守卫（Patch6）。"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from services import admin_service
from utils import jwt_util


def _decode_token(authorization: str | None) -> dict | None:
    """解析 Bearer JWT；无 token 返回 None；无效/过期抛 401。"""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        return None
    try:
        return jwt_util.decode(token, settings.jwt_secret)
    except jwt_util.JWTError as e:
        raise HTTPException(status_code=401, detail=f"令牌无效：{e}")


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """从 JWT 解析当前用户 {tenant_id, phone, role}。无/过期 → 401。

    （settings.auth_required=False 时回落默认用户，仅供本地/测试。）
    """
    payload = _decode_token(authorization)
    if payload is None:
        if not settings.auth_required:
            return {"tenant_id": settings.default_tenant, "phone": None, "role": "user"}
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="令牌缺少 tenant_id")
    return {
        "tenant_id": tenant_id,
        "phone": payload.get("phone"),
        "role": payload.get("role", "user"),
    }


def get_tenant_id(user: dict = Depends(get_current_user)) -> str:
    """业务接口拿 tenant_id（据此隔离租户）。"""
    return user["tenant_id"]


def require_admin(x_admin_key: str | None = Header(default=None)) -> bool:
    """ADMIN_KEY 守卫（仅用于 bootstrap / 应急）。未配置 admin_key 则禁用。"""
    if not settings.admin_key:
        raise HTTPException(status_code=403, detail="管理端点未启用")
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="管理员口令错误")
    return True


def require_invite_permission(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """发码权限：JWT 角色为 super_admin/invite_admin 放行；
    或携带正确 X-Admin-Key（应急兜底）放行。否则 403。

    返回操作者上下文 {phone, role}（ADMIN_KEY 兜底时 role=super_admin、phone=None）。
    """
    # 应急兜底：ADMIN_KEY（前端日常不用）
    if settings.admin_key and x_admin_key == settings.admin_key:
        return {"phone": None, "role": admin_service.ROLE_SUPER, "via": "admin_key"}

    payload = _decode_token(authorization)
    if payload is None:
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    phone = payload.get("phone")
    # 以库为准重新核验角色（防 JWT 签发后被降权仍可用）
    role = admin_service.get_role(db, phone)
    if not admin_service.can_invite(role):
        raise HTTPException(status_code=403, detail="无发码权限")
    return {"phone": phone, "role": role, "via": "jwt"}


def require_super_admin(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """仅 super_admin 可访问（授权/取消授权管理员）。否则 403。"""
    payload = _decode_token(authorization)
    if payload is None:
        raise HTTPException(status_code=401, detail="未登录或缺少令牌")
    phone = payload.get("phone")
    role = admin_service.get_role(db, phone)
    if role != admin_service.ROLE_SUPER:
        raise HTTPException(status_code=403, detail="仅超级管理员可操作")
    return {"phone": phone, "role": role}
