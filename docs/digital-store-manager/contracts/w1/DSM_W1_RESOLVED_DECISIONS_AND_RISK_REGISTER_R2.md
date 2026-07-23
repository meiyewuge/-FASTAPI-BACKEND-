# DSM_W1_RESOLVED_DECISIONS_AND_RISK_REGISTER_R2

状态:`DRAFT_FOR_CHATGPT_REVIEW`。DR-01..DR-10 已由 ChatGPT 裁定,(R1 已改标,R2 维持) **`RESOLVED_FOR_CHATGPT_FINAL_REVIEW`**——保留证据、选项与理由,不再存在"技术待决定";CSV 中原 `DECISION_REQUIRED`/`BLOCKED_BY_AUTHORITY_DECISION` 引用已同步为 `RESOLVED_DR-xx`。

| decision_id | title | 裁定 | 采纳内容(执行口径) | 原证据(保留) | blocking_batch | status |
|---|---|---|---|---|---|---|
| DR-01 | 门店三套 ID 统一 | **A** | 新建权威门店注册表;主库 int/v013 str/binding.dl_store_id 全部映射;对外仅 `store_<opaque>` | models.py:15;db_v013.py:32;identity/models.py:77 | W3 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-02 | 身份 I1 合并路径 | **B** | 以施工时最新远端 main 为基,重排身份提交为单一干净分支后重新审计;不把陈旧 Draft PR 直接当生产基线合并 | PR#4 Draft(head 4525392/base 306a72a);remote_tip UNCONFIRMED | W3 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-03 | 预约确认落点 | **B** | 上游保持只读;门店确认写本地 AppointmentConfirmation 投影/事件表,引用上游 appointment_id,状态口径对齐上游 VALID_TRANSITIONS | R3A:r005;daily_loop/models:88 | W4 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-04 | 诊断/月度多权威 | **A** | Diagnosis 写权威=v013 规则实现;MonthlyCheckup 写权威=主库;Report 统一读面+下载票据;v012 仅只读导入,不再形成第二写权威 | R2 存储表;碰撞矩阵 §3 | W4 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-05 | 内容/分群/激活域 | **A** | W5 全量:内容持久化、版本审核、分群、私域、激活闭环;不裁页面 | weapp.py:46;R2 MISSING×4 | W5 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-06 | 员工/服务域边界 | **A(批次修正)** | Employee 独立实体+关联 Binding;**核心前移 W4**(供服务记录/责任人/审计),W5 完成团队管理与统计;ServiceRecord/Experience 归服务域 | db_v013.py:264;14 表清单 | W4/W5 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-07 | 消耗台账 | **A** | 新建 ConsumptionRecord 事件台账;存量 used_quantity 记开账余额;回滚用冲销事件,不改历史 | customer_ops_v013.py:158 | W4 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-08 | 4 处碰撞处置 | **A** | 保留 v013 处理器为内部实现,删除/停用 v012 四个被遮蔽处理器;生产面不暴露任何碰撞路径 | R3 碰撞矩阵 MISMATCH_CONFIRMED | W4 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-09 | 双任务域 | **A** | 页 03/24=daily-loop 顾客任务(详情/回执为本地投影新建);页 01/26=v013 行动任务;两域独立内部域+独立外部 ID 命名空间 | 冻结台账#03;R3A:r004/r027 | W3/W4 | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |
| DR-10 | 首期范围 | **A(吴哥原则固化)** | 全量 35 页纳入本期,按 W2–W8 分批;缺什么后端补什么后端;不把 W5/W7 裁成不确定后续 | 总方案 §5 | W5+ | RESOLVED_FOR_CHATGPT_FINAL_REVIEW |

## 风险登记(更新)
| risk_id | 风险 | 缓解(R1 后状态) | 级别 |
|---|---|---|---|
| RK-01 | 生产误连 49 条遗留端点 | 处置口径修正:**44 BLOCK + 5 ALLOW_AFTER_W1_FREEZE_AND_IMPLEMENTATION;当前有效直连 49/49 BLOCK**;W2 API Client 白名单 | 高 |
| RK-02 | demand-board 泄漏手机号 | 字段合同已改 `phone_masked`(不再仅 notes) | 高→中 |
| RK-03 | 消耗/报告重复提交 | 写类 C 幂等合同 + DR-07 台账 RESOLVED;W4-03 横切先行 | 高→中 |
| RK-04 | mock 登录误当真实 | 11 行 CANDIDATE_CODE_ONLY_SAFE_AFTER_MERGE 标注;W3 前禁真实登录联调 | 中 |
| RK-05 | 远端 main tip UNCONFIRMED | DR-02=B:施工时以最新远端 main 重排;开工前 live fetch 复核 | 中 |
| RK-06 | 内存内容数据/演示数据混入 | W5 持久化(DR-05=A);W2 构建隔离演示数据 | 中 |
| RK-07(新) | 顾客端存在性泄漏 | 顾客端他人资源统一 404(全局合同 R1-2) | 中 |
| RK-08(新) | signed_store_context_token 签发面被滥用 | 票据短时+绑定顾客 openid+门店;W7 设计审查项 | 中 |


## R2 增补说明
- CSV 依赖字段规范化(§2.6):8 个资源行与 WI-W5-01 的依赖字符串统一为 `RESOLVED_DR-xx=选项` 形式;登记册本表自 R1 起即为 10/10 `RESOLVED_FOR_CHATGPT_FINAL_REVIEW`,无内容变化。
- DR-03=B 已在资源表 Appointment 行完全落地(本地 AppointmentConfirmation 投影,无 TBD/DECISION_WRITE 残留)。
- 顾客端他人资源 404 不泄漏存在性已落到 OP/COV 行(RK-07 缓解状态:已写入字段级合同)。
