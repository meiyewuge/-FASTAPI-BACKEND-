# V4 P2 · L2.3 — 数据契约 & 生产单规范（Manifest Spec）

> **本轮最重要的中间层文档**。定义 A台↔B台 之间的统一数据契约（JSON 草案，**不得直接执行**）。
> 设计原则：B 台只认 `production_order + shot_map + fission_plan + fission_variant`，不再盲切 mp4。
> 所有结构均 tenant 隔离；时间单位秒（float）；id 用字符串（uuid hex）除非另注。

---

## 总览：数据如何串起来
```
director_plan(已有, A台 P0-B)
   │  director→manifest 映射
   ▼
production_order ──1:1── shot_map[]        （生产单 + 镜头角色地图）
   │
   ▼
fission_plan ──1:N── fission_variant[]      （裂变计划 + 每条施工单）
   │ 引用                      │ 引用
   ▼                          ▼
skill_registry[]            asset_pack
   │ 执行                      │ 注入
   ▼                          ▼
B台 Remixer 施工 → videos(type=viral) ──1:1── qa_result
   │
   ▼
reflow / knowledge_candidates（经验回流）
```

---

## A. `production_order`（生产单）
A 台导演意图 + 用户用途 → 一张可执行生产单。**这是 B 台不再盲切的关键**。
```json
{
  "production_order_id": "po_4f3a...",
  "tenant_id": "t_138...",
  "user_id": "13800000000",                // = phone
  "brand_id": "brand_dfd",                 // 可空（无品牌时纯片段）
  "product_id": "prod_dfd_oil",            // 可空
  "scenario": "product_seeding",           // product_seeding|store_event|customer_case|expert_science|live_clip|investment
  "platform": "douyin",                    // douyin|xiaohongshu|shipinhao|generic
  "ratio": "9:16",
  "duration": 15,                          // 母视频目标时长(秒)
  "director_plan_id": "dp_9c1...",         // 来自 A台 /compose/preview（已有 director_plans 表）
  "mother_video_ids": [1201],              // 绑定/生成的母视频（videos.id）；可多条作源池
  "asset_pack_id": "ap_dfd_v1",            // 品牌素材包；可空
  "skill_profile_id": "sp_seeding_v1",     // 技能档（场景→默认技能序列）
  "fission_goal": { "target_count": 30, "ratio_per_source": 10, "max_outputs": 50 },
  "qa_gates": ["duration_check","pts_check","playback_validate","md5_duplicate_check","brand_presence_check"],
  "cost_policy": { "b_track_api_cost": 0, "allow_llm_assist": false, "compose_locked": true },
  "status": "preview",                     // preview|confirmed|generating|done|failed
  "created_at": "2026-06-26T00:00:00Z"
}
```
> `cost_policy.b_track_api_cost=0` 是硬约束：B 台主路径零 API 成本。`compose_locked=true` 反映 `ENABLE_COMPOSE=false`。

---

## B. `shot_map`（镜头角色地图）
把 **时间轴 ↔ 导演稿 ↔ 视频片段** 三者对齐。一个母视频 → 多条 shot。
```json
{
  "shot_id": "shot_po4f3a_01",
  "production_order_id": "po_4f3a...",
  "source": { "video_id": 1201, "kind": "mother" },   // 来源母视频
  "role": "pain",                          // pain|product|solution|result|brand|cta
  "start_time": 0.0,
  "end_time": 4.0,
  "text": "夏季干皮上妆卡粉的困扰",          // 该段台词/字幕（来自 director_plan 分镜 line）
  "visual_description": "女性面部干皮特写，低对比度暖自然光侧面照射",  // 来自 storyboard description
  "image_refs": [                          // 绑定的图片角色（来自 director_plan image_roles）
    {"file_id": "img_a", "role": "first_frame"}
  ],
  "confidence": 0.82,                       // 角色识别置信度（规则+可选LLM）
  "qa_notes": ["关键帧对齐用于 safe_trim 切点"]
}
```
> 角色 role 由 `shot_role_labeler_v1` 技能产出：规则匹配关键词（痛点/卖点/效果/品牌/CTA）+ 导演分镜位置（开场→pain/product，中段→solution，尾段→brand/cta）。

---

## C. `fission_plan`（裂变计划）
编导层据生产单 + shot_map 产出。**让用户看清「为什么 30 条、分几组」**。
```json
{
  "fission_plan_id": "fp_77ab...",
  "production_order_id": "po_4f3a...",
  "source_video_ids": [1201, 1202, 1203],  // 合格源（duration_seconds>=30，沿用 P1 规则）
  "target_count": 30,
  "groups": [                              // 6 组排比矩阵（每组 5 条）
    {"group_type": "pain_first",  "center_idea": "痛点前置", "count": 5},
    {"group_type": "selling_first","center_idea": "卖点前置", "count": 5},
    {"group_type": "result_close","center_idea": "效果收束", "count": 5},
    {"group_type": "brand_double","center_idea": "品牌双定", "count": 5},
    {"group_type": "same_source", "center_idea": "同源前后", "count": 5},
    {"group_type": "reverse",     "center_idea": "倒叙",     "count": 5}
  ],
  "variants": ["var_...", "..."],          // fission_variant id 列表（30 条）
  "required_skills": ["safe_trim_setpts_v1","safe_concat_v1","text_card_insert_v1","subtitle_brand_style_v1","md5_duplicate_check_v1"],
  "required_assets": { "asset_pack_id": "ap_dfd_v1", "needs": ["logo","product_images","text_card_templates"] },
  "qa_gates": ["duration_check","pts_check","playback_validate","md5_duplicate_check","perceptual_hash_check","brand_presence_check","subtitle_readability_check"],
  "status": "preview"                      // preview|confirmed|executing|done|failed
}
```

---

## D. `fission_variant`（每条裂变视频施工单）
B 台据此**精确施工**，不再盲切。
```json
{
  "variant_id": "var_77ab_03",
  "group_type": "pain_first",
  "center_idea": "痛点前置 → 卖点 → 品牌收束",
  "segment_plan": [                        // 由哪些 shot 段按序拼（引用 shot_map）
    {"shot_id": "shot_po4f3a_03", "src_video_id": 1202, "in": 12.0, "out": 18.0, "role": "pain"},
    {"shot_id": "shot_po4f3a_01", "src_video_id": 1201, "in": 0.0,  "out": 6.0,  "role": "product"},
    {"shot_id": "shot_po4f3a_07", "src_video_id": 1203, "in": 22.0, "out": 28.0, "role": "brand"}
  ],
  "skill_sequence": [                      // 按序执行的技能（含参数）
    {"skill_id": "safe_trim_setpts_v1", "params": {"reencode": true}},
    {"skill_id": "safe_concat_v1",      "params": {"reencode": true, "target_duration": [90,120]}},
    {"skill_id": "text_card_insert_v1", "params": {"position": "head", "template": "pain_hook"}},
    {"skill_id": "subtitle_brand_style_v1", "params": {"brand": "达芙荻丽"}}
  ],
  "asset_sequence": [                      // 注入的素材（引用 asset_pack）
    {"type": "text_card", "ref": "ap_dfd_v1.text_card_templates.pain_hook"},
    {"type": "logo", "ref": "ap_dfd_v1.logo", "position": "outro"}
  ],
  "subtitle_plan": { "style": "brand_white_bottom", "lines": ["夏季干皮卡粉救星", "达芙荻丽奢华油"] },
  "transition_plan": { "type": "xfade", "duration": 0.3, "max_effects": 2 },   // ≤2 差异化手段
  "output_requirements": { "ratio": "9:16", "fps": 30, "reencode": true, "target_seconds": [90,120], "cost": 0 },
  "qa_expected": { "pts_monotonic": true, "playable_to_end": true, "md5_unique": true, "brand_present": true }
}
```
> **质感优先于去重**：`transition_plan.max_effects=2`；品牌定帧/产品特写/文字卡优先，炫酷特效默认关闭（quality gate，见 L4）。

---

## E. `skill_registry`（技能标准）
每个技能一条标准记录。第一版 12 个核心技能见 L4 / 第六节。
```json
{
  "skill_id": "safe_trim_setpts_v1",
  "name": "安全切片(trim+setpts)",
  "category": "video_edit",                // probe|video_edit|compose|label|plan|overlay|qa
  "engine": "ffmpeg",                      // ffmpeg|ffprobe|opencv|rule|internal
  "input_schema": { "src": "path", "in": "float", "out": "float", "reencode": "bool" },
  "output_schema": { "path": "path", "duration": "float", "pts_monotonic": "bool" },
  "default_params": { "reencode": true, "vcodec": "libx264", "preset": "veryfast", "pix_fmt": "yuv420p" },
  "business_use": "替代 -c copy 切片，根治 PTS 损坏/14秒卡死",
  "platform_fit": ["douyin","xiaohongshu","shipinhao"],
  "risk_level": "low",
  "qa_gates": ["pts_check","duration_check"],
  "fallback": "probe_video_v1 → 若 trim 失败回退整段重编码",
  "version": "v1"
}
```

---

## F. `asset_pack`（品牌素材包标准）
```json
{
  "asset_pack_id": "ap_dfd_v1",
  "brand_id": "brand_dfd",
  "brand_name": "达芙荻丽",
  "logo": { "file_id": "img_logo", "url": "https://<staging>/static/uploads/...", "safe_zone": "bottom_right" },
  "brand_color": { "primary": "#1E4D5B", "accent": "#C8A96A" },
  "product_images": [ {"file_id": "img_front", "role": "product_front"}, {"file_id": "img_bottle", "role": "detail"} ],
  "scene_images": [ {"file_id": "img_scene1", "role": "usage"} ],
  "intro_cards": [ {"template_id": "intro_premium", "text": "达芙荻丽奢华油"} ],
  "outro_cards": [ {"template_id": "outro_brand", "text": "以油养肤之美"} ],
  "text_card_templates": [ {"id": "pain_hook", "layout": "center_big", "max_chars": 14} ],
  "bgm": [ {"id": "bgm_premium_1", "url": "...", "license": "owned", "loudness_lufs": -16} ],
  "qr_assets": [ {"file_id": "img_qr", "role": "cta_qr"} ],
  "compliance_notes": "禁医疗功效虚假宣传；禁绝对化用语；BGM 需自有版权",
  "status": "active"                        // active|draft|disabled
}
```

---

## G. `qa_result`（每条视频质检结果）
```json
{
  "video_id": 1310,
  "production_order_id": "po_4f3a...",
  "variant_id": "var_77ab_03",
  "duration_ok": true,                      // duration_check：在 [90,120]±容差
  "pts_ok": true,                           // pts_check：ffprobe 帧 PTS 单调递增
  "playable_ok": true,                      // playback_validate：解码到结尾无错
  "md5_duplicate": false,                   // md5_duplicate_check：同批唯一
  "perceptual_similarity": 0.31,            // perceptual_hash_check：与同批最相近的汉明/相似度
  "brand_presence": true,                   // brand_presence_check：logo/品牌字幕出现
  "subtitle_readability": "ok",             // subtitle_readability_check：ok|low|none
  "platform_risk": "low",                   // 违禁词/水印/低画质风险
  "final_status": "pass",                   // pass|warn|fail
  "qa_logs": [
    {"gate": "pts_check", "result": "pass", "detail": "frames=...,monotonic=true"},
    {"gate": "md5_duplicate_check", "result": "pass", "md5": "ab12..."}
  ]
}
```
> `final_status`：任一 hard gate（pts/playable/duration）fail → `fail`（该条不入 viral 陈列、标记重做）；soft gate（相似度/品牌/字幕）不达标 → `warn`（入列但提示）。

---

## 字段级约束（给后端/前端对齐）
- `role` 枚举固定：`pain|product|solution|result|brand|cta`。
- `group_type` 枚举固定：`pain_first|selling_first|result_close|brand_double|same_source|reverse`。
- `status` 机：生产单 `preview→confirmed→generating→done|failed`；裂变计划 `preview→confirmed→executing→done|failed`。
- 所有 `*_id` 均带 tenant 归属校验；跨租户引用一律拒绝（沿用 P1/P0-B 既有隔离）。
- `cost` 字段在 B 台链路恒为 0（与 cost_ledger 对账，B 台不产生 precharge）。

> ⚠️ 本文件所有 JSON 为**契约草案**，字段名/枚举待 ChatGPT 审核后定稿，再进 L4 建表与 API。
