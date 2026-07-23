# DSM W1｜ChatGPT 最终冻结与 W2 执行裁定 V1

裁定日期：2026-07-23  
裁定角色：ChatGPT（独立终验与总审）  
适用项目：数字店长 35 页生产工程

## 1. 最终裁定

```text
W1-A1-R2 FINAL PASS
W1 FINAL FROZEN
W1 CLOSED
W2 AUTHORIZED
W3 AUTHORIZED = NO（必须等待 W2 exit gate）
R3 REQUIRED = NO
```

本裁定结束 W1 合同审查链。除非后续施工出现“冻结合同本身无法实现”的新证据，不再针对同一批合同发起 R3、重复统计复核或无边界返修。

重要边界：

- `W1 FINAL FROZEN` 表示生产合同、依赖和责任边界已经冻结；
- 不表示 72 个操作均已实现；
- 不表示真实 API、数据库迁移、运行态或部署已经通过；
- `EXISTING_CODE_ONLY_*` 仍须在对应批次完成合并、Facade、安全改造和 E2E；
- `PROPOSED_NOT_IMPLEMENTED` 仍须按 W3–W7 实施；
- 当前 `CURRENT_RUNTIME_EVIDENCE = NONE`，不得把合同冻结冒充为运行验收。

## 2. 最终冻结输入

以下 8 份 R2 文件构成 W1 唯一冻结合同包：

| 文件 | SHA-256 |
|---|---|
| `DSM_W1_GLOBAL_PRODUCTION_CONTRACT_R2.md` | `8dcf486ac5aeb0b26598ce0b9a098dc2fb90d9ed0342797538ebffc5d4fa1de1` |
| `DSM_W1_35_PAGE_DOM_API_COVERAGE_R2.csv` | `301062f9085d4d7585e6ce9e04dfa437b2ab18e6a63afa21e7f37b023232f192` |
| `DSM_W1_CANONICAL_OPERATION_CONTRACT_R2.csv` | `a798d212b191b5c2a87e590c86bbb84d450987beb82135e1312087d9a8307a05` |
| `DSM_W1_RESOURCE_AUTHORITY_AND_ID_R2.csv` | `b58d59438cd6ef8d9755208b8b6786c1e2a949cdc023a1d9a07df5ae310323c7` |
| `DSM_W1_LEGACY_ROUTE_DISPOSITION_R2.csv` | `8f7b52d66c45c43cf8b93dbd4ece46c3c0e709761039f9c60746468247f46db7` |
| `DSM_W1_BATCH_DEPENDENCY_AND_OWNER_MATRIX_R2.csv` | `a09315e9d1126387e17ba2a2cf4634018b2a816a4057203c16cace5e13bc38d3` |
| `DSM_W1_RESOLVED_DECISIONS_AND_RISK_REGISTER_R2.md` | `b60de8c6bc8a496501e3475c69d0c21a9fe5f21437c93dcdd4394997d790f6e4` |
| `DSM_W1_R2_SELF_CHECK_REPORT.md` | `4d908fdcd1f52771870883db90a9e3e53d55123f1cd00f776e779dec5bbbd1e1` |

产品基线：

```text
digital_store_manager_143_P34_FINAL_PASS.zip
SHA-256 = b48607946229d8421fc8ea0f1e550fdea5b85539bc445161aa5b7244dd31bb23
根目录 HTML = 35
```

## 3. ChatGPT 独立终验结果

### 3.1 文件与结构

```text
R2 文件 SHA                       8/8 PASS
R1 冻结输入 SHA                    8/8 未变
页面                               35/35
Coverage                           102 行 × 26 列
Canonical Operation               72 行 × 33 列
Resource                           26 行 × 21 列（22+4）
Legacy Route                       49 行 × 18 列
Batch Matrix                       13 行 × 17 列
主键重复                            0
```

### 3.2 跨表一致性

```text
Coverage→Operation 引用             96/96
Method/path/kind/target_batch 冲突  0
authoritative_object 未登记对象      0
Coverage↔Operation 权威对象冲突      0
Coverage 已列响应字段冲突             0
72 个 Operation 批次归属            72/72
批次重复归属                         0
批次遗漏                             0
下载票据归属                         WI-W4-02，恰好 1 次
```

### 3.3 安全与权威口径

```text
COV-099 PUBLIC 预登录               PASS
signed_store_context_token          必填
客户端明文 store_id 决定范围          0
顾客访问他人资源 403 残留             0
顾客端 404 不泄漏存在性               PASS
分页 next_cursor + has_more          PASS
AppointmentConfirmation 本地投影     PASS
未解析 DR-01..DR-10 依赖             0
暴露字段中的内部 int ID               0
暴露字段中的 access_token             0
永久 report_url                      0
遗留路由口径                          44 BLOCK + 5 ALLOW_AFTER
当前有效前端直连                      49/49 BLOCK
```

### 3.4 R1→R2 变更边界

```text
Operation 变化                       6 格
Coverage 变化                        34 格
Resource 变化                        16 格
Legacy 变化                          0 格
Batch 变化                           5 格
非授权变化                            0
```

`Employee` 与 `HomeProduct` 两处依赖字符串仅做已裁定 DR 的规范化表达，不改变对象权威、批次、接口或实现范围，接受为 §2.6 一致性机械收口。

## 4. Git 入库裁定（Claude 立即执行）

Claude 只负责把 W1 冻结证据安全入库，不在本步骤写业务代码。

### 4.1 允许

```text
FETCH = YES
NEW CLEAN BRANCH = YES
COMMIT = YES
PUSH = YES
PR = YES
FORCE PUSH = NO
OLD BRANCH REWRITE = NO
BUSINESS CODE CHANGE = NO
```

### 4.2 执行规则

1. 先只读 `fetch`，确认最新 `origin/main`。
2. 不得推送或改写冻结审计分支：
   `claude/code-handoff-r0-report-niq3rf`。
3. 不得 amend/rebase 已作为历史证据锚点的：
   `3de445f64404e98970be7165202671eb1549cf3d`。
4. 从最新 `origin/main` 新建干净文档分支，建议：
   `docs/dsm-w1-final-freeze-20260723`。
5. 将本裁定文件和 8 份 R2 冻结合同包放入仓库既有治理文档目录；如无既有目录，使用：
   `docs/digital-store-manager/contracts/w1/`。
6. 新增 `SHA256SUMS`，必须与本裁定 §2 完全一致。
7. 本次提交只能包含上述 9 份文件和 `SHA256SUMS`；业务代码、配置、迁移、依赖锁文件变化必须为 0。
8. 使用已确认的正确作者身份提交，推送新分支并创建 PR。
9. PR 标题建议：
   `docs(dsm): freeze W1 production contracts and authorize W2`
10. PR 必须声明：
    `docs-only`、`W1 FINAL FROZEN`、`W2 AUTHORIZED`、`runtime not yet validated`。
11. 不使用 force-push；若最新 main 或目录结构冲突，停止并报告真实冲突，不得改写冻结文件内容。

本步骤结束状态：

```text
W1_GIT_PUBLICATION = PR OPEN
W2 可并行开始，不必等待 docs-only PR 合并
```

是否合并由现有仓库保护规则和检查结果决定；不得绕过 required checks。

## 5. W2 执行安排（Qoder 主责）

### 5.1 负责人

```text
前端主责      Qoder
后端          本轮不施工
独立复核      智谱
服务/预览验收  扣子
最终闸门      ChatGPT
```

### 5.2 W2 唯一范围

构建 35 页生产前端公共底座：

- 可复现构建；
- 35 页路由与公共页面壳；
- 设计 Token 与统一组件基线；
- 单一 API Client；
- 统一响应包络解析；
- 统一身份/门店上下文接口壳；
- 五类七态 UI 壳；
- 统一错误呈现、trace_id 短引用与重试边界；
- API 白名单及 49 条遗留路由阻断；
- 本地契约桩与生产构建隔离；
- 不改变 35 页已冻结业务逻辑、字段语义和一级导航。

### 5.3 W2 禁止事项

- 不接任何真实 API；
- 不修改后端、数据库、迁移、服务或部署配置；
- 不把 11 个 `CANDIDATE_CODE_ONLY_SAFE_AFTER_MERGE` 当作已上线接口；
- 不直连 49 条遗留路由；
- 不在生产构建中保留 mock、演示顾客或假成功；
- 不使用姓名、手机号、展示文案作为资源 ID；
- 不使用 CDN 依赖；
- 不提前实现 W3 身份链；
- 不启动 W4–W7 业务域施工；
- 不改变 W1 冻结 CSV。

### 5.4 W2 必交物

1. 源码变更与可复现构建命令；
2. 35 页路由清单与可达性报告；
3. Design Token 与公共组件清单；
4. API Client 白名单及遗留路由阻断测试；
5. 包络解析、错误码、七态组件测试；
6. mock/演示数据生产构建零残留扫描；
7. CDN/远程运行时依赖零残留扫描；
8. 35 页冻结 DOM/业务语义非授权变化报告；
9. 构建产物 SHA-256；
10. 智谱独立复核报告；
11. 扣子预览拉起与基础交互验收报告；
12. Git branch、commit、PR 与干净工作树证据。

### 5.5 W2 exit gate

```text
reproducible build                  PASS
35/35 route reachable              PASS
API Client whitelist               PASS
legacy direct route                0
production mock/demo residue       0
CDN/runtime remote dependency      0
envelope/error/seven-state tests   PASS
unauthorized business/DOM change   0
independent review                 PASS
preview acceptance                 PASS
```

Qoder 完成后只能声明：

```text
W2-A1 CANDIDATE COMPLETE
```

不得自行声明：

```text
W2 FINAL PASS
W3 AUTHORIZED
```

## 6. Claude 后续任务

Claude 完成 W1 文档入库后暂停业务代码施工。

只有 ChatGPT 对 W2 签发 `W2 FINAL PASS / W3 AUTHORIZED` 后，Claude 才进入：

```text
WI-W3-01  身份 I1 干净分支重排、登录/me/logout、会话与门店绑定
WI-W3-02  daily-loop 任务/预约只读链
```

W3 必须以施工时最新 `origin/main` 为基，不直接合并陈旧 Draft PR，不复用被冻结的旧审计分支历史。

## 7. 当前项目状态

```text
W0          CLOSED
W0-A1-R3A   FINAL PASS
W1          FINAL FROZEN / CLOSED
W2          AUTHORIZED / NEXT
W3          BLOCKED BY W2 EXIT
W4–W8       BLOCKED BY DEPENDENCY MATRIX
```

