# V0.1.3 后端代码审查包 · README

> 本包供扣子 / Codex / ChatGPT 工具链做代码审查。**当前不允许部署、不允许 push。**

## 基本信息
- 仓库：`-FASTAPI-BACKEND-`（仅后端）
- 基础 commit：`68263a1`（V0.1.2 P2 复审检查点，V0.1.3 分支由此切出）
- 当前 HEAD：`86d64d3`
- 分支名：`store-manager-v0.1.3-backend`（无 upstream → 未 push）

## 包内文件
| 文件 | 说明 |
|------|------|
| `STORE_MANAGER_V0_1_3_BACKEND_CODE_REVIEW_PACKAGE.md` | 审查总包（18 节：表/端点/指标/规则/限流/闸门/smoke/红线等） |
| `STORE_MANAGER_V0_1_3_BACKEND_REVIEW_README.md` | 本说明 |
| `STORE_MANAGER_V0_1_3_BACKEND_DIFF_68263a1_TO_HEAD.patch` | 全量改动 patch（`git diff 68263a1..HEAD`，新增文件=全量源码） |
| `STORE_MANAGER_V0_1_3_BACKEND_DIFF_STAT.txt` | `git diff --stat 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_GIT_LOG.txt` | `git log --oneline 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_CHANGED_FILES.txt` | `git diff --name-status 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_SMOKE_OUTPUT.txt` | smoke 完整输出（含 24 PASS / 0 FAIL） |

## 如何查看 diff
```bash
# 在 -FASTAPI-BACKEND- 仓库内
git checkout store-manager-v0.1.3-backend
git diff 68263a1..HEAD
# 或直接看包内 patch：
less STORE_MANAGER_V0_1_3_BACKEND_DIFF_68263a1_TO_HEAD.patch
```
> 本轮所有后端代码均为**新增文件**（patch 中以 `new file` 呈现），现有文件仅 `backend/app/main.py` 改 2 行（注册 router）。

## 如何运行 smoke_test
```bash
cd backend
STORE_MANAGER_DB_PATH=/tmp/smoke.db STORE_MANAGER_ADMIN_KEY=any_key python smoke_test_v013.py
# 期望：24 PASS / 0 FAIL，exit 0，无 5xx / traceback
```
> 隔离挂载 v0.1.3 路由（不依赖 weasyprint）；整库启动冒烟留待部署前环境执行。

## 红线声明（本阶段）
- 未 push（分支无 upstream，远程不存在）
- 未 merge
- 未部署 ECS、未 scp、未开放 18081
- 未动 18080 测试服务、未改 Nginx
- 未动 V0.1.1 主链路、未动生产数据库、未执行迁移
- 未动 MWUZS-MINIAPP 小程序仓库（该仓库工作区干净，本轮零提交）

## 安全
本包不含：`.env` / 密钥 / 数据库真实数据 / `node_modules` / `venv` / `__pycache__` / 生产配置。

## 下一步（顺序定死，当前禁止部署）
```
生成 review zip → 扣子收包 → Codex/ChatGPT 审查 → 审查通过
→ 补 4 个阈值配置化小提交 → 再部署 ECS 18081
```
> 4 个待确认阈值（客流/新客承接/锁客/项目结构）见审查总包第 16.1 节，**审查通过后再统一补小提交，本阶段不改代码**。
