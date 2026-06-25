# FRONTEND_V4_PAGE_REDESIGN_P0_REPORT

> Qoder 前端 V4 单框工作流 P0 重构交付报告
> 分支: `qoder/v4-frontend-workbench`
> 后端基线: `claude/v4-staging` @ `d64675f`（P0 主干 + 回流层 + 收口）

---

## 1. 页面总结构

**三区块单框工作流**，Manus 风格，深蓝主色 `#2563EB`，浅底色 `#f8fafc`，圆角 12px。

- 区块一：顶部操作对话框（prompt + 上传 + 操作按钮）
- 区块二：母视频 / 源视频陈列面
- 区块三：裂变视频陈列面

## 2. 操作对话框（区块一）

- 标题："我能为你做什么？"
- 大输入框 placeholder："请输入视频需求，或上传素材开始创作…"
- 统一上传入口（不分 Tab）：图片/文件/视频/文本，各最多 10 个
- 素材汇总条：`图片 x3 / 文件 x1 / 视频 x5 / 文本已输入 / 清除全部`
- 上传缩略图预览 + 单文件删除 + 失败原因标注

## 3. 上传接口

- `POST /api/uploads/batch` (FormData, type=image|video|file)
- XHR 上传带进度条
- 失败文件不阻断其他文件

## 4. 操作按钮

| 按钮 | 行为 | 约束 |
|------|------|------|
| A台·母视频 | 二次确认 → 提示"请联系管理员操作" | P0 不自动触发 A 台 |
| B台·裂变 | 勾选 1~10 源视频 → 展开配置面板 | 0 元/条，无源时 disabled |
| 上传素材 | 调用 batchUpload | 有未上传文件时显示 |

## 5. 母视频陈列面（区块二）

- 接口: `listVideos("mother", page, 50)`
- 卡片: 封面 / video_id / 来源标签(A台/上传) / 时长 / 大小 / 创建时间 / 播放 / 下载 / 删除 / 复选框
- 工具栏: 全选 / 下载选中 / 发送到 B 台裂变

## 6. B 台批量裂变

- `POST /api/b/batch-generate` → 提交裂变
- `GET /api/b/batch/{batch_id}` → 轮询状态
- 配置面板: 源数 × 每源裂变数(1~10) × 策略 × prompt 叠加
- 预计产出上限 50 条
- 完成后自动刷新裂变陈列面

## 7. 裂变视频陈列面（区块三）

- 接口: `listVideos("viral", page, 50)`
- 卡片: 封面 / video_id / 源视频 ID / 时长 / 大小 / 剩余天数 / 播放 / 下载 / 删除 / 复选框
- 反馈菜单: 收藏 / 好用 / 不好用 / 备注
- 提示: "裂变视频服务器临时保留 5 天，请及时下载到本地。"
- 已过期 / 剩余天数标签

## 8. 下载到本地

- `stableDownload`：AbortController(30s) + ReadableStream 进度 + CDN URL 刷新 + 重试
- 下载按钮 title: "浏览器将保存到你的电脑下载目录"
- 批量下载支持（选中 → 逐个下载，间隔 300ms）

## 9. 删除视频

- `DELETE /api/videos/{id}` + 二次确认
- 403/2001 → "无权删除该视频"
- 删除后从列表移除 + 刷新

## 10. storage/status

- `GET /api/storage/status`
- 普通用户: scope=tenant，显示 mother/viral/upload count + MB
- super_admin: scope=global，额外显示 disk_used_percent

## 11. 事件埋点

| 事件 | 接口 | 触发时机 |
|------|------|----------|
| video_play | POST /events/track | 播放按钮 |
| video_select | POST /events/track | 勾选视频 |
| send_to_b | POST /events/track | 发送 B 台 |
| video_download | POST /events/track | 下载按钮 |
| video_delete | POST /events/track | 删除操作 |

**失败不阻断**：`catch → console.warn`，不影响主流程。

## 12. 视频反馈

- `POST /api/videos/{id}/feedback` (favorite/useful/useless/note)
- 裂变视频卡片"更多"下拉菜单触发

## 13. 管理员候选池

- AdminPanel 新增第三 Tab "回流候选池"（super_admin only）
- `GET /api/admin/knowledge-candidates` → 列表
- `POST /api/admin/knowledge-candidates/{id}/approve` → 通过
- `POST /api/admin/knowledge-candidates/{id}/reject` → 拒绝
- invite_admin / user 不可见

## 14. Patch6 权限保持

| 项目 | 状态 |
|------|------|
| `/api/me` 登录后获取角色 | ✅ 不变 |
| `isAdmin()` / `isSuperAdmin()` | ✅ 不变 |
| `ENABLE_ADMIN_KEY_FALLBACK` | ✅ `false` |
| 管理员接口鉴权 | ✅ 纯 Bearer JWT |
| ADMIN_KEY | ✅ 不恢复 |

## 15. 文件变更清单

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `frontend/api/client.ts` | 追加新类型+函数 | +188 行（520→715） |
| `frontend/styles.css` | 主题色重写+workflow 样式 | 大幅变更 |
| `frontend/pages/Workbench.tsx` | 完全重写 | 559→695 行 |
| `frontend/pages/AdminPanel.tsx` | 增加候选池 Tab | +46 行（283→329） |
| `frontend/main.tsx` | 不变 | — |
| `frontend/pages/Login.tsx` | 不变 | — |

## 16. 构建验证

```
vite v5.4.21 building for production...
✓ 37 modules transformed.
dist/index.html                   0.41 kB │ gzip:  0.31 kB
dist/assets/index-B2ontQjU.css   16.93 kB │ gzip:  3.78 kB
dist/assets/index-BiR6YtoE.js   238.54 kB │ gzip: 77.28 kB
✓ built in 1.22s
```

## 17. 约束遵守

| 约束 | 状态 |
|------|------|
| 不改 backend/ | ✅ |
| 不碰 production | ✅ |
| 不触发 A 台真实生成 | ✅ 仅提示"请联系管理员" |
| 不写死邀请码或密钥 | ✅ |
| 不恢复 ADMIN_KEY 模式 | ✅ ENABLE_ADMIN_KEY_FALLBACK=false |
| 不大文件压测/批量压测 | ✅ |

## 18. 未实现/后续联调

- `POST /api/a/generate`（A 台生成）：P0 阶段仅展示入口，不自动触发
- 候选池后端端点：Claude staging 已有，本地联调时验证
- `POST /api/events/track` 后端实现：联调时验证
- 视频反馈后端处理：联调时验证

## 19. 技术栈

- React 18 + TypeScript 5 + Vite 5
- react-router-dom 6 (HashRouter)
- 无第三方 UI 库，纯 CSS + 自定义组件

## 20. 下一步

1. 本地联调：`claude/v4-staging` 后端 + 本分支前端
2. 验证所有新端点响应格式
3. 事件埋点数据落地检查
4. 候选池回流审核流程端到端测试
