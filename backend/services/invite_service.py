"""邀约码业务（Patch4）：生成 / 查看 / 作废 / 校验消费。

规则：无邀约码不得登录。登录时校验邀约码有效（active 且未超 max_uses），
消费一次（used_count+1），并返回绑定的 tenant_id（空则按手机号生成租户）。
"""

from __future__ import annotations

import secrets
import string

from sqlalchemy.orm import Session

from models import InviteCode

_ALPHABET = string.ascii_uppercase + string.digits


def _gen_code(n: int = 10) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def generate(db: Session, count: int = 1, tenant_id: str | None = None,
             max_uses: int = 1, note: str | None = None) -> list[dict]:
    """批量生成邀约码。"""
    out = []
    for _ in range(count):
        code = _gen_code()
        while db.get(InviteCode, code) is not None:
            code = _gen_code()
        rec = InviteCode(
            code=code, tenant_id=tenant_id, active=True,
            max_uses=max_uses, used_count=0, note=note,
        )
        db.add(rec)
        out.append(code)
    db.commit()
    return [_brief(db.get(InviteCode, c)) for c in out]


def list_codes(db: Session) -> list[dict]:
    rows = db.query(InviteCode).order_by(InviteCode.created_at.desc()).all()
    return [_brief(r) for r in rows]


def revoke(db: Session, code: str) -> bool:
    rec = db.get(InviteCode, code)
    if rec is None:
        return False
    rec.active = False
    db.commit()
    return True


def validate_and_consume(db: Session, code: str, phone: str) -> dict:
    """校验邀约码并按规则放行（Patch4.1：专属登录码可重复登录）。

    返回 {"ok": True, "tenant_id": ...} 或 {"ok": False, "code": int, "message": str}。

    规则：
    1) 首次使用（phone 未绑定且 active 且 used_count<max_uses）：绑定 phone、used_count+1、放行。
    2) 同手机号重复登录（phone 已绑定且等于本次 phone）：不增 used_count、不受 max_uses 限制、放行。
    3) 不同手机号用已绑定码：拒绝 4010「该邀请码已绑定其他手机号」。
    4) revoked/失效（active=False）：拒绝（含管理员作废后，同手机号也不能登录）。
    """
    rec = db.get(InviteCode, code)
    if rec is None or not rec.active:
        return {"ok": False, "code": 1002, "message": "邀约码无效或已用尽"}

    # 已绑定手机号：只认绑定的那台手机
    if rec.phone:
        if rec.phone != phone:
            return {"ok": False, "code": 4010, "message": "该邀请码已绑定其他手机号"}
        # 规则2：同手机号重复登录，不再消费
        return {"ok": True, "tenant_id": rec.tenant_id or f"t_{phone}"}

    # 规则1：首次使用
    if rec.used_count >= rec.max_uses:
        return {"ok": False, "code": 1002, "message": "邀约码无效或已用尽"}
    rec.phone = phone
    rec.used_count += 1
    tenant_id = rec.tenant_id or f"t_{phone}"
    db.commit()
    return {"ok": True, "tenant_id": tenant_id}


def _brief(r: InviteCode) -> dict:
    return {
        "code": r.code,
        "tenant_id": r.tenant_id,
        "phone": r.phone,
        "active": r.active,
        "max_uses": r.max_uses,
        "used_count": r.used_count,
        "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
