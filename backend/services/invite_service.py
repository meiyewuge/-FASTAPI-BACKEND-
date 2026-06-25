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


def validate_and_consume(db: Session, code: str, phone: str) -> str | None:
    """校验邀约码并消费一次，返回 tenant_id；无效返回 None。"""
    rec = db.get(InviteCode, code)
    if rec is None or not rec.active:
        return None
    if rec.used_count >= rec.max_uses:
        return None
    rec.used_count += 1
    if rec.used_count >= rec.max_uses:
        rec.active = False
    tenant_id = rec.tenant_id or f"t_{phone}"
    db.commit()
    return tenant_id


def _brief(r: InviteCode) -> dict:
    return {
        "code": r.code,
        "tenant_id": r.tenant_id,
        "active": r.active,
        "max_uses": r.max_uses,
        "used_count": r.used_count,
        "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
