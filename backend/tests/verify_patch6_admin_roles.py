"""Patch6 验证：管理员身份与发码权限体系。

覆盖：
- 无 super_admin 时，用 ADMIN_KEY bootstrap 吴哥手机号成功
- 已有 super_admin 后，再 bootstrap 失败
- 吴哥登录后 JWT role=super_admin
- GET /api/me 返回 is_admin=true
- super_admin 可生成邀请码
- 普通 user 调发码端点返回 403
- super_admin 可授权员工 invite_admin
- invite_admin 可生成邀请码
- invite_admin 不能授权其他管理员（403）
- revoke 后员工失去发码权限

跑法：cd backend && python tests/verify_patch6_admin_roles.py
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_patch6_test.db"

import config
import db as _db

ADMIN_KEY = "ADMINSECRET"
WUGE = "13800000001"        # 吴哥（超级管理员）
STAFF = "13800000002"       # 员工（发码员）
USER = "13800000003"        # 普通用户


def _fresh_client():
    _db.engine.dispose()
    if os.path.exists("./_patch6_test.db"):
        os.remove("./_patch6_test.db")
    config.settings.admin_key = ADMIN_KEY
    config.settings.auth_required = True
    config.settings.jwt_secret = "test-secret"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _gen_code(c, max_uses=1):
    """用 ADMIN_KEY 应急通道生成一个邀请码（供登录用）。"""
    r = c.post("/api/admin/invite/generate", json={"count": 1, "max_uses": max_uses},
               headers={"X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"][0]["code"]


def _login(c, phone):
    code = _gen_code(c)
    r = c.post("/api/auth/login", json={"phone": phone, "invite_code": code})
    assert r.json()["code"] == 0, r.json()
    return r.json()["data"]


def main():
    c = _fresh_client()
    admin_h = {"X-Admin-Key": ADMIN_KEY}

    # 1) 无 super_admin → ADMIN_KEY bootstrap 吴哥成功
    r = c.post("/api/admin/bootstrap", json={"phone": WUGE, "note": "initial super admin"},
               headers=admin_h)
    assert r.json()["code"] == 0 and r.json()["data"]["role"] == "super_admin", r.json()
    print("  ✔ bootstrap 吴哥为 super_admin 成功")

    # 2) 已有 super_admin → 再 bootstrap 失败
    r = c.post("/api/admin/bootstrap", json={"phone": "13800009999"}, headers=admin_h)
    assert r.json()["code"] == 4090, r.json()
    print("  ✔ 已有超级管理员 → 重复 bootstrap 被拒（4090）")

    # bootstrap 必须 ADMIN_KEY 保护
    assert c.post("/api/admin/bootstrap", json={"phone": WUGE}).status_code == 401
    print("  ✔ bootstrap 缺 X-Admin-Key → 401")

    # 3) 吴哥登录 → JWT role=super_admin
    wuge = _login(c, WUGE)
    assert wuge["role"] == "super_admin", wuge
    wuge_h = {"Authorization": f"Bearer {wuge['token']}"}
    print("  ✔ 吴哥登录 JWT role=super_admin")

    # 4) GET /api/me → is_admin=true
    r = c.get("/api/me", headers=wuge_h).json()["data"]
    assert r["is_admin"] is True and r["role"] == "super_admin", r
    assert "invite:generate" in r["permissions"] and "admin:grant" in r["permissions"]
    print(f"  ✔ /api/me is_admin=true, permissions={r['permissions']}")

    # 5) super_admin 用 JWT（无 ADMIN_KEY）生成邀请码
    r = c.post("/api/admin/invite/generate", json={"count": 2}, headers=wuge_h)
    assert r.json()["code"] == 0 and r.json()["data"]["count"] == 2, r.json()
    print("  ✔ super_admin 用 JWT 发码成功（不需 ADMIN_KEY）")

    # 6) 普通 user 调发码端点 → 403
    user = _login(c, USER)
    assert user["role"] == "user", user
    user_h = {"Authorization": f"Bearer {user['token']}"}
    assert c.get("/api/me", headers=user_h).json()["data"]["is_admin"] is False
    r = c.post("/api/admin/invite/generate", json={"count": 1}, headers=user_h)
    assert r.status_code == 403 and r.json()["code"] == 1001, r.json()
    print("  ✔ 普通 user 发码 → 403")

    # 7) super_admin 授权员工为 invite_admin
    r = c.post("/api/admin/users/grant",
               json={"phone": STAFF, "role": "invite_admin", "note": "发码员"},
               headers=wuge_h)
    assert r.json()["code"] == 0 and r.json()["data"]["role"] == "invite_admin", r.json()
    print("  ✔ super_admin 授权员工 invite_admin")

    # 8) invite_admin 登录 → 可发码
    staff = _login(c, STAFF)
    assert staff["role"] == "invite_admin", staff
    staff_h = {"Authorization": f"Bearer {staff['token']}"}
    assert c.get("/api/me", headers=staff_h).json()["data"]["is_admin"] is True
    r = c.post("/api/admin/invite/generate", json={"count": 1}, headers=staff_h)
    assert r.json()["code"] == 0, r.json()
    print("  ✔ invite_admin 可发码")

    # 9) invite_admin 不能授权其他管理员 → 403
    r = c.post("/api/admin/users/grant", json={"phone": "13800008888", "role": "invite_admin"},
               headers=staff_h)
    assert r.status_code == 403 and r.json()["code"] == 1001, r.json()
    print("  ✔ invite_admin 授权他人 → 403")

    # 10) revoke 后员工失去发码权限（用同一旧 token，以库为准即时生效）
    r = c.post("/api/admin/users/revoke", json={"phone": STAFF}, headers=wuge_h)
    assert r.json()["code"] == 0 and r.json()["data"]["role"] == "user", r.json()
    r = c.post("/api/admin/invite/generate", json={"count": 1}, headers=staff_h)
    assert r.status_code == 403, r.json()
    assert c.get("/api/me", headers=staff_h).json()["data"]["is_admin"] is False
    print("  ✔ revoke 后员工立即失去发码权限（旧 token 也 403）")

    # 不能撤销唯一超级管理员
    r = c.post("/api/admin/users/revoke", json={"phone": WUGE}, headers=wuge_h)
    assert r.json()["code"] == 4091, r.json()
    print("  ✔ 不能撤销唯一超级管理员（4091）")

    _db.engine.dispose()
    if os.path.exists("./_patch6_test.db"):
        os.remove("./_patch6_test.db")
    print("\n✅ Patch6 管理员身份与发码权限 ALL PASSED")


if __name__ == "__main__":
    main()
