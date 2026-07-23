# DSM_W1_GLOBAL_PRODUCTION_CONTRACT_R2

**状态:`DRAFT_FOR_CHATGPT_REVIEW`(R2 跨表一致性收口版)** — 依 `W1_A1_R2_..._CONSISTENCY_ORDER.md`(SHA `89b80741…`)。不推翻 R1:A1/R1 已通过条款全部沿用(A1 `f90f017e…`、R1 `5ba706dc…` 冻结保留),本文件仅记录 R2 修正。`CURRENT_RUNTIME_EVIDENCE = NONE`。

## R2-1 跨表权威对象一致(§2.1)
覆盖矩阵 17 行 `authoritative_object` 与操作合同精确对齐:11 行 `Task_upstream|Appointment_upstream`→`Task+Appointment`(COV-002/003/009/010/011/012/036/037/068/069/070);5 行→`CustomerIdentity+CustomerAuthSession+CustomerStoreAuthorization+ServiceRecord`(COV-097/098/099/101/102);COV-029→`Report`。机械闸门:未登记对象=0、Coverage↔Operation 不一致=0。

## R2-2 顾客登录 PUBLIC 预登录(§2.2)
COV-099 与 `OP-CUSTAUTH-LOGIN` 完全一致:request=`code+signed_store_context_token`(拒绝明文 store_id);`actor_scope=PUBLIC`、`store_scope=signed_store_context_token_verified_server_side`、`resource_scope=NONE_prelogin`;响应补 `data.expires_at:str:req`;notes=PUBLIC_prelogin;server_verifies_signed_store_context_token;issues_independent_CUSTOMER_SESSION;never_staff_session。

## R2-3 顾客端 404 不泄漏存在性(§2.3)
`OP-CUSTVIEW-HOME`/`OP-CUSTVIEW-SERVICE-RECORDS` 及 COV-097/098/101/102 统一:`403=STORE_UNBOUND|ROLE_FORBIDDEN`;`404=RESOURCE_NOT_FOUND(含他人资源,不泄漏存在性)`;`RESOURCE_FORBIDDEN_on_others` 全部删除。店长/员工跨店 403 合同不变。

## R2-4 覆盖分页与字段可选性(§2.4)
COV-007/COV-101 补 `data.next_cursor:str:opt + data.has_more:bool:req`;COV-016/COV-094 `role/store_id`→opt、COV-021 `report_id`→req;附加同步 COV-078 `data.status`→`str:req(in_review)`(与操作一致)。程序化比对:已列字段路径缺失=0、类型不一致=0、req/opt 不一致=0。

## R2-5 Appointment 落实 DR-03=B(§2.5)
资源行改为:authority=`upstream_daily_loop+local_AppointmentConfirmation_projection`;id_generator=`appointment_facade`;facade=`FACADE_READ+LOCAL_CONFIRMATION_PROJECTION`;write=`local_AppointmentConfirmation_projection`;read=`upstream_facade+local_confirmation_projection`;外部 ID 保持 `apt_<opaque12>`(不上游直通)。notes 同时保留 W0 事实(上游只读、无本地确认写链)与 W1 裁定(确认写本地投影、引用上游 appointment_id、状态遵循上游 VALID_TRANSITIONS)。资源表 W1 列 `TBD/DECISION_WRITE = 0`。

## R2-6 已裁定 DR 不再作未解决依赖(§2.6)
8 个资源行 `blocking_dependencies` 改为 `RESOLVED_DR-02=B_clean_branch / RESOLVED_DR-05=A_full_domain(×4) / RESOLVED_DR-06=A_service_domain(×2) / RESOLVED_DR-07=A_event_ledger`(HomeProduct/Employee 同步规范化);批次表 `WI-W5-01.hard_dependencies → WI-W4-03;RESOLVED_DR-05=A_full_domain`。机械闸门:blocking/hard 依赖中未解析 DR = 0。

## R2-7 下载票据归报告域(§2.7)
`OP-REPORT-DOWNLOAD-TICKET` 从 WI-W4-04(service)移至 **WI-W4-02(diagnosis/report)**;WI-W4-02 交付物 += 短时签名下载票据+限频+下载审计;exit_gate += 下载票据 E2E 与越权测试通过。该操作在 W2–W7 工作项中恰好归属 1 次。

## R2-8 统计勘误(§2.8)
R1 自检"A1→R1 operation 385 格"为生成过程中间计数(含新行单元格重复计入),**勘误为:共享单元格实际变化 = 343,新增行 = 1**(独立逐 id 逐列重算一致)。R2 统计一律取自最终文件 diff(见 R2 自检 §2)。

## 不变项
遗留路由 49 行处置事实不变(44 BLOCK + 5 ALLOW_AFTER;当前有效直连 49/49 BLOCK,R2 文件与 R1 逐字节一致);操作 72、资源 26=22+4、页面 35/35、int ID=0、access_token=0、永久 report_url=0、写安全 A–G 七类完整、DR 10/10 RESOLVED_FOR_CHATGPT_FINAL_REVIEW。
