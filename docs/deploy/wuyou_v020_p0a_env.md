# V0.2.0 P0A 加固 — 环境变量准备

> P0A 新增 1 个配置项，P0B 上线前需设置真实值。

## .env 新增项

```bash
# ── P0A 新增 ──────────────────────────────
# 报告签名密钥（P0B 上线前必须设置真实值）
# 生成方式: openssl rand -hex 32
# 当前为空值，不影响服务运行
REPORT_SIGN_SECRET=
```

## P0B 上线前的真实密钥设置

```bash
# 生成密钥
openssl rand -hex 32
# 输出示例: a1b2c3d4e5f6...

# 写入 .env
REPORT_SIGN_SECRET=<上一步输出>
```

## config.py 校验状态

| 项目 | P0A 现状 | P0B 目标 |
|------|----------|----------|
| `report_sign_secret` 字段 | ✅ 已添加，默认空 | 启动校验 field_validator |
| 占位值检测 | ❌ 未启用 | `change-me-in-production` 等禁止值校验 |
| 最小长度 | ❌ 未启用 | ≥ 32 字符 |

> TODO(P0B): 在 config.py 中添加 field_validator 启动校验。

## 禁止写入 Git 的文件

- `.env`（含真实密钥）
- `backend/.env`
- `backend/.env.*`（除 `.env.example`）
- 任何包含真实 REPORT_SIGN_SECRET 值的文件

## 验证

```bash
# 确认代码中无真实密钥
grep -rn "REPORT_SIGN_SECRET" backend/app/
# 应只看到字段定义和注释

# 确认 .env 不在 Git 中
git ls-files | grep -i "\.env"
# 应为空
```
