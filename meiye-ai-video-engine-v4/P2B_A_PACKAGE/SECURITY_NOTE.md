# 安全确认清单 — P2B-A

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | 无硬编码密钥/token | ✅ |
| 2 | JWT Bearer 鉴权 | ✅ |
| 3 | Preview Only — 不执行视频 | ✅ |
| 4 | 无 execute/remixer/火山/batch-generate 按钮 | ✅ |
| 5 | 无 upload/付费素材请求 | ✅ |
| 6 | Network 白名单仅 8 个 P2B-A API | ✅ |
| 7 | A 台/B 台/P2A/Admin/登录不退化 | ✅ |
| 8 | partial_done 逻辑不退化 | ✅ |
| 9 | RequireAuth 包裹 | ✅ |
| 10 | 无 XSS（所有输入均为受控状态） | ✅ |

## 禁止调用清单

- POST /api/remixer/*
- POST /api/batch-generate
- 火山引擎域名
- POST /api/videos/upload
- 任何付费资源接口
- Seedance / ffmpeg 调用
