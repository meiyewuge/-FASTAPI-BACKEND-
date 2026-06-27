# FRONTEND_V4_P0B_P1_CODE_REPORT

> **Qoder 前端 V4 P0-B + P1 交付报告**
> 分支：`qoder/v4-frontend-workbench`
> Commit：**b0e0741**
> 接口依据：**FRONTEND_V4_CURRENT_API_CONTRACT.md**（唯一真源，取代旧版 REDESIGN_API_CONTRACT）
> Build：✅ vite build 666ms，0 error / 0 warning

---

## 1. 修改文件清单

| 文件 | 变更 | 说明 |
|----|----|----|
| `frontend/api/client.ts` | +74 / -3 | 新增 `composePreview()` + `ComposePreviewResult` 等类型；`compose()` 签名改为 `director_plan_id + confirmed_cost` |
| `frontend/pages/Workbench.tsx` | +538 / -117 | 完全重写：A台 preview→compose 流程 + 图片 role 拖拽 + localStorage 草稿 + 4031/2002 |
| `frontend/styles.css` | +346 / 0 | 图片角色排序区、A台配置行、Preview 面板、分镜卡片、Seedance 提示词折叠、维护态按钮 |

**合计**: 3 文件，+958 / -120

---

## 2. 交付项逐条确认（16 项）

| # | 要求 | 状态 | 实现说明 |
|---|----|----|----|
| 1 | 以 FRONTEND_V4_CURRENT_API_CONTRACT.md 为唯一依据 | ✅ | 所有端点签名、错误码、流程均对齐新合同 |
| 2 | 实现 compose preview（`POST /api/compose/preview`） | ✅ | `composePreview()` in client.ts；`handlePreview()` in Workbench |
| 3 | 展示 director_plan（分镜卡片） | ✅ | `preview-panel` → `storyboard-section` → `storyboard-card`（镜头号/时码/画面/台词/图片引用） |
| 4 | 展示 seedance_text_prompt | ✅ | 可折叠 `seedance-prompt` 区域，点击展开 T1-T5 结构化提示词 |
| 5 | 展示 image_roles | ✅ | `preview-image-roles` + `role-chips`（首帧/参考图角标） |
| 6 | 图片排序 + role 自动更新 | ✅ | `image-role-list` 拖拽排序；第 1 张 = first_frame，2-9 张 = reference_image；拖拽后 badge 自动切换 |
| 7 | localStorage 草稿恢复 | ✅ | `LS_DRAFT_KEY = v4_compose_draft`；debounce 500ms 写入；页面加载恢复；提交成功（拿 task_id）后 `clearDraft()` |
| 8 | A台费用确认 | ✅ | `handleComposeConfirm()` → `confirm("本次生成预计消耗 ¥${estimated_cost}…")` → compose(director_plan_id, true) |
| 9 | 正确处理 4031 | ✅ | compose 返回 4031 → `setComposeMaintenance(true)` + 按钮置灰 `btn-maintenance` + 文案「生成通道维护中，暂不可用。」 |
| 10 | 正确处理 2002 | ✅ | preview/compose 返回 2002 → toast「图片无法被视频模型访问，请重新上传或等待处理完成。」 |
| 11 | 使用 source_video_ids（非 sources） | ✅ | `batchGenerate()` in client.ts → `{ source_video_ids, prompt, auto_ratio, max_outputs, strategy }` |
| 12 | 维护 current_source_video_ids | ✅ | useState + 上传视频成功自动加入 + A台生成母视频自动加入 + 删除视频时移除 |
| 13 | 读取 duration_seconds | ✅ | `qualifiedSources` 过滤 `duration_seconds != null && >= 30`；卡片显示时长/时长未知 |
| 14 | B台 3 个 30 秒门槛 | ✅ | `bEnabled = qualifiedCount >= 3 && !batchRunning && !composeRunning`；不足时 toast 门槛提示 |
| 15 | 自动刷新裂变陈列面 | ✅ | pollBatchStatus done → `loadViral(1, batch_id)` + `scrollIntoView({ behavior: "smooth" })` |
| 16 | feedback pending 文案 | ✅ | `handleFeedback()` → `showToast("已加入候选池，待审核")`；feedback-dropdown 底部显示同一文案 |

---

## 3. 自查清单（20 项）

| # | 检查项 | 状态 |
|---|----|----|
| 1 | A台不直接调 compose 生成（必须先 preview） | ✅ handleAConfirm → handleComposeConfirm，compose 必带 director_plan_id |
| 2 | compose 请求带 confirmed_cost: true | ✅ `compose(directorPlanId, true, totalSeconds)` |
| 3 | preview 不花钱、不调火山 | ✅ POST /compose/preview，后端不调 provider |
| 4 | 费用确认弹窗用 estimated_cost（不写固定单价） | ✅ `¥${est.toFixed(2)}（以实际扣费为准）` |
| 5 | 4031 按钮置灰 + 文案 | ✅ `btn-maintenance` class + `composeMaintenance` state |
| 6 | 2002 错误透传给用户 | ✅ preview + compose 两处都处理 |
| 7 | 3001 plan 过期处理 | ✅ toast「导演稿已过期，请重新预览」+ 清除 previewResult |
| 8 | 4029 额度不足处理 | ✅ compose 返回 4029 → toast 提示 |
| 9 | B台请求体 source_video_ids | ✅ batchGenerate() |
| 10 | B台 done 后刷新 + 滚动 | ✅ loadViral + scrollIntoView |
| 11 | ignored_source_video_ids 提示 | ✅ `部分视频未参与本轮裂变` |
| 12 | events/track fire-and-forget | ✅ trackEvent() try/catch 仅 console.warn |
| 13 | feedback 文案「已加入候选池，待审核」 | ✅ 非「已入库」 |
| 14 | 候选池仅 super_admin | ✅ AdminPanel.tsx `isSuper` 判断 |
| 15 | Patch6 权限完整 | ✅ ENABLE_ADMIN_KEY_FALLBACK=false，JWT 鉴权，/api/me 定角色 |
| 16 | 管理员入口靠 role | ✅ super_admin → 管理员后台+候选池；invite_admin → 发码；user → 无入口 |
| 17 | localStorage 草稿 debounce 500ms | ✅ useEffect + setTimeout 500ms |
| 18 | 提交成功后清除草稿 | ✅ clearDraft() in handleComposeConfirm |
| 19 | 图片 role 拖拽排序 | ✅ native HTML5 DnD（dragStart/dragOver/dragEnd） |
| 20 | build 通过 | ✅ vite build 666ms, 0 error |

---

## 4. 禁止事项确认

| 禁止项 | 状态 |
|----|----|
| 不改后端 | ✅ 仅改前端 3 文件 |
| 不碰 production | ✅ 分支 qoder/v4-frontend-workbench |
| 不触发真实火山生成 | ✅ preview 不调火山；compose 后端 ENABLE_COMPOSE=false |
| 不做大文件压测 | ✅ |
| 不做真实 50 条压测 | ✅ |
| 不恢复 ADMIN_KEY | ✅ ENABLE_ADMIN_KEY_FALLBACK=false 保持不变 |

---

## 5. 后续联调注意事项

1. **后端 compose preview 需要真实部署**：当前 `claude/v4-staging` 有 preview 端点，但 staging 环境未部署
2. **DB migration**：`director_plans` 表 + `cost_ledger` 表需 `create_all` 或手动 ALTER
3. **上传图片返回 file_id**：preview 的 `image_file_ids` 来自 batch upload 的 `uploaded[].file_id`
4. **ENABLE_COMPOSE=false**：staging 联调时 compose 会返回 4031，验证前端维护态展示
5. **duration_seconds backfill**：联调前需执行 `python -m tasks.backfill_duration`

---

*报告生成时间：2026-06-25*
*Qoder 精装修交付 — 可交 ChatGPT 审核*
