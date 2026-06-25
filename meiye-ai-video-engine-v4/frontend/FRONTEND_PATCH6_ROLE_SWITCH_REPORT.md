# FRONTEND_PATCH6_ROLE_SWITCH_REPORT

## 1. 基本信息

| 项目 | 值 |
|------|------|
| **分支** | `qoder/v4-frontend-workbench` |
| **Commit** | `8ed5c83` |
| **后端基线** | `claude/v4-staging` @ `d64675f`（Patch6 @ `553ea13`） |
| **构建** | `vite build` ✅ 通过（234.66 kB / 76.22 kB gzip） |
| **时间** | 2026-06-24 |

## 2. ENABLE_ADMIN_KEY_FALLBACK 状态

**`ENABLE_ADMIN_KEY_FALLBACK = false`** ✅ 已关闭

- 代码保留 fallback 逻辑（紧急回退用），但默认值为 `false`
- `adminHeaders()` 默认只发送 `Authorization: Bearer <JWT>`
- `X-Admin-Key` 不再日常发送
- 登录页不再显示"管理员发码"入口链接
- staging 黄色标签已移除（Login.tsx 内嵌管理面板已整体移除）

## 3. 登录后 /api/me 调用

✅ **登录成功后立即调用 `GET /api/me`**

```typescript
// Login.tsx handleLogin()
const r = await login(phone.trim(), inviteCode.trim());
if (r.code === 0) {
  const meR = await fetchMe(); // ← 登录成功后立即获取角色
  navigate("/workbench", { replace: true });
}
```

- `fetchMe()` 返回 `UserProfile`：`{ phone, tenant_id, role, is_admin, permissions }`
- 存入模块级变量 `_userProfile`，`isAdmin()` / `isSuperAdmin()` / `getCurrentUserRole()` 读取
- 页面刷新后 Workbench `useEffect` 自动重新调用 `fetchMe()` 恢复角色
- `/api/me` 失败不阻塞跳转（降级为 `role=user`）

## 4. 三种角色权限显示

### super_admin（吴哥）

✅ 完整管理员后台：

| 功能 | 可见 |
|------|------|
| 生成邀请码 | ✅ |
| 邀请码列表 | ✅ |
| 作废邀请码 | ✅ |
| 授权员工为 invite_admin | ✅ |
| 取消员工发码权限 | ✅ |
| 查看管理员列表 | ✅（adminListUsers API 已对接） |

### invite_admin（被授权员工）

| 功能 | 可见 |
|------|------|
| 生成邀请码 | ✅ |
| 邀请码列表 | ✅ |
| 作废邀请码 | ✅ |
| 授权员工 | ❌ 不可见 |
| 取消授权 | ❌ 不可见 |
| 系统配置 | ❌ 不可见 |

AdminPanel 通过 Tab 切换实现：`invite_admin` 无 Tab（只显示发码管理），`super_admin` 有"邀请码管理"+"用户授权"双 Tab。

### user（普通用户）

| 行为 | 状态 |
|------|------|
| 工作台管理员按钮 | ❌ 不显示 |
| 直接访问 /admin | → 自动跳转 /workbench |
| 登录页管理员入口 | ❌ 已移除 |

## 5. 管理员接口改为 Bearer JWT

✅ 所有管理员接口仅使用 `Authorization: Bearer <JWT>`：

| 端点 | 方法 | 鉴权方式 |
|------|------|----------|
| `/api/admin/invite/generate` | POST | Bearer JWT |
| `/api/admin/invite/list` | GET | Bearer JWT |
| `/api/admin/invite/revoke` | POST | Bearer JWT |
| `/api/admin/users/grant` | POST | Bearer JWT |
| `/api/admin/users/revoke` | POST | Bearer JWT |
| `/api/admin/users/list` | GET | Bearer JWT |

**`X-Admin-Key` 日常调用：❌ 不再使用**（仅 `ENABLE_ADMIN_KEY_FALLBACK=true` 时才附加，当前默认 false）

## 6. 业务闭环保持

| 环节 | 状态 |
|------|------|
| 吴哥手机号登录 | ✅ 手机号 + 邀约码登录 |
| /api/me → super_admin | ✅ 登录后自动调用 |
| 管理员后台入口 | ✅ Workbench 顶部按钮 → /admin |
| 生成邀请码 | ✅ JWT Bearer |
| 复制邀请码 | ✅ clipboard API |
| A 台费用警告 | ✅ "🎬 A台·母视频（⚠️会产生费用）" |
| B 台 0 元标记 | ✅ "🔁 B台·裂变（0元/条）" |
| 用此裂变 | ✅ 母视频卡片上的按钮 |
| B 台数量控制 | ✅ 1-50 可控 |
| B 台本地 ffmpeg | ✅ 前端调用 |
| 播放/下载/导出 | ✅ 不受影响 |
| A 台自动触发 | ❌ 不触发 |

## 7. Staging 后端验证

| 测试项 | 状态 | 说明 |
|--------|------|------|
| /api/me 无 JWT | ✅ 401 | 未登录拒绝 |
| /api/admin/invite/list 无 JWT | ✅ 401 | 未登录拒绝 |
| /api/admin/users/list 无 JWT | ✅ 401 | 未登录拒绝 |
| /api/admin/users/grant 无 JWT | ✅ 401 | 未登录拒绝 |
| /api/admin/users/revoke 无 JWT | ✅ 401 | 未登录拒绝 |
| Build 通过 | ✅ | vite build 成功 |

> ⚠️ 完整登录联调（吴哥手机号 + 邀约码 → /api/me → super_admin → 发码 → B台裂变）需使用真实账号在 staging 浏览器验证。

## 8. 文件变更清单

| 文件 | 变更 | 行数 |
|------|------|------|
| `frontend/api/client.ts` | FALLBACK=false, 纯JWT, +用户管理API | +35/-18 |
| `frontend/pages/Login.tsx` | 登录后 fetchMe(), 移除内嵌管理面板 | +4/-238 |
| `frontend/pages/Workbench.tsx` | isAdmin() 按钮, fetchMe on mount | +10/-3 |
| `frontend/pages/AdminPanel.tsx` | 重写：role裁剪, Tab, 用户授权管理 | +202/-172 |
| `frontend/main.tsx` | 注释更新 | +2/-1 |
| `frontend/styles.css` | +admin-tabs, role-badge, btn-error/primary/logout | +91/-0 |
| **合计** | 6 files | +345/-427 |

## 9. 是否可以交 Coze 部署 staging 前端

**✅ 可以部署**

- 构建通过
- 代码已推送 `qoder/v4-frontend-workbench` @ `8ed5c83`
- staging 后端 Patch6 已就绪
- 管理员权限体系完全基于 JWT role，无硬编码密钥

## 10. 后续待做（非本次范围）

- [ ] 吴哥在 staging 浏览器完整联调验收（登录 → 发码 → B台裂变 → 下载）
- [ ] invite_admin 角色的实际授权测试（吴哥授权一个员工手机号 → 该员工登录验证）
- [ ] user 角色登录后确认管理员按钮不显示
- [ ] production 部署前确认 `ENABLE_ADMIN_KEY_FALLBACK = false`
