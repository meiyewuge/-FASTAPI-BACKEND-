# FRONTEND_JOINT_DEBUG_PATCH_REPORT.md
> Qoder V4 前端联调交付报告 | commit `c6d664d` | 分支 `qoder/v4-frontend-workbench`

---

## 1. 登录页改造 ✅ PASS

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 手机号输入框 | ✅ | `type="tel"` + 占位提示 |
| 邀约码输入框 | ✅ | 必填，Enter 键提交 |
| POST /api/auth/login | ✅ | `{ phone, invite_code }` |
| JWT 存储 | ✅ | `localStorage` 保存 JWT token |
| 后续请求带 Bearer | ✅ | 所有 API 自动 `Authorization: Bearer <JWT>` |
| 401 跳登录 | ✅ | `register401()` 全局注册，401 自动清 token + navigate |
| 4010 提示 | ✅ | "该邀请码已绑定其他手机号" |
| 其他失败 | ✅ | 显示后端 `message` 字段 |
| 同手机号重复登录 | ✅ | 前端不做拦截（Patch4.1 逻辑） |

---

## 2. 全局 API 请求封装 ✅ PASS

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 统一 authHeaders() | ✅ | 自动带 `Authorization: Bearer JWT` |
| 401 自动跳登录 | ✅ | `check401()` 在每个响应后检测 |
| 网络断开处理 | ✅ | `navigator.onLine` + catch → 离线红色横幅 |
| 后端 message 显示 | ✅ | Resp 接口 `message` 字段（与后端对齐） |
| 离线横幅 | ✅ | 固定顶部红色 bar |
| 覆盖端点 | ✅ | /generate, /videos, /videos/{id}/url, /compose, /upload, /export, /export/videos, /subscription/status, /b/strategies |

---

## 3. 上传素材 ✅ PASS

### 3A 图片上传
| 检查项 | 状态 | 说明 |
|--------|------|------|
| POST /api/upload type=image | ✅ | FormData 上传 |
| jpg/png/webp ≤10MB | ✅ | 前端 accept 限制 |
| 文件选择 | ✅ | 点击上传区域选择 |
| 预览 | ✅ | 上传成功显示 file_url 链接 |
| 上传进度 | ✅ | XHR onprogress 实时百分比 |
| file_url | ✅ | 成功后显示并可访问 |

### 3B 文字/脚本上传
| 检查项 | 状态 | 说明 |
|--------|------|------|
| 文本框输入 | ✅ | textarea 4行 |
| 上传 txt | ✅ | POST /api/upload type=text, content 字段 |
| file_id 显示 | ✅ | 成功后显示文件名 |

### 3C 视频上传
| 检查项 | 状态 | 说明 |
|--------|------|------|
| 文件选择/拖拽 | ✅ | onDrop + input file |
| mp4/mov/avi ≤500MB | ✅ | accept 限制 |
| 上传进度条 | ✅ | XHR onprogress |
| 作为 B 台素材 | ✅ | 上传成功后刷新视频列表 |

---

## 4. B 台入口恢复 ✅ PASS

| 检查项 | 状态 | 说明 |
|--------|------|------|
| B 台按钮可点击 | ✅ | 不再 disabled |
| 文案"B台·裂变" | ✅ | 🔁 B台·裂变 |
| 裂变视频 Tab 可点击 | ✅ | 恢复 mother/viral 双 Tab |
| 策略栏显示 | ✅ | 选中母视频后显示裂变策略按钮组 |
| B 台费用 = 0 元/条 | ✅ | 预估栏显示"B台裂变 = 0元/条（本地ffmpeg）" |
| 不触发火山成本提示 | ✅ | B 台生成 toast 显示"0元/条" |
| 需源视频 | ✅ | 无选中时按钮 disabled + 提示 |
| 完成后显示 viral | ✅ | 生成结果网格内显示，可播放/下载 |

---

## 5. 下载稳定性 ✅ PASS

| 检查项 | 状态 | 说明 |
|--------|------|------|
| AbortController | ✅ | `stableDownload()` 内置 |
| 30 秒超时 | ✅ | `setTimeout(() => controller.abort(), 30000)` |
| 失败重试 1 次 | ✅ | maxRetries=2（首次+1次重试） |
| 大文件进度 | ✅ | ReadableStream reader + contentLength 百分比 |
| CDN URL 过期刷新 | ✅ | 403/404 → `refreshVideoUrl()` → 新 URL 重试 |
| 单条下载 | ✅ | 每条独立状态按钮 |
| 批量下载 | ✅ | 300ms 间隔逐个，汇总 N/M 成功 |
| 下载状态显示 | ✅ | 等待/下载中/已完成/失败(重试) |

---

## 6. 导出功能 ✅ PASS

| 检查项 | 状态 | 说明 |
|--------|------|------|
| CSV 导出保留 | ✅ | POST /export format=csv → Blob 下载 |
| 视频导出(mp4) | ✅ | POST /export/videos → 返回 URL 列表 |
| 视频列表勾选 | ✅ | checkbox + 全选/取消全选 |
| "导出视频"按钮 | ✅ | 显示已选数量 |
| 逐条下载 | ✅ | 复用 stableDownload，300ms 间隔 |
| 不做 ZIP | ✅ | 仅 mp4 逐个下载 |

---

## 7. API 端点对齐

| 端点 | 来源 | 状态 |
|------|------|------|
| `POST /auth/login` | Login.tsx | ✅ |
| `POST /generate` | Workbench → handleGenerate | ✅ |
| `POST /a/generate` | Workbench → handleAGenerate | ✅ |
| `POST /b/generate` | Workbench → handleBGenerate | ✅ |
| `POST /compose` | client.ts → compose | ✅ |
| `GET /b/strategies` | loadDashboard | ✅ |
| `GET /tasks/{id}` | pollTask | ✅ |
| `GET /tasks` | loadDashboard | ✅ |
| `POST /tasks/{id}/retry` | handleRetry | ✅ |
| `GET /videos` | switchVideoTab / loadVideoPage | ✅ |
| `GET /videos/{id}/url` | stableDownload → CDN刷新 | ✅ |
| `POST /upload` | uploadFile (XHR) | ✅ |
| `POST /export` | exportVideosCSV / exportVideosJSON | ✅ |
| `POST /export/videos` | exportVideosMp4 | ✅ |
| `GET /cost/summary` | loadDashboard | ✅ |
| `GET /metrics/overview` | loadDashboard | ✅ |
| `GET /subscription/status` | client.ts → subscriptionStatus | ✅ |

**无 mock 依赖，全部对接真实后端。**

---

## 禁止事项检查

- ❌ 修改后端代码：**未触碰**
- ❌ 改 cost_engine：**未触碰**
- ❌ 改 Nginx：**未触碰**
- ❌ 碰生产环境：**未触碰**
- ❌ 写死密钥/Token：**未发生**

---

## 交付物

| 项目 | 状态 |
|------|------|
| 本地 build 通过 | ✅ `vite build` 成功，0 errors |
| Git 推送 | ✅ `c6d664d` → `qoder/v4-frontend-workbench` |
| 后端对齐版本 | `claude/v4-staging` commit `8541dce` |

**结论：V4 前端联调完成，可交 ChatGPT 审核前端报告。**

下一步流程：ChatGPT 审核 → Coze 部署 staging → 手动验收 → stable v1.0.0
