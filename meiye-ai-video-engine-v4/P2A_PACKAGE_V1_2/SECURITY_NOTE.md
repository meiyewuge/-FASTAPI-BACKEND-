# 安全确认清单

## P2A V1.2 安全确认

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | 无硬编码密钥/token/API Key | ✅ |
| 2 | JWT Bearer 鉴权（Patch6 模式） | ✅ |
| 3 | Preview Only — 无写入/执行/生成操作 | ✅ |
| 4 | 无 execute/remixer/火山/batch-generate 关键词 | ✅ |
| 5 | 无 upload/paid asset 请求 | ✅ |
| 6 | Network 白名单仅 5 个 P2A API | ✅ |
| 7 | 不影响 A 台/B 台原有功能 | ✅ |
| 8 | partial_done 逻辑不退化 | ✅ |
| 9 | 无 XSS 风险（scenario/platform 均为 select 下拉） | ✅ |
| 10 | RequireAuth 包裹（未登录不可访问） | ✅ |

## 禁止调用清单

以下接口/域名在 P2A 页面中**绝不可调用**：

- POST /api/remixer/*
- POST /api/batch-generate
- 任何火山引擎域名 (volcengineapi.com, bytevcloud.com 等)
- POST /api/videos/upload
- 任何付费资源接口
