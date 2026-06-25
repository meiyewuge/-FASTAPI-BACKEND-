# Patch6 报告：管理员身份与发码权限体系

> 范围：**后端 only**（不碰前端 / 不部署 / 不碰生产）。基于 `claude/v4-staging` 继续，独立 commit 可回滚。
> 目标：从「前端输入 ADMIN_KEY 调接口发码」升级为「吴哥账号登录后凭身份拥有超级管理员权限」。

---

## 1. 角色权限体系

新增表 **`admin_users`**（主键 `phone`）：

| 字段 | 类型 | 说明 |
|----|----|----|
| `phone` | VARCHAR(32) PK | 管理员手机号 |
| `role` | VARCHAR(16) | `super_admin` / `invite_admin` / `user` |
| `status` | VARCHAR(16) | `active` / `disabled` |
| `created_by` | VARCHAR(32) | 授权人 phone（bootstrap 为 `system`） |
| `note` | VARCHAR(255) | 备注 |
| `created_at` | DATETIME | 创建时间 |

**角色与权限**

| role | 发码（生成/查看/作废邀请码） | 授权/取消授权管理员 | 使用系统 |
|----|:--:|:--:|:--:|
| `super_admin`（吴哥本人） | ✅ | ✅ | ✅ |
| `invite_admin`（发码员） | ✅ | ❌ | ✅ |
| `user`（普通用户，不入表） | ❌ | ❌ | ✅ |

权限点（`/api/me` 返回，前端据此渲染入口）：
- `super_admin`：`invite:generate/list/revoke` + `admin:grant/revoke`
- `invite_admin`：`invite:generate/list/revoke`
- `user`：`[]`

---

## 2. 初始超级管理员 bootstrap

**端点**：`POST /api/admin/bootstrap`，Header `X-Admin-Key: <ADMIN_KEY>`

```
请求：{ "phone": "吴哥手机号", "note": "initial super admin" }
返回：{ "code":0, "data":{ "ok":true, "phone":"...", "role":"super_admin" } }
```

约束（全部已实现并测试）：
- 仅当系统**无任何 active super_admin** 时可执行；已存在 → `code:4090` 拒绝。
- 必须 `X-Admin-Key` 保护（缺/错 → 401）。
- 手机号**由请求提供，不写死**。
- `ADMIN_KEY` 只作初始化/应急密钥，**不作为长期发码方式**。

---

## 3. 登录 JWT 带角色 + `/api/me`

**登录**：`POST /api/auth/login {phone, invite_code}`
- 校验邀请码（沿用 Patch4/4.1）→ 成功后**按 `admin_users` 判定 role** 写入 JWT payload：
  `{ tenant_id, phone, role }`（非管理员 role=`user`）。
- 返回 `{ token, tenant_id, role }`。

**新增** `GET /api/me`（带 JWT）：
```
{ "phone":"...", "tenant_id":"...", "role":"super_admin",
  "is_admin":true, "permissions":[...] }
```
> role 以 DB 实时查询为准（JWT 签发后被授权/降权也能正确反映）。

---

## 4. 发码端点改为 JWT 角色权限 + 员工授权

**发码端点**（`/api/admin/invite/generate|list|revoke`）守卫由 `X-Admin-Key` 改为
**`require_invite_permission`**：
- JWT 角色 ∈ {super_admin, invite_admin} → 放行；
- 或携带正确 `X-Admin-Key`（**应急兜底**，前端日常不用）→ 放行；
- 普通 user → **403**。
- 角色**以 DB 为准重新核验**：管理员被 revoke 后，旧 JWT 立即失效。

**新增授权端点**（仅 `super_admin`，`require_super_admin`）：
- `POST /api/admin/users/grant  { phone, role:"invite_admin", note }`
- `POST /api/admin/users/revoke { phone }` —— 降级为 user；**不能撤销唯一 super_admin**（→ `code:4091`）。
- `GET  /api/admin/users/list` —— 当前管理员列表。

> `invite_admin` 调 grant/revoke → 403（不能授权他人）。

---

## 5. 测试（`tests/verify_patch6_admin_roles.py`，12 项全过 ✅）

```
✔ bootstrap 吴哥为 super_admin 成功
✔ 已有超级管理员 → 重复 bootstrap 被拒（4090）
✔ bootstrap 缺 X-Admin-Key → 401
✔ 吴哥登录 JWT role=super_admin
✔ /api/me is_admin=true, permissions=[...]
✔ super_admin 用 JWT 发码成功（不需 ADMIN_KEY）
✔ 普通 user 发码 → 403
✔ super_admin 授权员工 invite_admin
✔ invite_admin 可发码
✔ invite_admin 授权他人 → 403
✔ revoke 后员工立即失去发码权限（旧 token 也 403）
✔ 不能撤销唯一超级管理员（4091）
```

回归：`verify_patch4 / verify_patch4_1 / verify_patch5 / test_volcano_pipeline / test_b9_local_remix` 全过。

---

## 改动文件

| 文件 | 变更 |
|----|----|
| `models/admin_user.py` | 新增 `AdminUser` 表 |
| `models/__init__.py` | 注册 `AdminUser` |
| `services/admin_service.py` | 新增：`bootstrap_super_admin / get_role / can_invite / permissions_of / grant / revoke / list_admins / has_super_admin` |
| `api/deps.py` | 新增 `get_current_user / require_invite_permission / require_super_admin`；`get_tenant_id` 基于 `get_current_user` |
| `api/routes.py` | 登录注入 role；新增 `/me /admin/bootstrap /admin/users/{grant,revoke,list}`；发码端点改 JWT 角色守卫 |
| `schemas/dto.py` | `BootstrapIn / GrantIn / UserRevokeIn` |
| `tests/verify_patch6_admin_roles.py` | 新增（12 项） |

**新增错误码**：`4090`（已存在超级管理员）、`4091`（不能撤销唯一超级管理员）；无权 → `403`（`{code:1001}`）。

---

## 上线顺序（运维执行，本补丁不部署）

```
部署后端
 ↓
POST /api/admin/bootstrap  (X-Admin-Key + 吴哥手机号)  → 设初始超管
 ↓
给吴哥一个邀请码（应急通道生成）
 ↓
吴哥登录 → 凭身份发码 / 授权员工 invite_admin
```

- `ADMIN_KEY` / `JWT_SECRET` 必须在生产 `.env` 配置，**未写入代码**。
- `admin_users` 为新表，`create_all` 自动建，无需手工迁移。

---

## 给前端（Qoder）的对接口径

```
管理员入口不再是“输入 ADMIN_KEY 发码”；
而是吴哥正常登录后，前端调用 GET /api/me：
- role=super_admin → 显示“管理员后台”（发码 + 员工授权）
- role=invite_admin → 只显示“发码管理”
- role=user        → 不显示任何管理员入口
发码/授权请求统一带 Authorization: Bearer <JWT>，不再传 ADMIN_KEY。
```

---

## 未决事项 / 风险

1. 业务 JWT（tenant 访问）在 `exp` 前仍有效；发码/授权端点已做 DB 即时核验，被降权管理员的发码权限立即失效，但其普通业务访问需待 token 过期（与全局「JWT 无吊销」一致）。
2. bootstrap 仅一次；若需迁移超管或紧急恢复，靠 `ADMIN_KEY` 应急通道（仍可发码）。
3. 当前仅 `super_admin` / `invite_admin` / `user` 三级，未做更细粒度权限点配置；如需「按门店/按租户」的发码范围限制，待后续。
