# V0.1.3 后端代码审查包 · README

> 本包供扣子 / Codex / ChatGPT 工具链做代码审查。**当前不允许部署、不允许 push。**

## 基本信息
- 仓库：`-FASTAPI-BACKEND-`（仅后端）
- 基础 commit：`68263a1`（V0.1.2 P2 复审检查点，V0.1.3 分支由此切出）
- 分支名：`store-manager-v0.1.3-backend`（无 upstream → 未 push）

### HEAD 语义（修正 P0-3 一致性）
| 角色 | commit | 说明 |
|------|--------|------|
| 第一阶段代码交付 HEAD | `86d64d3` | 7 模块开发完成时 |
| 首版审查包提交 | `2b8eebb` | 首次生成审查材料 |
| **初审修订后代码 HEAD（本次审查对象）** | **`f1f29a4`** | 修复 ChatGPT 初审 3P0+3P1 |
| 审查材料同步提交 | 紧随 `f1f29a4` 之后的 1 个 **docs-only** 提交 | 仅同步本审查包，**不含代码改动** |

> 即：本审查材料对应**代码 HEAD = `f1f29a4`**；其后仅有一个 docs 提交同步本包，无代码变更。
> `git log` 末尾的 docs 提交即此包本身，非新代码。

## 包内文件
| 文件 | 说明 |
|------|------|
| `STORE_MANAGER_V0_1_3_BACKEND_CODE_REVIEW_PACKAGE.md` | 审查总包（18 节：表/端点/指标/规则/限流/闸门/smoke/红线等） |
| `STORE_MANAGER_V0_1_3_BACKEND_REVIEW_README.md` | 本说明 |
| `STORE_MANAGER_V0_1_3_BACKEND_DIFF_68263a1_TO_HEAD.patch` | 全量改动 patch（`git diff 68263a1..HEAD`，新增文件=全量源码） |
| `STORE_MANAGER_V0_1_3_BACKEND_DIFF_STAT.txt` | `git diff --stat 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_GIT_LOG.txt` | `git log --oneline 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_CHANGED_FILES.txt` | `git diff --name-status 68263a1..HEAD` |
| `STORE_MANAGER_V0_1_3_BACKEND_SMOKE_OUTPUT.txt` | isolated router smoke（27 PASS / 0 FAIL） |
| `STORE_MANAGER_V0_1_3_BACKEND_APP_LEVEL_SMOKE_OUTPUT.txt` | **完整 main.py app 级 smoke**（9 PASS / 0 FAIL，验证路由冲突已解决） |

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
# 1) isolated router smoke（不依赖 weasyprint）
STORE_MANAGER_V013_DB_PATH=/tmp/v013.db STORE_MANAGER_ADMIN_KEY=any_key python smoke_test_v013.py
# 期望：27 PASS / 0 FAIL

# 2) 完整 main.py app 级 smoke（验证路由冲突已解决；无 weasyprint 时脚本自动 stub）
STORE_MANAGER_V013_DB_PATH=/tmp/v013a.db python smoke_app_level_v013.py
# 期望：9 PASS / 0 FAIL
```
> V0.1.3 独立测试库环境变量为 `STORE_MANAGER_V013_DB_PATH`，默认 `/opt/meiye-wuyou-test/data/store_manager_workbench_v013.db`；
> 指向生产库目录 `/opt/meiye-wuyou/data` 会 fail-fast 拒绝。整库部署冒烟仍留待部署前环境。

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
