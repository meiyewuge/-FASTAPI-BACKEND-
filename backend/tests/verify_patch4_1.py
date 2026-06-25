"""Patch4.1 验证：邀约码可重复登录（专属登录码绑定手机号）。

覆盖 6 项：
- 首次「手机号 + 邀请码」登录成功（绑定手机号）
- 同手机号二次登录成功
- 同手机号二次登录 used_count 不增加
- 不同手机号登录同一码失败（4010）
- revoked 后同手机号登录失败
- JWT 仍可正常访问业务 API

跑法：cd backend && python tests/verify_patch4_1.py
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_patch4_1_test.db"

import config
import db as _db


def _fresh_client():
    _db.engine.dispose()
    if os.path.exists("./_patch4_1_test.db"):
        os.remove("./_patch4_1_test.db")
    config.settings.admin_key = "ADMINSECRET"
    config.settings.auth_required = True
    config.settings.jwt_secret = "test-secret"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _used_count(code: str) -> int:
    from models import InviteCode
    s = _db.SessionLocal()
    n = s.get(InviteCode, code).used_count
    s.close()
    return n


def main():
    c = _fresh_client()
    admin_h = {"X-Admin-Key": "ADMINSECRET"}
    PHONE = "13800000000"
    OTHER = "13911112222"

    # 生成一个 max_uses=1 的专属登录码
    code = c.post("/api/admin/invite/generate", json={"count": 1, "max_uses": 1},
                  headers=admin_h).json()["data"]["items"][0]["code"]
    print(f"  邀请码={code}（max_uses=1）")

    # 1) 首次 手机号+邀请码 登录成功，绑定手机号
    r = c.post("/api/auth/login", json={"phone": PHONE, "invite_code": code})
    assert r.json()["code"] == 0, r.json()
    token1 = r.json()["data"]["token"]
    assert _used_count(code) == 1, _used_count(code)
    print("  ✔ 首次手机号+邀请码登录成功（used_count=1，已绑定）")

    # 2) 同手机号二次登录成功（签发新 JWT）
    r = c.post("/api/auth/login", json={"phone": PHONE, "invite_code": code})
    assert r.json()["code"] == 0, r.json()
    token2 = r.json()["data"]["token"]
    assert token2 and isinstance(token2, str)
    print("  ✔ 同手机号二次登录成功（签发新 JWT）")

    # 3) 同手机号二次登录 used_count 不增加（仍为 1，不受 max_uses 限制）
    assert _used_count(code) == 1, _used_count(code)
    print("  ✔ 同手机号二次登录 used_count 未增加（仍=1）")

    # 4) 不同手机号登录同一码失败 → 4010
    r = c.post("/api/auth/login", json={"phone": OTHER, "invite_code": code})
    assert r.json()["code"] == 4010, r.json()
    assert "已绑定其他手机号" in r.json()["message"]
    print("  ✔ 不同手机号登录同一码 → 4010")

    # 5) revoked 后，同手机号也不能登录
    assert c.post("/api/admin/invite/revoke", json={"code": code}, headers=admin_h).json()["code"] == 0
    r = c.post("/api/auth/login", json={"phone": PHONE, "invite_code": code})
    assert r.json()["code"] == 1002, r.json()
    print("  ✔ 作废后同手机号登录失败（1002）")

    # 6) JWT 仍可正常访问业务 API
    for tok in (token1, token2):
        rr = c.get("/api/tasks", headers={"Authorization": f"Bearer {tok}"})
        assert rr.status_code == 200 and rr.json()["code"] == 0, rr.json()
    print("  ✔ 已签发 JWT 仍可正常访问业务 API")

    _db.engine.dispose()
    if os.path.exists("./_patch4_1_test.db"):
        os.remove("./_patch4_1_test.db")
    print("\n✅ Patch4.1 邀约码可重复登录 ALL PASSED")


if __name__ == "__main__":
    main()
