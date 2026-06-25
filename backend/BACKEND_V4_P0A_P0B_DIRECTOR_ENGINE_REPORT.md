# 后端 V4 P0-A 安全止血 + P0-B Director-Prompt Engine 报告

> 范围：**后端 only**。本轮只做 **P0-A 安全止血 + P0-B Director-Prompt Engine 最小闭环**。
> **未做**：完整闭口裂变 30 条、Seedance 2.5、素材库商业接入、真实火山压测、production 解锁。
> **未启用真实 compose**（ENABLE_COMPOSE 默认 false）；**未触发火山**；不碰 production。
> 依据：《V4_BUG_FIX_AND_PRODUCTION_SOP》3.2a。分支 `claude/v4-staging`。

## 1. commit 号
- **`7922fe3`**（`V4 P0-A 安全止血 + P0-B Director-Prompt Engine 最小闭环`），已推送 `claude/v4-staging`。

## 2. BUG-1（compose 线程卡死）修复方式
- compose 改**独立 daemon 线程**派发：`tasks/runner.dispatch_compose(task_id)` → `threading.Thread(..., daemon=True)`，不占用 uvicorn 线程池（避免长轮询阻塞）。
- runner 新增**inflight 锁**（`_inflight` set + Lock）：`execute_task` 同一 `task_id` 只执行一次，重复触发直接跳过（防 recovery / 双触发重复跑火山）。
- `/api/compose` 不再 `bg.add_task`，改 `dispatch_compose`。

## 3. BUG-2（计费偏差/暗烧）修复方式
- **定价修正**：`pricing_model._PRICE_PER_SEC["1080p"]["generate"]` 1.05 → **2.48**（火山官方）。价格**单一真源**在 `pricing_model`，新增 `estimate_cost()`，provider/engine/ledger 一律调用，无散落硬编码。
  - 验证：`estimate_cost("video.generate.a",15,"1080p") == 37.20`。
- **cost_ledger 流水台账**（新表 `cost_ledger`）：`estimate / precharge / refund / final_adjust` 四类事件，按 `task_id + provider_job_id` 全程可追踪。
- **提交即预扣**：compose 拿到 `provider_job_id` 立即 `precharge`（不等完成），杜绝「线程卡死但火山已扣费」的暗烧。
- **失败自动退**：`execute_task` 失败路径调 `cost_ledger.refund` 并 commit。
- **去重**：`already_precharged(task_id, job_id)` 保证 recovery / 重试不重复预扣（验证：重复 precharge 返回 0）。

## 4. RISK-1 熔断锁是否完成 —— ✅ 完成
- `config.enable_compose: bool = False`（默认锁）。
- `/api/compose`：`enable_compose=false` → `code:4031`「生成通道维护中，暂不可用。」**不提交火山**。
- 防御纵深：`compose_service.run()` 开头同样校验，即便绕过路由也拒绝。
- 前端可显示按钮，后端未解锁即拒绝。

## 5. recovery 是否防重复 submit —— ✅ 是
- `recovery.recover()`：`task.type=="compose" and not enable_compose` → **跳过**（不重跑、不预扣）。
- 已有 `provider_job_id` 的任务：inflight 锁 + compose 续传逻辑保证不二次 submit。
- 验证：锁未开时 compose pending 任务被跳过，状态保持 pending，无 precharge。

## 6. provider_job_id 是否持久化 —— ✅ 是
- `Task` 新增列 `provider_job_id VARCHAR(64)`；compose 拿到 job_id 即写入（首个），恢复时据此判断已提交。

## 7. cost ledger 是否完成 —— ✅ 完成
新表 `cost_ledger` 字段：`task_id, provider_job_id, tenant_id, user_phone, model, resolution, duration_seconds, request_type, estimated_amount, precharged_amount, actual_amount, event_type(estimate|precharge|refund|final_adjust), status, created_at`。
函数：`estimate / precharge / already_precharged / refund / final_adjust / net_charged`。

## 8. refund 是否完成 —— ✅ 完成
- 任务 `failed/cancelled` → `refund` 写一条负额 `actual_amount` 流水，已退则不重复退。
- 验证：failed compose 任务自动退回 ¥37.20。

## 9. Director-Prompt Engine 是否完成 —— ✅ 完成
`services/director_prompt_engine.py` 5 个函数（SOP Step1-5）：
- `extract_brand_context(prompt, profile=None)` — 品牌名/产品名/卖点(1-3)/slogan/场景词。
- `direct_storyboard(prompt, brand_context, image_roles, style, duration)` — 逐段分镜（时码/画面/台词/图片引用），叙事节奏 开场→卖点→品牌收束。
- `assemble_prompt(brand_context, storyboard, style)` — T1-T5 结构化中文提示词。
- `assign_image_roles(image_file_ids)` — 第1张 first_frame / 第2-9张 reference_image。
- `assemble_seedance_content(text_prompt, image_roles)` — content[]（text + image_url role）。
- 另有 `build_director_plan()` 串起 Step1-5。

## 10. T1-T5 模板是否代码化 —— ✅ 是
`prompt_templates/director_prompt_v1.py` 固定 5 段式模板（T1 产品定格 / T2 风格基调 / T3 逐镜指令 / T4 品牌收束 / T5 禁止项），变量由引擎填入，用户不碰模板。风格预设 `style_presets.py`（premium/fresh/chinese），禁止词 `negative_words.py`，品牌注入 `brand_injection_rules.py`（开场/中间/收束三种注入格式）。

## 11. 模板版本是否记录 —— ✅ 是
每条 `director_plan` 记录三版本：`director_prompt_version=director_prompt_v1`、`style_preset_version=style_preset_v1`、`negative_words_version=beauty_safe_v1`。

## 12. compose preview 是否完成 —— ✅ 完成
`POST /api/compose/preview`（require_auth）：**不调火山、不扣费**，返回
`{director_plan_id, director_plan{brand_context,storyboard,versions}, seedance_text_prompt, seedance_content, image_roles, estimated_cost, ratio, resolution, duration, generate_audio, warnings}`，结果落 `director_plans` 供正式 compose 复用。
- 验证：preview 期间 httpx 设陷阱未触发；ledger 仅 `estimate` 无 `precharge`。

## 13. image_file_ids 是否进入 content[] —— ✅ 是
`assemble_seedance_content` 产出 `content=[{type:text}, {type:image_url, image_url:{url}, role}...]`；preview 返回 `seedance_content`，第1张 role=first_frame。provider 链（generator → video_provider → volcano `_submit`）已支持 `content[]` 直传（默认走 content[]，兼容旧 prompt 字符串）。

## 14. generate_audio 是否可配置 —— ✅ 是
`config.compose_generate_audio=True`（+ `compose_ratio=9:16`、`compose_resolution=1080p`、`compose_watermark=False`）。preview 返回 `generate_audio`；volcano `_submit` 注入 `generate_audio`/`watermark`。

## 15. 图片 HTTPS 校验是否完成 —— ✅ 完成
`utils/image_url_check.resolve_image_roles`：逐图校验 **属于当前 tenant + 存在 + storage_status=active + 可生成 HTTPS 公网 URL + 本地文件在**；任一失败 → `ImageAccessError` → 路由 `code:2002`「**图片无法被视频模型访问，请重新上传或等待处理完成。**」无图=纯文生（合法）。
> 注：外部模型可达性（external reachability）在 sandbox 不真发请求；生产可开启探测（预留）。

## 16. DB migration SQL
新表（`create_all` 自动建，全新库无需手工）：`director_plans`、`cost_ledger`。
存量表新增列（生产已存在则手工 ALTER）：
```sql
ALTER TABLE tasks ADD COLUMN provider_job_id VARCHAR(64);
-- 新表（若生产无）：
-- director_plans(id PK, tenant_id, user_phone, prompt, style, ratio, duration_seconds,
--   resolution, director_json, seedance_text_prompt, image_roles_json,
--   director_prompt_version, style_preset_version, negative_words_version,
--   estimated_cost, status, created_at)
-- cost_ledger(id PK, task_id, provider_job_id, tenant_id, user_phone, model, resolution,
--   duration_seconds, request_type, estimated_amount, precharged_amount, actual_amount,
--   event_type, status, created_at)
```
回滚：`ALTER TABLE tasks DROP COLUMN provider_job_id;` + `DROP TABLE director_plans; DROP TABLE cost_ledger;`（SQLite<3.35 保留空列即可）。

## 17. 测试结果（`tests/verify_v4_p0a_p0b.py`，16/16 ✅）
```
✔ BUG-2 定价修正：1080p 15s = ¥37.20
✔ preview 未调用火山（httpx 陷阱未触发）
✔ preview 不扣费（仅 estimate 流水）
✔ preview 返回 director_plan（含分镜）
✔ preview 返回 T1-T5 结构化提示词 + 模板版本
✔ 图片 role：第1张 first_frame，第2-9张 reference_image（HTTPS）
✔ image_file_ids 进入 content[]；generate_audio 可配置；费用预估=37.20
✔ 图片不可访问 → 2002 清晰错误
✔ ENABLE_COMPOSE=false → 4031 拒绝
✔ 未 confirmed_cost → 拒绝
✔ 无 director_plan 且无 prompt → 拒绝
✔ 有 director_plan + confirmed_cost → 放行（dispatch 拦截，不真跑火山）
✔ precharge 立即扣费；重复 precharge 去重=0
✔ 任务 failed → 自动 refund
✔ recovery 跳过 compose（锁未开）→ 不重复 submit、不预扣
✔ provider_job_id 持久化
✔ Patch6 管理员权限不受影响
```
**全量回归（11 套全过）**：`verify_v4_p1_remix`（B台 P1 裂变不受影响）、`verify_v4_p0`、`verify_v4_closeout`、`verify_v4_reflow`、`test_volcano_pipeline`、`test_b9_local_remix`、`verify_patch4/4.1/5/6`。
- 环境：sandbox + 真实 ffmpeg/ffprobe + httpx 桩（**无真实火山 key、未启用 compose、无大文件压测**）。

## 18. 是否可以交 Qoder 做前端 preview / localStorage / 图片 role 展示 —— ✅ 可以
- **preview**：`POST /api/compose/preview`（返回导演分镜、T1-T5 提示词、image_roles、estimated_cost、warnings）。
- **localStorage**：前端可缓存草稿（prompt + image_file_ids + style）；提交后清除。
- **图片 role 展示**：用 `image_roles[].role`（first_frame / reference_image）标注每张图角色。
- **A台真生成按钮**：可显示，但后端 `ENABLE_COMPOSE=false` 时返回 4031「生成通道维护中，暂不可用。」前端据此置灰/提示。
- **费用确认**：preview 返回 `estimated_cost`；正式 `/api/compose` 必须带 `confirmed_cost=true` + `director_plan_id`。

## 本轮明确未做（归档）
完整 closed-loop fission 30 条、P4.3 差异化增强、Seedance 2.5、外部素材库、真实火山批量压测、production 解锁。
