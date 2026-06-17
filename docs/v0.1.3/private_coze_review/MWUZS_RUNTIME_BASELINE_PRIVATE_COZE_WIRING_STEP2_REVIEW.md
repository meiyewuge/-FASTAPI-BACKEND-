# MWUZS_RUNTIME_BASELINE_PRIVATE_COZE_WIRING_STEP2_REVIEW

> 工单：PRIVATE_COZE_WIRING_STEP2 审查包 ｜ **只做 private**，未合 main/未 push/未部署/Coze 未介入/未进入 content。
> 审查对象（**private-only 增量**）：base `04bc8ba`（STEP1 chat）→ target `405f341`（STEP2 private）
> diff 范围 = `04bc8ba..405f341`（**不含 chat 代码**，已校验无 `ai_chat` 函数改动）。

## 1. 本轮只做了 private
仅把 `POST /api/private/generate` 从「场景字典模板」改成「真实 Coze Workflow + 灰度 + 降级 + 护栏 + 真实标签」。
**未进入 content；未改 chat 行为边界；未迁 manager；未动 `/api/store-manager/*`；未改前端。**

## 2. changed files（private-only，3 个，+123/-10）
| 文件 | 改动 |
|------|------|
| `backend/app/config.py`（+6/-1） | 新增 `coze_private_enabled / coze_private_workflow_id`（**仅读取，无真实值**） |
| `backend/app/coze_client.py`（+45） | 新增 `run_workflow()`（Coze v1 `/workflow/run`，httpx async，data 二次 JSON 解析，超时，**不记录 token/请求头**，失败抛 `CozeError`）+ `private_configured()` |
| `backend/app/routers/weapp.py`（+82/-?） | `/api/private/generate` async 化 + Workflow/降级分流 + scene_type 分流兜底 + 软化护栏 + 真实标签；新增 `_PRIVATE_SOFTEN`/`_soften_private` |

## 3. private 修复前后契约对比
| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 实现 | `_PRIVATE_SCENES` 场景字典模板 | `COZE_PRIVATE_ENABLED=true` 且配置完整 → Coze Workflow；否则/任何失败 → 场景模板降级 |
| 前端契约 | `data.{answer,tips}` | `data.{answer,tips}`（**不变，前端无感**）+ 附 `source/confidence_label/degraded/scene_type` |
| 标签 | 永远 `知识库+模型生成`（**假标**） | 真实：成功=`source:coze`/`扣子知识库+模型生成`/`degraded:false`；模板=`source:local_fallback`/`本地模板(降级)`/`degraded:true` |
| 场景分流 | `.get(scene_type, reactivate)` | 5 场景显式分流；**非法/缺失统一兜底 `reactivate`** |
| 护栏 | 无 | 软化：不硬推/不贬同行/不紧迫逼单/不疗效承诺 |
| 健壮性 | — | `answer` 始终可用；`tips` 缺失给 `[]`；**不白屏、不 500** |

## 4. 测试摘要（10 PASS / 0 FAIL，见 TEST_OUTPUT.txt）
1. `COZE_PRIVATE_ENABLED=false` → 模板降级、不假标、answer 非空 + tips 数组 ✅
2. enabled=true 但缺 token/workflow_id → 降级 ✅
3. Workflow 成功 → `source=coze`/`degraded=false`/`扣子知识库+模型生成`，answer/tips 来自 Workflow ✅
4. 非法 `scene_type` / 缺失 `scene_type` → 兜底 `reactivate`（两例）✅
5. 命中"隔壁家差/限时/最后一个名额/保证治好" → **软化**为"每家定位不同/近期/名额有限/帮助改善体验" ✅
6. Coze 异常 → 降级模板、不假标 ✅

## 5. scene_type 5 场景分流与兜底
- 合法键：`reactivate / objection / invitation / aftercare / followup`。
- 非法值或缺失 → 后端统一兜底 `reactivate`（真实/降级路径都生效）；返回体回显 `scene_type`。

## 6. 软化规则（绝对禁止项落地）
`_soften_private` 命中即替换违规措辞（真实输出与降级输出都过）：
- **不硬推/不紧迫逼单**：限时/最后名额/最后一个名额/错过没有了 → 名额有限/近期/欢迎随时了解。
- **不贬同行**：隔壁家差/别家骗人/同行垃圾 → 每家定位不同/建议综合判断/每家各有特色。
- **不疗效承诺（含售后不替代就医的口径基线）**：保证治好/一定见效/根治 → 帮助改善体验/因人而异/调理改善。
> 无法软化（整段违规）时由上层判无效 → 降级模板。售后场景的"不替代就医"在场景模板与 Coze prompt 双层约束。

## 7. 模板降级标签真实化
任何模板/降级输出强制 `source=local_fallback`、`degraded=true`、`confidence_label=本地模板(降级)`、`confidence=low`、`quality_score=60`，**绝不标"知识库+模型生成"**。仅真实 Workflow 成功才 `source=coze`。

## 8. 边界声明
- 未 merge main、未 push main、未部署、未 scp、未动 ECS/Nginx/SSL/安全组/18080/18081。
- **当前仍未轮到 Coze 介入**；**当前仍未进入 content**。
- 未改 chat 已通过部分行为；未迁 manager、未动 `/api/store-manager/*`；未碰真实 token/env。

## 9. 安全
本 patch 为 `04bc8ba..405f341` 的 **private 增量**；经扫描**无真实 token/密钥明文**；配置项默认空，真实值经环境变量注入。
