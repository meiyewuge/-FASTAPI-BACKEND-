"""Patch4 验证：邀约码 + JWT 鉴权。

覆盖：
- 无 JWT 访问业务 API → 401（统一 {code:1001}）
- 管理员生成邀约码（X-Admin-Key）
- 手机号 + 邀约码登录 → 签发 JWT；带 JWT 访问业务 API 放行
- 无邀约码 / 无效邀约码 → 拒绝登录
- 邀约码用尽 → 作废，二次登录失败
- 作废邀约码后登录失败
- 过期 / 篡改 token → 401
跑法：cd backend && python tests/verify_patch4.py
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_patch4_test.db"

import config
import db as _db


def _fresh_client():
    _db.engine.dispose()
    if os.path.exists("./_patch4_test.db"):
        os.remove("./_patch4_test.db")
    config.settings.admin_key = "ADMINSECRET"
    config.settings.auth_required = True
    config.settings.jwt_secret = "test-secret"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def main():
    c = _fresh_client()
    admin_h = {"X-Admin-Key": "ADMINSECRET"}

    # 1) 无 JWT → 401
    r = c.get("/api/tasks")
    assert r.status_code == 401, r.status_code
    assert r.json()["code"] == 1001, r.json()
    print("  ✔ 无 JWT 业务 API → 401")

    # 2) 管理端点需 X-Admin-Key
    assert c.post("/api/admin/invite/generate", json={"count": 1}).status_code == 401
    print("  ✔ 管理端点缺 X-Admin-Key → 401")

    # 3) 生成邀约码（max_uses=1）
    r = c.post("/api/admin/invite/generate", json={"count": 2, "max_uses": 1}, headers=admin_h)
    assert r.status_code == 200, r.text
    codes = [it["code"] for it in r.json()["data"]["items"]]
    assert len(codes) == 2
    print(f"  ✔ 管理员生成邀约码：{codes}")

    # 4) 无邀约码不得登录（schema 必填 → 422）
    assert c.post("/api/auth/login", json={"phone": "13800000000"}).status_code == 422
    # 无效邀约码 → 业务拒绝
    r = c.post("/api/auth/login", json={"phone": "13800000000", "invite_code": "NOPE"})
    assert r.json()["code"] == 1002, r.json()
    print("  ✔ 无/无效邀约码 → 拒绝登录")

    # 5) 正确邀约码 → 登录签发 JWT
    r = c.post("/api/auth/login", json={"phone": "13800000000", "invite_code": codes[0]})
    assert r.json()["code"] == 0, r.json()
    token = r.json()["data"]["token"]
    tenant_id = r.json()["data"]["tenant_id"]
    assert tenant_id == "t_13800000000"
    print(f"  ✔ 登录成功，签发 JWT，tenant={tenant_id}")

    # 6) 带 JWT 访问业务 API 放行
    auth_h = {"Authorization": f"Bearer {token}"}
    r = c.get("/api/tasks", headers=auth_h)
    assert r.status_code == 200 and r.json()["code"] == 0
    print("  ✔ 带 JWT 业务 API 放行")

    # 7) 该码已绑定 13800000000；换手机号登录 → 4010（Patch4.1）
    r = c.post("/api/auth/login", json={"phone": "13900000000", "invite_code": codes[0]})
    assert r.json()["code"] == 4010, r.json()
    print("  ✔ 已绑定码换手机号 → 4010")

    # 8) 作废邀约码 → 登录失败
    assert c.post("/api/admin/invite/revoke", json={"code": codes[1]}, headers=admin_h).json()["code"] == 0
    assert c.post("/api/auth/login", json={"phone": "13700000000", "invite_code": codes[1]}).json()["code"] == 1002
    print("  ✔ 作废邀约码 → 登录失败")

    # 9) 篡改 token → 401
    bad = {"Authorization": f"Bearer {token[:-2]}xx"}
    assert c.get("/api/tasks", headers=bad).status_code == 401
    print("  ✔ 篡改 token → 401")

    # 10) 过期 token → 401
    from utils import jwt_util
    expired = jwt_util.encode({"tenant_id": "t_x"}, config.settings.jwt_secret, ttl_seconds=-10)
    assert c.get("/api/tasks", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    print("  ✔ 过期 token → 401")

    # 11) 管理员查看邀约码列表
    r = c.get("/api/admin/invite/list", headers=admin_h)
    assert r.json()["data"]["total"] == 2
    print("  ✔ 管理员查看邀约码列表")

    _db.engine.dispose()
    if os.path.exists("./_patch4_test.db"):
        os.remove("./_patch4_test.db")
    print("\n✅ Patch4 邀约码 + JWT ALL PASSED")


if __name__ == "__main__":
    main()
