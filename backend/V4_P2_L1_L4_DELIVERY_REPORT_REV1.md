# V4 P2 · L1–L4 设计包 交付报告（Rev1）

> Rev1 小修定稿（取代原交付报告）。**仍纯设计，未写代码、未改 production、未解锁 compose、未触发火山、未部署。** 供 ChatGPT 复审。

## 0. 本次输出（Rev1 六文件）
| 层 | 文件 |
|----|----|
| L1 | `V4_P2_L1_PRD_VIDEO_PRODUCTION_CENTER_REV1.md` |
| L2 | `V4_P2_L2_CLICKABLE_PROTOTYPE_REV1.html` |
| L2.3 | `V4_P2_L2_3_DATA_CONTRACT_AND_MANIFEST_SPEC_REV1.md` |
| L3 | `V4_P2_L3_INTERACTION_SPEC_REV1.md` |
| L4 | `V4_P2_L4_TECHNICAL_DESIGN_REV1.md` |
| 报告 | `V4_P2_L1_L4_DELIVERY_REPORT_REV1.md`（本文件） |

## 1. 本次修改点（对照 ChatGPT 6 项 + 吴哥素材拍板）

### 1.1 时长口径统一为短视频（最高优先级）✅
全包统一：A台 preview 估价仍按 15s 说明（compose 锁）；**A台母视频目标 27–30s**；B台合格源 `>=30s`；**B台裂变输出 `target_seconds=[25,35]`**；**`duration_check=[25,35]`**；P1.1 目标=30 秒级短视频不卡死/不重复/可播放到结尾；**90–120s 移到 P3**。
- 已同步修改：L1 成功指标、L2.3 `fission_variant.output_requirements`+`qa_result.duration_ok` 注释、L3 裂变计划说明、L4 Remixer P1.1 示例 + `safe_concat` target + `duration_check`、本报告 P1.1 说明、L2 原型标签。

### 1.2 P1.1 / P2 边界拆清 ✅
- **P1.1（止血，允许）**：仅改 `b_engine/remixer.py` + 封装最小 QA（duration[25,35]/pts/playable/md5）。**禁止**新增 P2 大表、改前端主流程、模板渲染、HyperFrames/Remotion、调火山；cost=0、ENABLE_COMPOSE=false。
- **P2（设计通过后）**：production_order/shot_map/fission_plan/fission_variant/skill_registry/asset_pack/qa_result + production_assets/brand_pack 实现 + free_stock 占位 + paid 流程设计 + fission_plan preview + 用户侧页面。
- 写入 L4 §E 与本报告。

### 1.3 skill_executor 安全边界补充 ✅（L4 §D）
- **skill_registry DB 绝不存可执行 shell/ffmpeg 命令**；只存 adapter 名 + default_params + 元数据。
- 执行链：skill_id 白名单 → Python adapter → 代码固定 ffmpeg 参数模板 → params schema 校验 → 路径白名单(storage-staging) → subprocess 参数列表(非 shell)。禁任意路径读写、禁 shell 注入。

### 1.4 素材权限分层 ✅
- **production_assets**：用户本次上传，仅绑当前生产单，普通用户可传。
- **brand_asset_pack**：品牌长期可复用包，super_admin/授权管理员管理。
- L2/L3/L4/L2.3 均区分，不再混为一谈。

### 1.5 QA fail 重做 / partial_done ✅
- 单条 hard gate fail → 自动重做 ≤`max_retry`(默认 2)；仍失败 → `final_status=failed`，不入列、标重做、不建议下载。
- batch `partial_done`（如 28 pass / 2 failed，不拖死整批）；前端「N 条可用，M 条需重做」。soft warn 可展示提示风险。
- 写入 L2.3 §K、L3 §6、L4 §F、`fission_variant.retry_count/max_retry`、`qa_result.retry_count/final_status`。

### 1.6 API 语义小修 ✅（L4 §H）
- `POST /api/production-orders/preview` 不再写「内含 compose/preview」。改为：有 director_plan_id → 读取生成生产单 preview；无 → 可经现有 A台 preview 流程获 director_plan，但**仍不触发真实 compose、不扣费**；**明确本接口不触发火山**。

### 1.7 素材供应网关（Asset Supply Gateway）— 吴哥拍板，并入 Rev1 ✅
- 素材四层：**production_assets / brand_asset_pack / free_stock_gateway(Pexels/Pixabay/Unsplash) / paid_stock_gateway(Adobe/Shutterstock/Getty/Storyblocks)**。
- **免费优先**（默认）；**付费外部跳转、用户自购自传、不走平台账/token/cost_ledger、平台不垫资不代购不收银**。
- 前端新增「素材增强」三选项（仅我上传/优先免费/允许付费推荐，默认免费）+ 付费预算/人工确认 + 跳转文案；裂变计划展示**素材构成 + 预计成本**。
- 数据契约新增：`asset_policy`、`asset_source`、`external_asset_candidate`、`paid_user_uploaded_asset`、`asset_license_ledger`、`production_assets`（L2.3）。
- 后端新增（设计）：`asset_source_service/asset_search_service/asset_ranker_service(beauty_asset_ranker)/asset_license_service/external_asset_gateway` + 7 个 provider adapter **占位**。
- QA 新增：`license_check`（来源/授权/商用/attribution/付费已授权/license_id/缓存/二次加工/敏感）、`license_claim_check`（付费素材用户上传+授权确认+绑单+未走平台代购）。
- 分期：**P2** 设计 Asset Supply Layer + production_assets/brand_pack 实现 + free_stock adapter 占位 + paid 预算/授权流程设计（不接真实付费 API）+ license_check 结构；**P3** 真实接入 + 真实授权台账 + 自动推荐；**P4** 分佣/批发商商业化。

## 2. 必答确认项（逐条）
1. **时长口径已统一为 [25,35] 短视频裂变** ✅
2. **90–120 秒已移到 P3** ✅
3. **P1.1 / P2 边界已拆清** ✅（L4 §E + 本报告 §1.2）
4. **skill_executor 安全边界已补充** ✅（L4 §D，DB 不存命令 + 白名单 adapter + 校验 + 路径白名单）
5. **production_assets / asset_pack 权限已分层** ✅
6. **QA fail 重做 / partial_done 已补充** ✅
7. **素材供应网关（免费优先 + 付费外部跳转不走平台账）已并入** ✅
8. **是否仍纯设计、未写代码、未部署、未触发火山、未碰 production** ✅ 是

## 3. 仍需 ChatGPT 复审/拍板
1. 7+5 个 JSON 契约字段/枚举是否定稿（含 asset_policy / external_asset_candidate / asset_license_ledger）。
2. P1.1 是否先单独发（清 Bug-2 短视频）再做 P2。
3. 短视频默认区间是否就用 [25,35]（不同平台是否要差异）。
4. license_check 哪些设 hard（建议：来源/商用/付费授权/license_id 为 hard）。
5. 免费素材 adapter 占位的最小可演示形态（mock vs 真接）。
6. paid 预算字段是否要在 P2 就持久化（还是纯前端约束）。

## 4. 风险清单
| 风险 | 等级 | 缓解 |
|----|----|----|
| 时长误写长视频 | 已消除 | Rev1 全包 [25,35]，90–120 标 P3 |
| skill 命令注入 | 高→低 | DB 不存命令 + adapter 白名单 + 路径白名单 + 非 shell |
| 付费素材版权/财务 | 高→中 | 外部跳转自购自传 + license_claim_check + 平台不走账 |
| 免费素材同质化/合规 | 中 | beauty_asset_ranker + 二次品牌化 |
| QA fail 拖死 batch | 已消除 | 重做≤2 + partial_done |
| 第三方许可 | 高 | 不引 OpenMontage/AGPL；HyperFrames/Remotion 仅 sandbox；本轮不接真实素材 API |

## 5. 下一步建议
1. ChatGPT 复审 Rev1（重点：短视频口径、skill 安全、素材网关付费铁律、QA partial）。
2. 通过后**优先发 P1.1**（短视频 Remixer PTS 修复 + 最小 QA），清线上 Bug-2。
3. 再分批做 P2 MVP（先生产单/裂变计划 preview + production_assets/brand_pack，后 free_stock 占位 + paid 流程设计）。
4. 真实素材接入与购买授权、长视频、商业化分别放 P3/P4。

## 6. 约束遵守自查
- ✅ 仅设计文档 + 可点击原型；未写业务代码
- ✅ 未改 production / 未解锁 ENABLE_COMPOSE / 未触发火山 / 未部署 / 未改 staging
- ✅ 未接真实素材 API / 未接任何素材支付 / 未购买素材
- ✅ 未引 OpenMontage 代码 / AGPL；HyperFrames/Remotion 仅 sandbox
- ✅ 所有 API/JSON/DDL 标注草案，不得直接执行；与 P0/P1/P0-A/P0-B 不冲突
