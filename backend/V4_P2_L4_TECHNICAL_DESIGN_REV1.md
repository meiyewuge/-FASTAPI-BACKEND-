# V4 P2 · L4（Rev1）— 技术设计

> Rev1（取代原 L4）。**草案，不写代码/不建表/不改 staging/不部署。** 主修：短视频时长口径、P1.1/P2 边界、skill_executor 安全边界、素材权限分层、QA 重做/partial、API 语义、**Asset Supply Gateway**。
> 安全：`ENABLE_COMPOSE=false` 保持；B 台零平台 API 成本；不触发火山；付费素材不走平台账；不引 OpenMontage 代码/AGPL；HyperFrames/Remotion 仅 sandbox；**本轮不接真实素材 API、不接素材支付**。

---

## 0. 统一时长口径（全文一致）
- A台母视频目标(P2)：**27–30s**；A台 preview 估价：按 15s 说明（compose 锁住）。
- B台合格源：`duration_seconds>=30`。
- **B台裂变输出默认 `target_seconds=[25,35]`；`duration_check=[25,35]`±容差。**
- 90–120s 长视频 → **P3**，不在 P1.1/P2。

---

## A. 后端模块（新增 services）
| 模块 | 职责 |
|----|----|
| `production_order_service.py` | director_plan → production_order + shot_map（preview/落库/查询，**不调火山**） |
| `director_layer_service.py` | 生产单+shot_map → fission_plan（6 组×5=30 短视频 variants） |
| `skill_registry_service.py` | 技能注册表 CRUD + 版本/启用（super_admin 只读为主） |
| `skill_executor.py` | **白名单 adapter 调度**（见 D 安全边界） |
| `fission_plan_service.py` | 裂变计划 preview/execute；QA 重做/partial 编排 |
| `qa_gate_service.py` | duration/pts/playable/md5/相似/品牌/字幕/**license_check/license_claim_check** |
| **`asset_source_service.py`** | 素材源注册/启用（user_upload/brand_pack/free_stock/paid_stock） |
| **`asset_search_service.py`** | 统一检索（先 production_assets/brand_pack，再 free_stock 占位） |
| **`asset_ranker_service.py`** | `beauty_asset_ranker`（美业/品牌/平台/画质/版权风险评分） |
| **`asset_license_service.py`** | 授权台账 asset_license_ledger 读写；license/license_claim 校验 |
| **`external_asset_gateway.py`** | 素材供应网关：找/筛/推荐/跳转/记录（**不付款/不代购/不平台扣费**） |

**Provider adapters（本轮仅占位接口，不接真实 API）**：`pexels_adapter.py`、`pixabay_adapter.py`、`unsplash_adapter.py`、`adobe_stock_adapter.py`、`shutterstock_adapter.py`、`getty_adapter.py`、`storyblocks_adapter.py`。

---

## B. 与现有模块关系（复用，零冲突）
| 现有 | 连接 |
|----|----|
| `director_plans`(P0-B) | production_order.director_plan_id 引用 |
| `videos` | 裂变产物写 type=viral（沿用 b_service + duration_seconds + expires_at 5天） |
| `cost_ledger`(P0-A) | B 台主路径不 precharge；**付费素材不写 cost_ledger**（外部支付） |
| `knowledge_candidates`(回流) | QA pass/高分→strategy 候选；fail→failure_case |
| `b_engine/remixer.py` | **P1.1 重写短视频 safe_trim_setpts+safe_concat 重编码**；变 adapter 被 skill_executor 调 |
| `reflow_service` | execute 结束 finalize；feedback→候选池（rating str\|int 已兼容） |
| `uploads` | production_assets / brand_pack / paid_user_uploaded 引用 uploads.file_id；图片 HTTPS 校验沿用 image_url_check |
| `admin_users`(Patch6) | 技能/品牌素材包治理 + 候选池 = super_admin；隔离不变 |

---

## C. 数据库（建议新表，草案 DDL；本轮不建）
P2 新表：`production_orders`、`shot_maps`、`fission_plans`、`fission_variants`、`skill_registry`、`skill_runs`、`asset_packs`、`qa_results`（DDL 见原 L4），Rev1 **追加**：
```sql
CREATE TABLE production_assets (              -- 用户本次上传素材（普通用户可传）
  production_asset_id VARCHAR(40) PRIMARY KEY, production_order_id VARCHAR(40), tenant_id VARCHAR(64),
  user_id VARCHAR(32), file_id VARCHAR(40), type VARCHAR(8), usage_scope VARCHAR(32),
  source_type VARCHAR(24) DEFAULT 'user_upload', created_at DATETIME );
CREATE TABLE asset_sources (                  -- 素材源注册
  source_id VARCHAR(40) PRIMARY KEY, provider VARCHAR(24), source_type VARCHAR(16),
  api_adapter VARCHAR(48), enabled BOOLEAN DEFAULT 1, auth_required BOOLEAN,
  attribution_required_default BOOLEAN, commercial_use_default BOOLEAN,
  cache_policy VARCHAR(32), license_policy VARCHAR(32), risk_level VARCHAR(8) );
CREATE TABLE external_asset_candidates (      -- 外部素材候选（检索缓存/记录，按授权决定可否缓存）
  external_asset_id VARCHAR(64), provider VARCHAR(24), tenant_id VARCHAR(64), type VARCHAR(8),
  title TEXT, preview_url TEXT, thumbnail_url TEXT, source_url TEXT, duration FLOAT, ratio VARCHAR(8),
  tags TEXT, creator VARCHAR(128), license_type VARCHAR(24), attribution_required BOOLEAN,
  commercial_use BOOLEAN, cost FLOAT, currency VARCHAR(8), license_required BOOLEAN,
  license_status VARCHAR(24), official_purchase_url TEXT, payment_flow VARCHAR(24),
  platform_billing BOOLEAN DEFAULT 0, token_cost FLOAT DEFAULT 0,
  requires_user_upload_after_purchase BOOLEAN, beauty_fit_score FLOAT, brand_fit_score FLOAT,
  platform_fit_score FLOAT, quality_score FLOAT, license_risk_score FLOAT, final_score FLOAT,
  risk_level VARCHAR(8), created_at DATETIME, PRIMARY KEY (external_asset_id, provider, tenant_id) );
CREATE TABLE asset_license_ledger (           -- 授权台账（风控核心）
  ledger_id VARCHAR(40) PRIMARY KEY, production_order_id VARCHAR(40), tenant_id VARCHAR(64),
  asset_id VARCHAR(64), provider VARCHAR(24), external_asset_id VARCHAR(64), source_type VARCHAR(24),
  license_type VARCHAR(24), license_status VARCHAR(24), license_id VARCHAR(64), license_price FLOAT,
  currency VARCHAR(8), attribution_text TEXT, attribution_url TEXT, commercial_use BOOLEAN,
  cache_allowed BOOLEAN, transform_allowed BOOLEAN, purchased_by VARCHAR(32), purchased_at DATETIME,
  usage_scope VARCHAR(32), user_confirmation_text TEXT, confirmed_at DATETIME, created_at DATETIME );
```
> 回滚：还原 DB 备份 / DROP 新表。**只新增表，零改现有 schema。**

---

## D. Skill Executor 安全边界（★ Rev1 铁律）
**`skill_registry` 数据库绝不保存可执行 shell/ffmpeg 命令。** 执行链：
```
skill_executor.run(skill_id, params)
  1. skill_id ∈ 白名单（代码内 SKILL_ADAPTERS 映射，DB 未注册/未启用 → 拒绝）
  2. 找到对应 Python adapter（如 safe_trim_setpts_adapter），DB 只提供 default_params + 元数据
  3. params 按 input_schema 做 schema 校验（类型/范围/枚举），非法即拒
  4. adapter 内用【代码固定的 ffmpeg 参数模板】拼命令，变量仅来自校验后的 params
  5. 路径白名单：输入/输出必须在 storage-staging（或正式安全目录）内；禁止 .. / 绝对越界 / 任意路径
  6. subprocess 以参数列表方式调用（非 shell=True），杜绝 shell 注入
  7. 记 skill_runs（params/status/耗时/error），失败按 fallback 回退
```
- **允许**：`skill_executor.run("safe_trim_setpts_v1", {...})`。
- **禁止**：从 DB 读取整条 ffmpeg 命令直接执行；shell 字符串拼接；任意路径读写。

---

## E. B 台 Remixer 修复（**P1.1，短视频，可立即进代码**）
**根因（Bug-2）**：旧 `-c copy -f segment` 切 + `-c copy` concat → 非关键帧切点 → PTS 非单调 → 30 秒视频 14 秒后卡死/duration 异常。
**方案**：重编码精确切 + 规范化拼接，**目标短视频 [25,35]**。
```bash
# 1) safe_trim_setpts_v1：精确切 + 重置 PTS（重编码）
ffmpeg -y -ss <in> -to <out> -i src.mp4 \
  -vf "setpts=PTS-STARTPTS,fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1" \
  -af "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 -c:a aac -ar 44100 -ac 2 \
  -video_track_timescale 90000 seg_i.mp4
# 2) normalize_video_v1：统一 1080x1920/30fps/SAR/采样率（可 concat）
# 3) safe_concat_v1：拼【规范化重编码】等参片段，目标短视频 25-35 秒
ffmpeg -y -f concat -safe 0 -i list.txt -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 \
  -c:a aac -movflags +faststart -t <target 25-35> out.mp4
#   片段差异大时用 filter_complex concat（n 段 v=1 a=1）
# 4) playback_validate_v1：解码到结尾 + PTS 单调
ffmpeg -v error -i out.mp4 -f null -            # 无 error=可完整解码
ffprobe -v error -select_streams v -show_entries frame=pkt_pts_time -of csv out.mp4
```
**保证**：PTS 单调 ✅ / 可播放到结尾 ✅ / **duration∈[25,35]** ✅ / 提升差异化兼容 ✅ / cost=0 ✅ / 不调火山 ✅。
> 性能：preset veryfast + 受控并发；P1.1 先正确后性能。**多段拼接一律重编码**；单源单段不拼可走 `-c copy` 快路径。

### P1.1 / P2 边界（强约束）
**P1.1（仅止血，允许）**：改 `b_engine/remixer.py`；封装最小 QA（`duration_check[25,35]`/`pts_check`/`playback_validate`/`md5_duplicate_check`）。
**P1.1 禁止**：新增 production_order/shot_map/fission_plan/skill_registry/asset_pack/qa_result 等 P2 表；改前端主流程；模板渲染；HyperFrames/Remotion；调火山。**cost=0、ENABLE_COMPOSE=false 保持。**
**P2（设计通过后）**：上述全套 + production_assets/brand_asset_pack 实现 + free_stock adapter 占位 + paid 预算/授权流程设计（不接真实付费 API）+ license_check 结构 + fission_plan preview + 用户侧页面。

---

## F. 质检方案（qa_gate_service）
| gate | 实现 | 类型 |
|----|----|----|
| `duration_check` | ffprobe，**在 [25,35]±容差** | hard |
| `pts_check` | ffprobe 帧 PTS 单调 | hard |
| `playback_validate` | `ffmpeg -v error -f null -` 无 error | hard |
| `md5_duplicate_check` | 文件 md5 同 batch 唯一 | hard |
| `license_check`（★Rev1） | 素材有来源/授权类型/允许商用/attribution 记录/付费已授权/license_id/缓存与二次加工许可/敏感风险 | hard（不过 → 素材不得进成片） |
| `license_claim_check`（★Rev1） | 付费素材由用户上传 + 勾选合法授权 + 记 provider/原始 url + 绑当前单 + 未走平台代购 | hard（付费素材） |
| `perceptual_hash_check` | OpenCV 抽帧 pHash 相似度（P2 起，重算法可延 P3） | soft |
| `brand_presence_check` | logo/品牌字幕出现 | soft |
| `subtitle_readability_check` | 字幕对比度/字号规则 | soft |
**重做/partial（★Rev1）**：hard fail → 自动重做 ≤`max_retry`(默认 2)；仍失败 → `final_status=failed`，不入列、标重做；batch `partial_done`（如 28 pass / 2 failed，不拖死）。

---

## G. 素材供应网关（Asset Supply Gateway）— ★ Rev1
四源统一经 `external_asset_gateway`：找/筛/推荐/跳转/记录。**不付款/不代购/不平台扣费/不走 cost_ledger。**
- **production_assets**：用户本次上传（普通用户）。
- **brand_asset_pack**：品牌长期包（super_admin/授权管理员）。
- **free_stock_gateway**：Pexels/Pixabay/Unsplash adapter（**本轮占位**），默认优先，记录 provider/creator/source_url/license_type/attribution/commercial/cache。
- **paid_stock_gateway**：Adobe/Shutterstock/Getty/Storyblocks adapter（**本轮占位**），仅搜索预览 + 官方购买**跳转**；`payment_flow=external_redirect`、`platform_billing=false`、`token_cost=0`；用户自购自传 → `paid_user_uploaded_asset` + 授权确认。
**beauty_asset_ranker**：`beauty_fit/brand_fit/platform_fit/quality/license_risk → final_score`，免费素材二次品牌化加工（裁切/调色/品牌卡/产品图/片尾/字幕/与母视频重组），避免低质泛化。

**付费铁律（写入 L1/L2.3/L3/L4）**：
- 不做素材代购 / 收银台；不代购 Adobe/Shutterstock/Getty 等。
- 不从平台 token / cost_ledger / 吴哥账户扣素材费；不接付费素材购买 API；不保存外部平台支付信息；不承诺替用户完成授权。
- 用户自购、自下、自传、自确认；平台只记录使用声明与素材来源。

---

## H. API 草案（require_auth；管理类 super_admin）
| 方法 | 路径 | 说明 |
|----|----|----|
| POST | `/api/production-orders/preview` | **若已有 director_plan_id → 读取 director_plan 生成生产单 preview；若无 → 可经现有 A台 preview 流程获得 director_plan，但仍不触发真实 compose、不扣费。明确：本接口不触发火山。** |
| POST | `/api/production-orders` | 确认创建生产单 |
| GET | `/api/production-orders/{id}` | 查生产单 + shot_map |
| POST | `/api/fission-plans/preview` | 生产单 → fission_plan(6 组/30 短视频 variants + 素材构成) 预览（0 成本） |
| POST | `/api/fission-plans/{id}/execute` | 执行（入队 B 任务，0 平台成本，不调火山，QA 重做/partial） |
| GET | `/api/fission-plans/{id}` | 进度 + variants + video_ids + partial 状态 |
| GET | `/api/skills` | 技能列表（super_admin 只读） |
| GET | `/api/asset-packs` · POST | 品牌素材包（POST 仅 super_admin/授权管理员） |
| GET | `/api/asset-sources` | 素材源启用态/授权策略 |
| POST | `/api/assets/search` | 经 gateway 检索免费/付费候选（**本轮返回 mock/占位，不接真实 API**） |
| GET | `/api/videos/{id}/qa` | 质检结果 |
> 兼容：现有 `POST /api/b/batch-generate`(P1) 保留；P2 的 `fission-plans/execute` 是其「带计划/技能/素材/质检」的上层编排，底层仍本地 ffmpeg。

---

## I. 安全边界（硬约束汇总）
- `ENABLE_COMPOSE=false` 保持；不触发火山；不碰 production；不改 staging；不部署；不大文件压测；不做 Seedance 2.5。
- **skill_registry 不存可执行命令**（白名单 adapter + 固定模板 + schema 校验 + 路径白名单 + 非 shell 执行）。
- B 台零平台 API 成本；**付费素材外部支付、不走平台账/token/cost_ledger**；不接真实素材 API/支付。
- 不引 OpenMontage 代码/AGPL；HyperFrames/Remotion 仅 sandbox（P3）。
- 不绕过用户确认购买付费素材；无 license_id 不得使用付费素材；来源不明素材不得进成片；外部素材不得当自有素材售卖；未授权不得用于模型训练。

---

## J. 技能库 v1（12 核心，adapter 化）
`probe_video_v1`/`safe_trim_setpts_v1`/`normalize_video_v1`/`safe_concat_v1`/`playback_validate_v1`/`shot_role_labeler_v1`/`mother_segment_mapper_v1`/`fission_strategy_planner_v1`/`text_card_insert_v1`/`product_image_insert_v1`/`subtitle_brand_style_v1`/`md5_duplicate_check_v1`。
增强预留：`brand_title_card_v1`/`brand_outro_card_v1`/`bgm_mix_v1`/`color_tone_variation_v1`/`motion_variation_v1`/`perceptual_hash_check_v1`/`template_render_card_v1`/`qr_code_card_v1`/`case_compare_card_v1`、以及素材类 `stock_fetch_v1`/`beauty_asset_ranker_v1`/`license_claim_v1`。

## K. 分期
- **P2**：Asset Supply Layer 设计落地；production_assets + brand_asset_pack 实现；free_stock adapter **占位**；paid 预算/授权流程**设计**（不接真实付费 API）；license_check 结构预留。
- **P3**：真实接 Pexels/Pixabay/Unsplash + Adobe/Shutterstock/Getty/Storyblocks；真实购买授权与 license ledger；自动素材推荐 + 成本台账；感知哈希；**90–120s 长视频/课程切片**；HyperFrames/Remotion sandbox。
- **P4（商业化）**：Affiliate/CPS 分佣、企业批量采购、素材会员包、批发商模式。
