# P2B-A V1.1 安全确认清单

## 禁止项（全部未触碰）
- ❌ 无 execute 按钮
- ❌ 无真实视频执行
- ❌ 无 remixer / 火山引擎调用
- ❌ 无 Seedance / 付费素材
- ❌ 无 batch-generate
- ❌ 无 videos 表写入
- ❌ 无 production 部署
- ❌ 无 P2B-B/C 代码
- ❌ 无 A台/B台/P2A 修改
- ❌ 无硬编码 JWT / ADMIN_KEY
- ❌ 无 AGPL / OpenMontage 依赖

## Network 白名单
P2B-A 页面运行时只允许请求以下 API：
1. `GET /api/production-orders/{id}`
2. `GET /api/p2b/skills`
3. `POST /api/p2b/theme-kernels`
4. `POST /api/p2b/execution-plans/preview`
5. `POST /api/p2b/execution-plans`
6. `GET /api/p2b/execution-plans/{id}/explain`
7. `GET /api/p2b/execution-plans/by-production-order/{production_order_id}`

**注意**: 验证 Network 白名单时应以浏览器实际 Network 请求为准，
不要用 JS bundle grep（因为 client.ts 包含旧功能代码字符串）。

## 状态
- V1.1 未部署 staging
- 等待 ChatGPT 复审
