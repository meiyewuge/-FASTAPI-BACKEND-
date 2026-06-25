# ADMIN_INVITE_PANEL_REPORT.md
> 管理员邀约码管理页 | P0 发码后台 | commit 待提交

---

## 1. 变更文件清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `frontend/api/client.ts` | +81 行 | 新增 admin API 函数（generate/list/revoke）+ ADMIN_KEY sessionStorage 管理 |
| `frontend/pages/AdminPanel.tsx` | 新建 247 行 | 完整管理员页面：密钥验证 + 生成表单 + 列表 + 作废 + 复制 |
| `frontend/main.tsx` | +10 行 | 新增 `/admin` 路由（RequireAuth 保护） |
| `frontend/pages/Workbench.tsx` | +1 行 | 顶部栏新增"管理员"按钮 |
| `frontend/styles.css` | +181 行 | 管理员页面全部样式 |

---

## 2. 功能实现

### 2.1 密钥验证

- 进入 `/admin` 页面时，先检查 `sessionStorage` 是否已有 `v4_admin_key`
- 无密钥：显示密钥输入页（密码框 + 验证按钮）
- 输入密钥后立即调用 `GET /api/admin/invite/list` 验证
- 验证失败 → 显示"管理员密钥无效"，清除 sessionStorage
- 验证通过 → 自动加载列表
- **ADMIN_KEY 仅存 sessionStorage，不进 localStorage，页面刷新后需重新输入**

### 2.2 生成邀请码

| 字段 | 对应后端参数 | 说明 |
|------|------------|------|
| 数量 | `count` (1-100) | 一次可生成多个 |
| 最大使用次数 | `max_uses` (1-100000) | 该码可被使用的次数 |
| 备注 | `note` | 可选，如"给XX客户" |

- 生成成功后，在页面顶部绿色区域显示新码 + 一键复制按钮
- 同时自动刷新列表

### 2.3 邀请码列表

| 列 | 说明 |
|----|------|
| 邀请码 | 等宽字体 + 复制按钮 |
| 备注 | note 字段 |
| 绑定手机号 | 已使用时显示 |
| 已用/上限 | used_count / max_uses |
| 状态 | 绿色"有效" / 红色"已作废" |
| 创建时间 | created_at |
| 操作 | 有效码显示"作废"按钮 |

### 2.4 作废邀请码

- 每条有效码旁有红色"作废"按钮
- 点击前弹出 `confirm()` 二次确认
- 确认后调用 `POST /api/admin/invite/revoke`
- 作废后该码立即变为"已作废"状态（灰色 + 删除线）
- 已作废的码不再显示"作废"按钮

### 2.5 复制邀请码

- 新生成的码：右侧"复制"按钮
- 列表中的码：等宽字体旁的📋按钮
- 使用 `navigator.clipboard.writeText()` API

---

## 3. 权限处理

| 项目 | 实现 |
|------|------|
| ADMIN_KEY 不写死代码 | ✅ 运行时手动输入 |
| 存储位置 | `sessionStorage`（非 localStorage） |
| 页面刷新后 | 需重新输入密钥 |
| 密钥无效时 | 自动清除 + 显示错误提示 |
| 普通用户 | 工作台有"管理员"按钮，但无密钥则卡在密钥输入页 |
| JWT 验证 | `/admin` 路由有 `RequireAuth` 保护（需登录） |
| 管理员验证 | 所有 admin API 请求带 `X-Admin-Key` header |

---

## 4. API 对接

| 前端函数 | 后端端点 | 方法 | Header |
|----------|----------|------|--------|
| `adminInviteGenerate()` | `POST /api/admin/invite/generate` | POST | X-Admin-Key + Bearer JWT |
| `adminInviteList()` | `GET /api/admin/invite/list` | GET | X-Admin-Key + Bearer JWT |
| `adminInviteRevoke()` | `POST /api/admin/invite/revoke` | POST | X-Admin-Key + Bearer JWT |

**staging 接口连通性**：`GET /api/admin/invite/list` 错误密钥 → HTTP 401 ✅

---

## 5. 安全约束

| 约束 | 状态 |
|------|------|
| ADMIN_KEY 不写进代码 | ✅ |
| JWT_SECRET 不写进代码 | ✅ |
| 不改后端 | ✅ |
| 不碰生产环境 | ✅ |
| 不自动生成真实视频 | ✅ |
| sessionStorage 仅存密钥 | ✅ |

---

## 6. 本地 build

```
vite v5.4.21 building for development...
✓ 37 modules transformed.
✓ built in 842ms
```

**0 TypeScript 错误，0 警告。**

---

## 7. 页面入口

工作台 → 右上角"管理员"按钮 → `/admin` 路由 → 密钥输入 → 邀约码管理

退出管理员 → 清除 sessionStorage → 返回工作台
