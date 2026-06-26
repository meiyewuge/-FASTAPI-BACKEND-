# V4 P2 · L4 — 技术设计

> **设计草案，不写业务代码、不建表、不改 staging、不部署。** API/JSON/DDL 均为草案。
> 现状基线（真实代码）：`services/compose_preview_service.py`、`services/director_prompt_engine.py`、`models/director_plan.py`、`models/cost_ledger.py`、`b_engine/remixer.py`、`services/reflow_service.py`、`services/orchestrator.submit_b_batch`、`services/b_service.py`。
> 安全：`ENABLE_COMPOSE=false` 保持；B 台零 API 成本；不触发火山；不引 OpenMontage 代码/AGPL；HyperFrames/Remotion 仅 sandbox 预留。

---

## A. 后端模块设计（新增 services）
| 模块 | 职责 | 引擎 |
|----|----|----|
| `production_order_service.py` | director_plan → production_order + shot_map（预览/落库/查询） | rule（+可选 LLM 辅助标注） |
| `director_layer_service.py` | 编导层：生产单 + shot_map → fission_plan（6 组排比矩阵 + 30 variants） | rule |
| `skill_registry_service.py` | 技能注册表 CRUD + 版本 + 启用态（super_admin 只读为主） | internal |
| `asset_pack_service.py` | 品牌素材包 CRUD（logo/产品图/卡片/BGM/合规） | internal |
| `fission_plan_service.py` | fission_plan 预览/执行编排（生成 variants、入队 B 任务） | rule |
| `qa_gate_service.py` | 质检门：duration/pts/playable/md5/相似度/品牌/字幕 | ffprobe/opencv/rule |
| `skill_executor.py` | 统一技能调度（按 skill_id 找实现，调 ffmpeg/ffprobe/opencv，记 skill_run） | ffmpeg/ffprobe/opencv |

> 分层：API → service（编排）→ skill_executor（执行）→ 底层工具（ffmpeg/ffprobe/opencv）。规则引擎做决策，LLM 只在 preview/标注辅助。

---

## B. 与现有模块关系（复用，不推翻）
| 现有 | P2 如何连接 |
|----|----|
| `director_plans`（P0-B） | production_order.director_plan_id 引用；shot_map 由 director_plan 的 storyboard + image_roles 映射 |
| `videos` | mother_video_ids 引用母视频；裂变产物仍写 `type=viral`（沿用 b_service 落库 + duration_seconds + expires_at 5天） |
| `cost_ledger`（P0-A） | B 台主路径不 precharge；qa_gate/skill_run 不计费；与 ledger 对账确保 B 台 cost=0 |
| `knowledge_candidates`（P0 回流） | QA pass + 高分内容 + 失败案例 → 经验候选（source_type=strategy/failure_case/workflow_summary） |
| `b_engine/remixer.py` | **P1.1 重写为 safe_trim_setpts + safe_concat 重编码**（见 E）；变 skill 实现被 skill_executor 调用 |
| `services/reflow_service.py` | fission 执行结束 → reflow.finalize；feedback → 候选池（已兼容 rating str|int） |
| `uploads` | asset_pack 的 logo/产品图/卡片引用 uploads.file_id；图片 HTTPS 校验沿用 `utils/image_url_check` |
| `admin_users`（Patch6） | 技能库/素材包治理 + 候选池审核 = super_admin；发码 = invite_admin；隔离不变 |

---

## C. 数据库设计（建议新表，草案 DDL）
> 全部带 `tenant_id` 隔离；`Base.metadata.create_all` 可自动建新表（实际建表待 P2 开发期）。
```sql
CREATE TABLE production_orders (
  production_order_id VARCHAR(40) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL,
  user_id VARCHAR(32), brand_id VARCHAR(40), product_id VARCHAR(40),
  scenario VARCHAR(24), platform VARCHAR(16), ratio VARCHAR(8), duration INTEGER,
  director_plan_id VARCHAR(40), mother_video_ids TEXT, asset_pack_id VARCHAR(40),
  skill_profile_id VARCHAR(40), fission_goal TEXT, qa_gates TEXT, cost_policy TEXT,
  status VARCHAR(16) DEFAULT 'preview', created_at DATETIME );
CREATE TABLE shot_maps (
  shot_id VARCHAR(48) PRIMARY KEY, production_order_id VARCHAR(40), tenant_id VARCHAR(64),
  source TEXT, role VARCHAR(12), start_time FLOAT, end_time FLOAT, text TEXT,
  visual_description TEXT, image_refs TEXT, confidence FLOAT, qa_notes TEXT );
CREATE TABLE fission_plans (
  fission_plan_id VARCHAR(40) PRIMARY KEY, production_order_id VARCHAR(40), tenant_id VARCHAR(64),
  source_video_ids TEXT, target_count INTEGER, groups TEXT, variants TEXT,
  required_skills TEXT, required_assets TEXT, qa_gates TEXT, status VARCHAR(16) DEFAULT 'preview',
  created_at DATETIME );
CREATE TABLE fission_variants (
  variant_id VARCHAR(48) PRIMARY KEY, fission_plan_id VARCHAR(40), tenant_id VARCHAR(64),
  group_type VARCHAR(24), center_idea TEXT, segment_plan TEXT, skill_sequence TEXT,
  asset_sequence TEXT, subtitle_plan TEXT, transition_plan TEXT, output_requirements TEXT,
  qa_expected TEXT, video_id INTEGER, status VARCHAR(16) DEFAULT 'planned' );
CREATE TABLE skill_registry (
  skill_id VARCHAR(48) PRIMARY KEY, name VARCHAR(64), category VARCHAR(16), engine VARCHAR(16),
  input_schema TEXT, output_schema TEXT, default_params TEXT, business_use TEXT,
  platform_fit TEXT, risk_level VARCHAR(8), qa_gates TEXT, fallback TEXT,
  version VARCHAR(8), enabled BOOLEAN DEFAULT 1, created_at DATETIME );
CREATE TABLE skill_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, skill_id VARCHAR(48), variant_id VARCHAR(48),
  tenant_id VARCHAR(64), params TEXT, status VARCHAR(16), input_ref TEXT, output_ref TEXT,
  duration_ms INTEGER, error TEXT, created_at DATETIME );
CREATE TABLE asset_packs (
  asset_pack_id VARCHAR(40) PRIMARY KEY, brand_id VARCHAR(40), tenant_id VARCHAR(64),
  brand_name VARCHAR(64), logo TEXT, brand_color TEXT, product_images TEXT, scene_images TEXT,
  intro_cards TEXT, outro_cards TEXT, text_card_templates TEXT, bgm TEXT, qr_assets TEXT,
  compliance_notes TEXT, status VARCHAR(16) DEFAULT 'active', created_at DATETIME );
CREATE TABLE qa_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER, production_order_id VARCHAR(40),
  variant_id VARCHAR(48), tenant_id VARCHAR(64), duration_ok BOOLEAN, pts_ok BOOLEAN,
  playable_ok BOOLEAN, md5_duplicate BOOLEAN, perceptual_similarity FLOAT, brand_presence BOOLEAN,
  subtitle_readability VARCHAR(8), platform_risk VARCHAR(8), final_status VARCHAR(8), qa_logs TEXT,
  created_at DATETIME );
```
> 回滚：还原 DB 备份；新表 `DROP TABLE`。不动现有表结构（P2 只新增表，与 P0/P1/P0-A/P0-B 既有表零冲突）。

---

## D. API 草案（require_auth；管理类 super_admin）
| 方法 | 路径 | 说明 |
|----|----|----|
| POST | `/api/production-orders/preview` | director_plan(+用途) → production_order + shot_map（**不调火山、不扣费**） |
| POST | `/api/production-orders` | 确认创建生产单（需 confirmed） |
| GET | `/api/production-orders/{id}` | 查生产单 + shot_map |
| POST | `/api/fission-plans/preview` | 生产单 → fission_plan(6 组/30 variants) 预览（0 成本） |
| POST | `/api/fission-plans/{id}/execute` | 执行裂变（入队 B 任务，0 成本，不调火山） |
| GET | `/api/fission-plans/{id}` | 裂变进度 + variants + video_ids |
| GET | `/api/skills` | 技能列表（super_admin 运维视角，只读） |
| GET | `/api/asset-packs` | 素材包列表 |
| POST | `/api/asset-packs` | 建/改素材包（super_admin） |
| GET | `/api/videos/{id}/qa` | 单条视频质检结果 |
> 兼容：现有 `POST /api/b/batch-generate`（P1）保留；P2 的 `fission-plans/execute` 是其「带计划/技能/素材/质检」的上层编排，底层仍走本地 ffmpeg。

---

## E. B 台 Remixer 修复设计（**P1.1，可立即进代码**）
**根因（Bug-2）**：`b_engine/remixer.py` 现用 `-f segment -c copy` 切片 + concat demuxer `-c copy`。`-c copy` 不重编码，切点落在非关键帧 → GOP/PTS 不规则 → 拼接后 PTS 非单调，部分播放器 14 秒后卡死、duration 异常。

**方案：废弃 `_slice()+_concat(-c copy)` 主流程，改重编码精确切 + 规范化拼接。**
```bash
# 1) safe_trim_setpts_v1：精确区间 + 重置 PTS（重编码，关键帧对齐）
ffmpeg -y -ss <in> -to <out> -i src.mp4 \
  -vf "setpts=PTS-STARTPTS,fps=30,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1" \
  -af "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 44100 -ac 2 -video_track_timescale 90000 seg_i.mp4
# 2) normalize_video_v1：统一参数（分辨率/帧率/SAR/采样率），保证可 concat
# 3) safe_concat_v1：用 concat demuxer 拼【已规范化且重编码】的等参片段（或 filter_complex concat）
ffmpeg -y -f concat -safe 0 -i list.txt -c:v libx264 -preset veryfast -pix_fmt yuv420p \
  -r 30 -c:a aac -movflags +faststart -t <target 90-120> out.mp4
#   或片段差异较大时用 filter_complex：
#   -filter_complex "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]" -map "[v]" -map "[a]"
# 4) playback_validate_v1：解码到结尾校验
ffmpeg -v error -i out.mp4 -f null -    # 无输出=可完整解码；有 error=不可播放
ffprobe -v error -select_streams v -show_entries frame=pkt_pts_time -of csv out.mp4  # 校验 PTS 单调
```
**保证项**：PTS 单调 ✅ / 可播放到结尾 ✅ / duration 正常(目标 90–120s) ✅ / 重编码统一参数提升差异化兼容 ✅ / **cost=0**（本地 ffmpeg）✅ / 不调火山 ✅。
**取舍**：重编码增加 CPU/耗时——P1.1 先保正确性，性能用 `preset veryfast` + 受控并发；`-c copy` 仅在「单源单段不拼接」时作快速路径，**多段拼接一律重编码**。
> P1.1 可独立于 P2 全套先交付（只动 remixer + 加 duration/pts/playable/md5 质检），不依赖 production_order/fission_plan。

---

## F. 质检方案（qa_gate_service）
| gate | 实现 | 类型 |
|----|----|----|
| `duration_check` | ffprobe format=duration，在 [90,120]±容差 | hard |
| `pts_check` | ffprobe 帧 pkt_pts_time 单调递增 | hard |
| `playback_validate` | `ffmpeg -v error -i x -f null -` 无 error | hard |
| `md5_duplicate_check` | 文件 md5，同 batch 唯一 | hard（重复→重做） |
| `perceptual_hash_check` | OpenCV 抽关键帧 pHash，汉明距离/相似度阈值 | soft（P2，重算法可延后 P3） |
| `brand_presence_check` | 有 asset_pack 时校验 logo/品牌字幕出现（规则+可选模板匹配） | soft |
| `subtitle_readability_check` | 字幕区域对比度/字号规则 | soft |
> hard fail → `final_status=fail`，该条不入 viral 陈列、标重做；soft 不达标 → `warn`（入列+提示）。

---

## G. 安全边界（硬约束）
- `ENABLE_COMPOSE=false` 保持；A 台真实生成仍锁（解锁需 7 条件 + 人工确认）。
- 不触发火山；B 台主路径**零 API 成本**（与 cost_ledger 对账：B 链路无 precharge）。
- 不碰 production；不改现有 staging；不直接部署；不大文件压测；不做 Seedance 2.5。
- **不引入 OpenMontage 代码**（仅学习 pipeline manifest 思想）；**不引 AGPL 依赖**。
- **HyperFrames / Remotion 仅 sandbox 预留**（P3），不接 production。
- 所有 P2 接口 tenant 隔离；管理类 super_admin；图片走 `image_url_check`（HTTPS）。

---

## H. 第一版技能库（skill_registry v1，12 个核心技能）
| # | skill_id | category | engine | 用途 |
|---|----|----|----|----|
| 1 | `probe_video_v1` | probe | ffprobe | 探测时长/帧率/分辨率/关键帧（切点决策） |
| 2 | `safe_trim_setpts_v1` | video_edit | ffmpeg | 精确切片 + setpts 重置 + 重编码（替 -c copy） |
| 3 | `normalize_video_v1` | video_edit | ffmpeg | 统一分辨率/帧率/SAR/采样率（可 concat） |
| 4 | `safe_concat_v1` | video_edit | ffmpeg | 规范化片段重编码拼接（PTS 单调） |
| 5 | `playback_validate_v1` | qa | ffmpeg | 解码到结尾校验 + PTS 校验 |
| 6 | `shot_role_labeler_v1` | label | rule | 镜头打角色（pain/product/solution/result/brand/cta） |
| 7 | `mother_segment_mapper_v1` | plan | rule | 母视频时间轴 ↔ 导演稿 ↔ 片段映射（生成 shot_map） |
| 8 | `fission_strategy_planner_v1` | plan | rule | 6 组排比矩阵 → 30 variants 施工单 |
| 9 | `text_card_insert_v1` | overlay | ffmpeg | 插文字卡（痛点钩子/卖点/CTA） |
| 10 | `product_image_insert_v1` | overlay | ffmpeg | 插产品特写图卡 |
| 11 | `subtitle_brand_style_v1` | overlay | ffmpeg | 品牌风格字幕（drawtext，CJK 字体） |
| 12 | `md5_duplicate_check_v1` | qa | internal | 同批 MD5 去重 |

**增强技能（后续预留）**：`brand_title_card_v1`、`brand_outro_card_v1`、`bgm_mix_v1`、`color_tone_variation_v1`、`motion_variation_v1`、`perceptual_hash_check_v1`、`template_render_card_v1`、`qr_code_card_v1`、`case_compare_card_v1`。

---

## I. 达芙荻丽 `DFD_ASSET_PACK_V1`（冷启动示例）
```json
{
  "asset_pack_id": "ap_dfd_v1", "brand_id": "brand_dfd", "brand_name": "达芙荻丽",
  "logo": {"file_id": "<上传 logo png 透明底>", "safe_zone": "bottom_right"},
  "brand_color": {"primary": "#1E4D5B", "accent": "#C8A96A"},
  "product_images": [ {"role":"product_front"}, {"role":"bottle_detail"}, {"role":"oil_drop"} ],
  "scene_images": [ {"role":"usage_face"} ],
  "intro_cards": [ {"template_id":"intro_premium","text":"达芙荻丽奢华油"} ],
  "outro_cards": [ {"template_id":"outro_brand","text":"以油养肤之美"} ],
  "text_card_templates": [
    {"id":"pain_hook","layout":"center_big","max_chars":14},
    {"id":"selling_point","layout":"bottom_strip","max_chars":18}
  ],
  "bgm": [ {"id":"bgm_premium_1","license":"owned","loudness_lufs":-16} ],
  "qr_assets": [ {"role":"cta_qr"} ],
  "compliance_notes": "禁医疗功效虚假宣传；禁绝对化用语；BGM 自有版权"
}
```
冷启动只需：logo 1 张 + 产品图 3 张 + 2 个文字卡模板 + 1 段自有 BGM + 品牌色，即可驱动 12 技能产出带品牌的 30 条。

---

## J. HyperFrames / Remotion 模板渲染层预留（P3，仅 sandbox）
- 预留 `template_render_card_v1` 技能位（engine=`template`），P3 在**独立 sandbox 服务**渲染高级卡片/转场，产出 mp4 片段回流给 `safe_concat_v1`。
- **不引入其代码到 production**；接口契约（输入模板 id + 变量 → 输出片段 path）先在 skill_registry 占位，许可与依赖审查通过后再评估。
