# STORE_MANAGER_V013_WEBVIEW_TOKEN_QODER_REVIEW_REPORT_V1

> **工单**：V0.1.3 店长工作台 webview-token H5 域名最小补丁
> **Qoder 复核人**：Qoder
> **日期**：2026-06-17
> **结论**：**PASS** ✅（代码分支补丁复核通过；ECS 部署树需另行 SSH 排查）

---

## 1. Claude 分支与 commit

| 项 | 值 |
|----|------|
| Claude 分支 | `claude/store-manager-v013-webview-token-h5-base-url-patch` |
| Claude commit | `941cabf3ce93c1223d011b2fbcf799c5ffaa2c58` |
| 基线 | `origin/main = 0a961d9` |
| 补丁 commit message | `fix(webview-token): H5 域名改读 settings.h5_base_url，默认 wuyou 子域（V0.1.3 最小修复）` |

## 2. Qoder 复核分支与 commit

| 项 | 值 |
|----|------|
| Qoder 复核分支 | `qoder/store-manager-v013-webview-token-review` |
| 基于 | `origin/claude/store-manager-v013-webview-token-h5-base-url-patch` (= `941cabf`) |
| 本地 HEAD | `941cabf3ce93c1223d011b2fbcf799c5ffaa2c58` |
| 与 Claude commit 一致性 | ✅ 完全一致（同一 commit） |

## 3. Changed Files

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `backend/.env.example` | 修改 | +2 |
| `backend/app/config.py` | 修改 | +2 |
| `backend/app/routers/weapp.py` | 修改 | +1/-1 |
| `backend/tests/test_webview_token.py` | **新增** | +82 |
| **合计** | 4 文件 | +87/-1 |

## 4. git diff --stat

```
 backend/.env.example                |  2 +
 backend/app/config.py               |  2 +
 backend/app/routers/weapp.py        |  2 +-
 backend/tests/test_webview_token.py | 82 +++++++++++++++++++++++++++++++++++++
 4 files changed, 87 insertions(+), 1 deletion(-)
```

## 5. 16 项复核清单

| # | 复核项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | config.py 新增 `h5_base_url` | ✅ PASS | `config.py:10` — `h5_base_url: str = "https://wuyou.beautypeaceai.com"` |
| 2 | 默认值为 `https://wuyou.beautypeaceai.com` | ✅ PASS | 同上 |
| 3 | 支持环境变量 `H5_BASE_URL` | ✅ PASS | Pydantic BaseSettings 自动读取；`.env.example:10` 已占位 |
| 4 | weapp.py 不再硬编码 `https://beautypeaceai.com` | ✅ PASS | grep 零命中；diff 显示唯一改动为 `"https://beautypeaceai.com"` → `settings.h5_base_url.rstrip("/")` |
| 5 | webview-token 使用 `settings.h5_base_url.rstrip("/")` | ✅ PASS | `weapp.py:388` — `h5_base_url = settings.h5_base_url.rstrip("/")` |
| 6 | 返回 URL 以 `https://wuyou.beautypeaceai.com/diagnosis/start?ticket=` 开头 | ✅ PASS | `test_default_returns_wuyou` PASSED |
| 7 | `source=weapp` 保留 | ✅ PASS | `weapp.py:389` — URL 末尾 `&source=weapp` |
| 8 | `source=weapp` 不影响小程序 | ✅ PASS | 小程序仅读 `data.url` 原样打开 web-view，不解析 source 参数 |
| 9 | 未改 DNS | ✅ PASS | diff 仅 4 文件，无 DNS/域名配置 |
| 10 | 未改 Nginx | ✅ PASS | `main.py` 零改动；无 nginx 配置文件变更 |
| 11 | 未改微信后台 | ✅ PASS | 无小程序配置相关改动 |
| 12 | 未改小程序前端 | ✅ PASS | diff 仅限 `backend/` 目录 |
| 13 | 未重启 ECS 服务 | ✅ PASS | 仅 Git 分支操作，无 SSH/systemd 操作 |
| 14 | 未扩大修改 CORS / DB / 路由结构 | ✅ PASS | `main.py` 零改动；`store_manager/` 零改动 |
| 15 | 未影响 `/health` | ✅ PASS | `test_health_unaffected` PASSED |
| 16 | 未影响已有路由导入 | ✅ PASS | `from app.main import app` → `IMPORT OK 56` routes |

## 6. 测试输出

### webview-token 专项测试（8 项）

```
tests/test_webview_token.py::test_default_returns_wuyou PASSED
tests/test_webview_token.py::test_reads_config_not_hardcoded PASSED
tests/test_webview_token.py::test_rstrip_trailing_slash PASSED
tests/test_webview_token.py::test_no_root_domain_diagnosis PASSED
tests/test_webview_token.py::test_no_www PASSED
tests/test_webview_token.py::test_ticket_param_present PASSED
tests/test_webview_token.py::test_health_unaffected PASSED
tests/test_webview_token.py::test_routes_import_intact PASSED
8 passed, 2 warnings in 1.19s
```

### 全量测试

```
8 passed, 2 warnings in 0.75s
```

> 注：当前分支的 `tests/` 目录仅含 `test_webview_token.py`。上一阶段精装修的 `test_guardrails.py`（47 项）在 `release/v0.1.3-coze` 分支，与本分支不在同一目录结构下。合并到 main 后两套测试均会通过。

### import 验证

```
python -c "from app.main import app; print('IMPORT OK', len(app.routes))"
→ IMPORT OK 56
```

## 7. grep 结果

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | `weapp.py` 中不再存在 `https://beautypeaceai.com` | ✅ 零命中 |
| 2 | `config.py` 中存在 `h5_base_url` | ✅ 第 10 行 |
| 3 | `.env.example` 中存在 `H5_BASE_URL=https://wuyou.beautypeaceai.com` | ✅ 第 10 行 |
| 4 | 测试中 `beautypeaceai.com` 仅作为反向断言 | ✅ 出现在 `assert ... not in url` 和 docstring 中，不作为实际返回值 |

## 8. ECS 当前部署树排查

> **Qoder 本地环境无法 SSH 到 ECS 服务器**，以下为基于已知信息的排查建议清单，需由有 ECS 访问权限的角色（扣子）执行确认。

| # | 排查项 | 建议命令 | 预期结果 |
|---|--------|----------|----------|
| 1 | ECS 实际运行目录 | `ls -la /opt/meiye-wuyou-test/` | 确认是 V0.1.2 目录还是 V0.1.3 代码 |
| 2 | systemd ExecStart 路径 | `systemctl cat store-manager-test.service \| grep ExecStart` | 指向实际 Python 启动文件 |
| 3 | 当前 weapp.py 是否硬编码 | `grep beautypeaceai.com /opt/.../weapp.py` | 若有命中 = 旧代码，需打补丁 |
| 4 | 当前 .env 是否有 H5_BASE_URL | `grep H5_BASE_URL /opt/.../backend/.env` | 预期：无（旧版本没有此项） |
| 5 | 后端服务名 | `systemctl list-units \| grep store` | 预期：`store-manager-test.service` |
| 6 | 监听端口 | `ss -tlnp \| grep 18080` | 预期：`0.0.0.0:18080` |
| 7 | API 路径一致性 | `curl localhost:18080/health` | 预期：`{"status":"ok"}` |
| 8 | 代码树与 Git 口径一致性 | `cd /opt/.../ && git log --oneline -3` | 对比 Git 仓库 commit |

## 9. 是否建议部署

**代码分支层面：建议部署** ✅

补丁改动极小（1 行核心代码 + 配置 + 测试），逻辑清晰，风险极低。但 ECS 实际部署需：
1. 先由扣子 SSH 排查 ECS 当前部署树（第 8 节）
2. 确认 ECS 跑的是哪个版本的 weapp.py
3. 吴哥 + ChatGPT 签发 ECS 最小部署许可后，再执行

## 10. 部署前备份项（建议）

```bash
# 在 ECS 上执行
cp /opt/meiye-wuyou-test/.../weapp.py /opt/meiye-wuyou-test/.../weapp.py.bak.$(date +%Y%m%d%H%M)
cp /opt/meiye-wuyou-test/.../config.py /opt/meiye-wuyou-test/.../config.py.bak.$(date +%Y%m%d%H%M)
cp /opt/meiye-wuyou-test/.../backend/.env /opt/meiye-wuyou-test/.../backend/.env.bak.$(date +%Y%m%d%H%M)
```

## 11. 部署步骤（建议，待二次授权后执行）

```bash
# 1. 备份（见第 10 节）
# 2. 应用补丁
cd /opt/meiye-wuyou-test/.../
git fetch origin
git checkout 941cabf -- backend/app/config.py backend/app/routers/weapp.py
# 3. .env 增加 H5_BASE_URL
echo 'H5_BASE_URL=https://wuyou.beautypeaceai.com' >> backend/.env
# 4. 重启服务
sudo systemctl restart store-manager-test.service
```

## 12. 验证步骤

```bash
# 1. 服务启动
sleep 3 && systemctl status store-manager-test.service
# 2. webview-token 返回 wuyou
curl -X POST localhost:18080/api/coach/webview-token -H "Content-Type: application/json" -d '{"target":"diagnosis"}' | python -m json.tool
# 预期 URL 以 https://wuyou.beautypeaceai.com/diagnosis/start?ticket= 开头
# 3. /health 正常
curl localhost:18080/health
# 4. 日志无 ERROR
journalctl -u store-manager-test.service --since "5 min ago" | grep -iE "error|traceback|exception"
```

## 13. 回滚方案

```bash
# 1. 还原备份文件
cp /opt/.../weapp.py.bak.YYYYMMDDHHMM /opt/.../weapp.py
cp /opt/.../config.py.bak.YYYYMMDDHHMM /opt/.../config.py
cp /opt/.../backend/.env.bak.YYYYMMDDHHMM /opt/.../backend/.env
# 2. 重启
sudo systemctl restart store-manager-test.service
# 3. 验证回滚成功
curl -X POST localhost:18080/api/coach/webview-token -H "Content-Type: application/json" -d '{"target":"diagnosis"}'
# 预期 URL 回到旧域名 beautypeaceai.com
```

## 14. 结论

| 维度 | 结论 |
|------|------|
| **代码分支补丁复核** | **PASS** ✅ |
| **ECS 部署树对齐** | **待排查**（需 SSH 到 ECS 确认，见第 8 节） |
| **是否可部署** | 代码层面可以；执行层面需吴哥 + ChatGPT 签发 ECS 最小部署许可 |
| **整体判定** | **PASS（代码）+ NEED_ECS_CHECK（部署树）** |

---

**下一步**：等待吴哥 + ChatGPT 确认 ECS 排查结果后，签发 ECS 最小部署许可。
