"""管理员身份与发码权限体系（Patch6）。

角色：super_admin（全权，可授权他人）/ invite_admin（仅发码）/ user（默认）。
权限：
- 发码（生成/查看/作废邀请码）：super_admin、invite_admin
- 授权/取消授权管理员：仅 super_admin
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import AdminUser

ROLE_SUPER = "super_admin"
ROLE_INVITE = "invite_admin"
ROLE_USER = "user"

# 各角色权限点（供 /api/me 返回，前端据此渲染入口）
PERMISSIONS = {
    ROLE_SUPER: ["invite:generate", "invite:list", "invite:revoke", "admin:grant", "admin:revoke"],
    ROLE_INVITE: ["invite:generate", "invite:list", "invite:revoke"],
    ROLE_USER: [],
}


def has_super_admin(db: Session) -> bool:
    return (
        db.query(AdminUser)
        .filter(AdminUser.role == ROLE_SUPER, AdminUser.status == "active")
        .first()
        is not None
    )


def get_role(db: Session, phone: str | None) -> str:
    """查 phone 的有效角色；不在表中或被禁用 → user。"""
    if not phone:
        return ROLE_USER
    u = db.get(AdminUser, phone)
    if u is None or u.status != "active":
        return ROLE_USER
    return u.role


def can_invite(role: str) -> bool:
    return role in (ROLE_SUPER, ROLE_INVITE)


def permissions_of(role: str) -> list[str]:
    return PERMISSIONS.get(role, [])


def bootstrap_super_admin(db: Session, phone: str, note: str | None = None) -> dict:
    """一次性初始化超级管理员。仅当系统无任何 active super_admin 时可执行。

    返回 {"ok": True, "phone", "role"} 或 {"ok": False, "code", "message"}。
    """
    if has_super_admin(db):
        return {"ok": False, "code": 4090, "message": "系统已存在超级管理员，禁止重复初始化"}
    u = db.get(AdminUser, phone)
    if u is None:
        u = AdminUser(phone=phone)
        db.add(u)
    u.role = ROLE_SUPER
    u.status = "active"
    u.created_by = "system"
    u.note = note or "initial super admin"
    db.commit()
    return {"ok": True, "phone": phone, "role": ROLE_SUPER}


def grant(db: Session, operator_phone: str, phone: str, role: str, note: str | None = None) -> dict:
    """授权员工为管理员（仅 super_admin 可调，权限校验在依赖层）。"""
    if role not in (ROLE_INVITE, ROLE_SUPER):
        return {"ok": False, "code": 2001, "message": f"不支持的角色：{role}"}
    u = db.get(AdminUser, phone)
    if u is None:
        u = AdminUser(phone=phone)
        db.add(u)
    u.role = role
    u.status = "active"
    u.created_by = operator_phone
    if note is not None:
        u.note = note
    db.commit()
    return {"ok": True, "phone": phone, "role": role}


def revoke(db: Session, phone: str) -> dict:
    """取消授权：降级为普通用户（禁用管理员身份）。不能撤销最后一个 super_admin。"""
    u = db.get(AdminUser, phone)
    if u is None or u.status != "active" or u.role == ROLE_USER:
        return {"ok": False, "code": 3001, "message": "该手机号不是有效管理员"}
    if u.role == ROLE_SUPER:
        others = (
            db.query(AdminUser)
            .filter(AdminUser.role == ROLE_SUPER, AdminUser.status == "active",
                    AdminUser.phone != phone)
            .first()
        )
        if others is None:
            return {"ok": False, "code": 4091, "message": "不能撤销唯一的超级管理员"}
    u.status = "disabled"
    u.role = ROLE_USER
    db.commit()
    return {"ok": True, "phone": phone, "role": ROLE_USER}


def list_admins(db: Session) -> list[dict]:
    rows = (
        db.query(AdminUser)
        .filter(AdminUser.status == "active", AdminUser.role != ROLE_USER)
        .order_by(AdminUser.created_at.desc())
        .all()
    )
    return [
        {
            "phone": r.phone,
            "role": r.role,
            "status": r.status,
            "created_by": r.created_by,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
