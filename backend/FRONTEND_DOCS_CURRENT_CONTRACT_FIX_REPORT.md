# 前端文档收口报告 · FRONTEND_DOCS_CURRENT_CONTRACT_FIX_REPORT

> 仅改文档：**未写业务代码、未改 production、未触发火山、未部署**。分支 `claude/v4-staging`。
> 起因：ChatGPT 复审发现前端文档包接口合同不一致（旧合同仍写 B台 `sources`、无 `/api/compose/preview`、无 `4031`、无 Director preview 流程）。

## 1. 是否已新增统一接口合同 —— ✅ 是
- 新增 **`FRONTEND_V4_CURRENT_API_CONTRACT.md`**，作为 Qoder 前端开发**唯一接口依据**，含 14 个模块（登录权限 / 上传 / A台 preview / A台 compose / B台裂变 / B台轮询 / 视频列表 / storage / track / feedback / 候选池 / 错误码 / 红线 / 流程串联）。

## 2. 是否已标记旧合同废弃 —— ✅ 是
- `FRONTEND_V4_REDESIGN_API_CONTRACT.md` 顶部加醒目「⛔ 已废弃 / DEPRECATED」标注，指向 `FRONTEND_V4_CURRENT_API_CONTRACT.md`，并说明仅作历史参考、请勿据此开发。

## 3. 是否已合并 preview 流程 —— ✅ 是
- 新合同 §3 `POST /api/compose/preview`：请求字段（prompt/image_file_ids/style/ratio/duration/resolution）；返回字段（director_plan_id/director_plan/seedance_text_prompt/seedance_content/image_roles/estimated_cost/generate_audio/warnings）；明确 **不调火山、不扣费**。
- §4 正式 compose：必带 `director_plan_id + confirmed_cost=true`；**前端不得绕过 preview**。
- §13 红线第 1 条强调「先 preview 后 compose」。

## 4. 是否已合并 B台 source_video_ids —— ✅ 是
- 新合同 §5：P1 标准请求体 `{prompt, source_video_ids, auto_ratio, max_outputs, strategy}`；`sources` **仅兼容旧版、不能作前端主字段**；返回含 `batch_id/source_count/total_outputs/ignored_source_video_ids/status/cost=0`；三层选源优先级 + 1:10 + 30/40/50。

## 5. 是否已写清 4031 —— ✅ 是
- §4 与 §12 错误码表：`4031` = A台 compose 熔断锁「生成通道维护中，暂不可用。」→ 前端生成按钮置灰 + 显示文案。

## 6. 是否已写清 2002 —— ✅ 是
- §3 与 §12：`2002` = 图片无法被视频模型访问 →「图片无法被视频模型访问，请重新上传或等待处理完成。」

## 7. 是否已写清 duration_seconds —— ✅ 是
- §7 视频列表 item 必含 `duration_seconds`（可能 null=时长未知）；§5 与 §12 明确 B台合格门槛 `duration_seconds>=30`，NULL/<30 不计入合格源。

## 8. 是否已写清 Patch6 权限 —— ✅ 是
- §1：`/api/me` 定角色；super_admin/invite_admin/user 权限矩阵；**ADMIN_KEY 不恢复为前端发码通道**，一律 JWT；候选池仅 super_admin。

## 9. 是否可以交 Qoder 前端开发 —— ✅ 可以
- 三份现行文档一致、无冲突：
  - `FRONTEND_V4_CURRENT_API_CONTRACT.md`（唯一真源）
  - `FRONTEND_V4_P1_QODER_MIGRATION_NOTES.md`（B台迁移细则）
  - `FRONTEND_V4_P0B_PREVIEW_QODER_NOTES.md`（A台 preview 细则）
- 旧 `FRONTEND_V4_REDESIGN_API_CONTRACT.md` 已废弃标注，避免误读。

## 交付物
- 新增：`FRONTEND_V4_CURRENT_API_CONTRACT.md`、本报告。
- 更新：`FRONTEND_V4_REDESIGN_API_CONTRACT.md`（废弃标注）。
- 重新打包：`V4_FRONTEND_for_Qoder_CURRENT_20260625.zip`（4 文件：当前合同 + P1 迁移 + P0-B preview + P0-A/P0-B 后端报告）。
- commit 号见推送结果。
