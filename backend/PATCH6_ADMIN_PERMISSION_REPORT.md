# Patch6 报告：管理员身份与发码权限体系

> 范围：**后端 only**（不碰前端 / 不部署 / 不碰生产）。基于 `claude/v4-staging` 继续，独立 commit 可回滚。
> 目标：从「前端输入 ADMIN_KEY 调接口发码」升级为「吴哥账号登录后凭身份拥有超级管理员权限」。

| 项 | 值 |
|----|----|
| **commit** | `553ea13`（`Patch6 admin role and invite permission`） |
| 分支 | `claude/v4-staging`（已推送 origin） |
| 状态 | ✅ 已完成并验证（12 项测试全过 + 回归全过） |

---

## 验收结论（对照吴哥 7 点）

| # | 验收项 | 结论 |
|---|----|----|
| 1 | `/api/me` 返回 `{phone, tenant_id, role, is_admin, permissions}` | ✅ 已实现（下方有三角色实测样本） |
| 2 | bootstrap：仅无 super_admin 时、ADMIN_KEY 保护、吴哥手机号初始化、重复必拒 | ✅ 全部满足（重复→4090，缺 key→401） |
| 3 | 登录 JWT 写入 role（super_admin/invite_admin/user） | ✅ 已实现（按 `admin_users` 判定） |
| 4 | 发码端点改 JWT 权限（super/invite 放行，user→403） | ✅ 已实现（ADMIN_KEY 仅应急兜底） |
| 5 | 员工授权（仅 super_admin grant/revoke，invite_admin 不能授权） | ✅ 已实现（invite_admin 授权→403） |
| 6 | 测试 10 项 | ✅ 全过（实际 12 项，见测试段） |
| 7 | 输出 `PATCH6_ADMIN_PERMISSION_REPORT.md` | ✅ 本文件 |

### `/api/me` 三角色实测样本（sandbox 真实跑通）

```json
super_admin  => {"phone":"13800000001","tenant_id":"t_13800000001","role":"super_admin","is_admin":true,"permissions":["invite:generate","invite:list","invite:revoke","admin:grant","admin:revoke"]}
invite_admin => {"phone":"13800000002","tenant_id":"t_13800000002","role":"invite_admin","is_admin":true,"permissions":["invite:generate","invite:list","invite:revoke"]}
user         => {"phone":"13800000003","tenant_id":"t_13800000003","role":"user","is_admin":false,"permissions":[]}
# user 调 POST /api/admin/invite/generate → HTTP 403
```

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

## 前端 Qoder 如何切换到 JWT role 模式

Qoder 已完成兼容预留（`fetchMe()` / `role` / `ENABLE_ADMIN_KEY_FALLBACK` / `isAdmin()` / `isSuperAdmin()` / `adminHeaders`）。后端 Patch6 与之对齐如下：

| 前端预留 | 后端对应 | 切换动作 |
|----|----|----|
| `fetchMe()` | `GET /api/me` → `{phone,tenant_id,role,is_admin,permissions}` | 登录后直接调用，字段即用 |
| `role` | JWT 内 `role` + `/api/me.role`（三值：`super_admin`/`invite_admin`/`user`） | 直接读取，无需映射 |
| `isAdmin()` | `/api/me.is_admin`（= role ∈ {super_admin, invite_admin}） | 用 `is_admin` 控制「管理面板」显隐 |
| `isSuperAdmin()` | `role === "super_admin"`（或 `permissions` 含 `admin:grant`） | 控制「员工授权」能力显隐 |
| `adminHeaders` | `Authorization: Bearer <JWT>`（**不再带 X-Admin-Key**） | 见下方开关 |
| `ENABLE_ADMIN_KEY_FALLBACK` | 后端 `require_invite_permission` 同时接受 JWT 角色与 X-Admin-Key | 平滑切换：先 `true` 双轨，验证 JWT 链路 OK 后切 `false` |

**切换步骤（建议）**
1. 后端部署 + bootstrap 吴哥为 super_admin。
2. 前端保持 `ENABLE_ADMIN_KEY_FALLBACK=true`：`adminHeaders` 暂可带 JWT；后端 JWT 角色已能放行。
3. 验证吴哥/员工登录后 `fetchMe()` 返回正确 role、发码端点 JWT 放行、user→403。
4. 验证通过后把 `ENABLE_ADMIN_KEY_FALLBACK` 切 `false`，`adminHeaders` 只带 `Bearer JWT`，前端彻底不再持有/发送 ADMIN_KEY。
5. ADMIN_KEY 此后仅由运维保管，用于 bootstrap / 应急。

**入口渲染口径**
```
role=super_admin → 显示“管理员后台”（发码 + 员工授权）
role=invite_admin → 只显示“发码管理”
role=user        → 不显示任何管理员入口
```

> 注意：后端发码/授权端点**每次以 DB 角色为准核验**，前端隐藏入口只是 UX；即使前端绕过，后端对 user 仍返回 403，对被 revoke 的员工旧 JWT 也即时失效。

---

## 未决事项 / 风险

1. 业务 JWT（tenant 访问）在 `exp` 前仍有效；发码/授权端点已做 DB 即时核验，被降权管理员的发码权限立即失效，但其普通业务访问需待 token 过期（与全局「JWT 无吊销」一致）。
2. bootstrap 仅一次；若需迁移超管或紧急恢复，靠 `ADMIN_KEY` 应急通道（仍可发码）。
3. 当前仅 `super_admin` / `invite_admin` / `user` 三级，未做更细粒度权限点配置；如需「按门店/按租户」的发码范围限制，待后续。
