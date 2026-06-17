# MWUZS_RUNTIME_BASELINE_CONTENT_COZE_WIRING_STEP3_REVIEW

> 工单：CONTENT_COZE_WIRING_STEP3 审查包 ｜ **只做 content** ｜ **Claude 开发线最后一拍**。
> 未合 main/未 push/未部署/Coze 未介入/未进入收口合成。
> 审查对象（**content-only 增量**）：base `405f341`（STEP2 private）→ target `1e6aabc`（STEP3 content）
> diff 范围 = `405f341..1e6aabc`（**不含 chat/private**，已校验无 `ai_chat`/`generate_private` 函数改动）。

## 1. 本轮只做了 content
仅把 `POST /api/content/generate` 从「硬编码模板 + flatten」改成「真实 Coze Workflow + 灰度 + 降级 + 平台护栏 + 真实标签」。
**未改 chat/private 已通过行为；未迁 manager；未动 `/api/store-manager/*`；未改前端。**

## 2. changed files（content-only，3 个，+104/-16）
| 文件 | 改动 |
|------|------|
| `backend/app/config.py`（+4） | 新增 `coze_content_enabled / coze_content_workflow_id`（**仅读取，无真实值**） |
| `backend/app/coze_client.py`（+4） | 新增 `content_configured()`（复用已有 `run_workflow`） |
| `backend/app/routers/weapp.py`（+112/-16） | `/api/content/generate` async 化 + Workflow/降级分流 + 双兼容 flatten + 平台护栏软化 + 真实标签；`ContentGenerateRequest` 补 `target_customer` |

## 3. content 修复前后契约对比
| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 实现 | 硬编码模板 + flatten | `COZE_CONTENT_ENABLED=true` 且配置完整 → Coze Workflow；否则/任何失败 → 模板降级 |
| 前端契约 | `data.{title,content,suggestions[]}` | **不变** + 附 `source/confidence_label/degraded` |
| 标签 | 永远 `知识库+模型生成`（**假标**） | 真实：成功=`source:coze`/`扣子知识库+模型生成`/`degraded:false`；模板=`source:local_fallback`/`本地模板(降级)`/`degraded:true` |
| 结构兼容 | — | **双兼容**：优先 Coze 直返 `{title,content,suggestions}`；否则 flatten `hook/body/cta`(正文) + `image_suggestion/publish_time`(suggestions) |
| 护栏 | 无 | 医疗/夸大/绝对化/收益软化；平台差异由 Coze prompt 约束 |
| 健壮性 | — | `title`/`content` 始终可用、`suggestions` 缺给 `[]`、**不白屏、不 500** |

## 4. 测试摘要（11 PASS / 0 FAIL，见 TEST_OUTPUT.txt）
1. `COZE_CONTENT_ENABLED=false` → 模板降级、不假标、契约齐（title/content字符串含换行/suggestions[]）✅
2. enabled=true 但缺 token/workflow_id → 降级 ✅
3. Workflow 成功（直返）→ `source=coze`/`degraded=false`，三字段来自 Workflow ✅
4. **hook/body/cta flatten** 为正文 + `image/publish` → suggestions ✅
5. 命中"100%/根治/绝对/最有效/彻底/治愈/保证赚钱" → **软化** ✅
6. Workflow 无有效正文（空）→ 降级模板、不假标 ✅
7. Coze 异常 → 降级模板、不假标 ✅

## 5. 直返 / flatten 双兼容
- **优先**：Coze 直接返回 `{title, content(字符串), suggestions[]}` → 直接采用。
- **兼容**：Coze 返回分段 `{title, hook, body, cta, image_suggestion, publish_time}` → 后端 flatten：
  - `content = hook + "\n\n" + body + "\n\n" + cta`
  - `suggestions = [image_suggestion, publish_time]`（过滤空值）
- **无有效正文**（直返与分段都拼不出正文）→ 判无效 → 降级模板。

## 6. 软化 / 降级规则（绝对禁止项落地）
`_soften_content` 命中即替换（真实输出与降级输出都过）：
- **医疗化**：根治/治愈/治疗 → 调理改善/改善/调理。
- **功效夸大/绝对化**：100%/百分百/绝对/彻底/永久/特效/立竿见影/最有效/最好的/天下第一 → 大多数情况/通常/明显/长期/…。
- **违规收益**：保证赚钱/稳赚/包回本 → 帮助经营/有助于/辅助提升。
- 平台差异（朋友圈/小红书/抖音/视频号）由 Coze prompt 约束；后端硬护栏覆盖跨平台通用红线。无法软化（整段违规/空正文）→ 降级模板。

## 7. 模板降级标签真实化
任何模板/降级输出强制 `source=local_fallback`、`degraded=true`、`confidence_label=本地模板(降级)`、`confidence=low`、`quality_score=60`，**绝不标"知识库+模型生成"**。仅真实 Workflow 成功才 `source=coze`/`quality_score=88`。

## 8. 边界声明
- 未 merge main、未 push main、未部署、未 scp、未动 ECS/Nginx/SSL/安全组/18080/18081。
- 未改 chat/private 已通过行为；未迁 manager、未动 `/api/store-manager/*`；未碰真实 token/env。
- **Coze 未介入。**

## 9. Claude 开发线收口
- chat（`04bc8ba`，已审）→ private（`405f341`，已审）→ content（`1e6aabc`，本拍）= **3 接口 Coze 接入全部完成**。
- **本拍审过后，Claude 开发线到此为止**；后续按既定流程转入 **阿里 Qoder 精装修 → 扣子组织终审 → 再考虑发布**，**不再由 Claude 直接做最终合成/发布**。
- 代码合 main / 部署 / 开 `COZE_*_ENABLED` 灰度，均需后续单独授权（且按 chat→private→content 逐个开）。

## 10. 安全
本 patch 为 `405f341..1e6aabc` 的 **content 增量**；经扫描**无真实 token/密钥明文**；配置项默认空，真实值经环境变量注入。
