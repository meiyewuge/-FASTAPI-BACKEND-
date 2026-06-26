# V4 P2 · L2.3（Rev1）— 数据契约 & 生产单规范

> Rev1（取代原 L2.3）。**草案，不得直接执行。** 主修：时长口径短视频、素材四层 + 授权台账、素材权限分层、QA 重做/partial_done、license 校验。
> 统一口径：B台裂变输出 **target_seconds=[25,35]**；duration_check **[25,35]**；90–120s 属 P3。

## 总览
```
director_plan(已有) → production_order ─1:1─ shot_map[]
   → fission_plan ─1:N─ fission_variant[]
   素材：production_assets / brand_asset_pack / free_stock / paid_stock(外部跳转) → asset_license_ledger
   → B台 Remixer(短视频重编码) → videos(type=viral) ─1:1─ qa_result
   → reflow / knowledge_candidates
```

---

## A. `production_order`（生产单）
```json
{
  "production_order_id":"po_...","tenant_id":"t_...","user_id":"138...",
  "brand_id":"brand_dfd","product_id":"prod_dfd_oil",
  "scenario":"product_seeding","platform":"douyin","ratio":"9:16",
  "duration":30,                              // A台母视频目标 27-30s（P2）
  "director_plan_id":"dp_...","mother_video_ids":[1201],
  "asset_pack_id":"ap_dfd_v1",
  "asset_policy":{                            // ★ Rev1 新增（素材策略）
    "use_user_uploads":true,"use_brand_pack":true,"use_free_stock":true,
    "allow_paid_recommendation":false,
    "paid_payment_mode":"external_redirect",  // 付费走外部跳转
    "platform_pays_stock_fee":false,          // 平台不垫资
    "token_cost_for_stock_asset":0,           // 不扣 token
    "require_user_upload_after_purchase":true,
    "require_user_license_confirmation":true,
    "require_manual_paid_confirm":true,
    "paid_budget_limit":0,
    "preferred_sources":["production_assets","brand_asset_pack","pexels","pixabay"],
    "blocked_sources":[]
  },
  "asset_sources":["production_assets","brand_asset_pack","pexels","pixabay"],
  "selected_assets":[ {"asset_id":"pexels_video_123","source":"pexels","usage_role":"background_scene","license_status":"free_recorded"} ],
  "paid_asset_budget":0,"asset_cost_estimate":0,
  "skill_profile_id":"sp_seeding_v1",
  "fission_goal":{"target_count":30,"ratio_per_source":10,"max_outputs":50,"output_seconds":[25,35]}, // 短视频
  "qa_gates":["duration_check","pts_check","playback_validate","md5_duplicate_check","brand_presence_check","license_check","license_claim_check"],
  "cost_policy":{"b_track_api_cost":0,"allow_llm_assist":false,"compose_locked":true,"stock_paid_by_platform":false},
  "status":"preview","created_at":"2026-06-26T00:00:00Z"
}
```

## B. `shot_map`（镜头角色地图）
```json
{ "shot_id":"shot_po_01","production_order_id":"po_...","source":{"video_id":1201,"kind":"mother"},
  "role":"pain", "start_time":0.0,"end_time":4.0, "text":"夏季干皮上妆卡粉的困扰",
  "visual_description":"女性面部干皮特写，暖自然光侧照",
  "image_refs":[{"file_id":"img_a","role":"first_frame"}], "confidence":0.82,
  "qa_notes":["关键帧对齐用于 safe_trim 切点"] }
```
> role 枚举：`pain|product|solution|result|brand|cta`。

## C. `fission_plan`（裂变计划）
```json
{ "fission_plan_id":"fp_...","production_order_id":"po_...","source_video_ids":[1201,1202,1203],
  "target_count":30,
  "groups":[
    {"group_type":"pain_first","center_idea":"痛点前置","count":5},
    {"group_type":"selling_first","center_idea":"卖点前置","count":5},
    {"group_type":"result_close","center_idea":"效果收束","count":5},
    {"group_type":"brand_double","center_idea":"品牌双定","count":5},
    {"group_type":"same_source","center_idea":"同源前后","count":5},
    {"group_type":"reverse","center_idea":"倒叙","count":5}
  ],
  "variants":["var_..."],
  "required_skills":["safe_trim_setpts_v1","normalize_video_v1","safe_concat_v1","text_card_insert_v1","subtitle_brand_style_v1","md5_duplicate_check_v1"],
  "required_assets":{"asset_pack_id":"ap_dfd_v1","needs":["logo","product_images","text_card_templates"],
                     "stock_plan":{"free_count":8,"paid_count":0,"paid_cost_estimate":0}},
  "asset_summary":{"user_uploads":3,"brand_pack":5,"free_stock":8,"paid_stock":0,"paid_pending":0,"asset_cost_estimate":0},
  "qa_gates":["duration_check","pts_check","playback_validate","md5_duplicate_check","perceptual_hash_check","brand_presence_check","license_check","license_claim_check"],
  "status":"preview" }
```

## D. `fission_variant`（每条裂变施工单）— 短视频
```json
{ "variant_id":"var_..._03","group_type":"pain_first","center_idea":"痛点前置→卖点→品牌收束",
  "segment_plan":[
    {"shot_id":"shot_po_03","src_video_id":1202,"in":12.0,"out":18.0,"role":"pain"},
    {"shot_id":"shot_po_01","src_video_id":1201,"in":0.0,"out":6.0,"role":"product"},
    {"shot_id":"shot_po_07","src_video_id":1203,"in":22.0,"out":28.0,"role":"brand"}
  ],
  "skill_sequence":[
    {"skill_id":"safe_trim_setpts_v1","params":{"reencode":true}},
    {"skill_id":"normalize_video_v1","params":{"w":1080,"h":1920,"fps":30}},
    {"skill_id":"safe_concat_v1","params":{"reencode":true,"target_seconds":[25,35]}},
    {"skill_id":"text_card_insert_v1","params":{"position":"head","template":"pain_hook"}},
    {"skill_id":"subtitle_brand_style_v1","params":{"brand":"达芙荻丽"}}
  ],
  "asset_sequence":[                          // 引用 asset_pack / stock；含外部素材插入
    {"asset_id":"ap_dfd_v1.logo","type":"logo","role":"outro"},
    {"asset_id":"pexels_video_123","type":"video","role":"scene_insert","insert_at":8.0,"duration":2.5}
  ],
  "inserted_stock_assets":[ {"asset_id":"pexels_video_123","source":"pexels","license_type":"free_stock"} ],
  "license_check_required":true,
  "subtitle_plan":{"style":"brand_white_bottom","lines":["夏季干皮卡粉救星","达芙荻丽奢华油"]},
  "transition_plan":{"type":"xfade","duration":0.3,"max_effects":2},
  "output_requirements":{"ratio":"9:16","fps":30,"reencode":true,"target_seconds":[25,35],"cost":0}, // ★ 短视频
  "qa_expected":{"pts_monotonic":true,"playable_to_end":true,"duration_in_range":[25,35],"md5_unique":true,"brand_present":true,"license_ok":true},
  "qa_status":"pending","retry_count":0,"max_retry":2,"final_status":null  // ★ Rev1 重做策略
}
```

## E. `skill_registry`（技能标准）— **DB 不存可执行命令**
```json
{ "skill_id":"safe_trim_setpts_v1","name":"安全切片(trim+setpts)","category":"video_edit",
  "engine":"ffmpeg","adapter":"safe_trim_setpts_adapter",      // ★ 映射到 Python adapter（非裸命令）
  "input_schema":{"src":"path","in":"float","out":"float","reencode":"bool"},
  "output_schema":{"path":"path","duration":"float","pts_monotonic":"bool"},
  "default_params":{"reencode":true,"vcodec":"libx264","preset":"veryfast","pix_fmt":"yuv420p","fps":30},
  "business_use":"替代 -c copy 切片，根治 30 秒级短视频 PTS 损坏/14秒卡死",
  "platform_fit":["douyin","xiaohongshu","shipinhao"],"risk_level":"low",
  "qa_gates":["pts_check","duration_check"],"fallback":"probe_video_v1 → 失败回退整段重编码",
  "version":"v1","enabled":true }
```
> **安全铁律**：`skill_registry` 只存 `adapter` 名 + `default_params` + 元数据；**绝不存整条 ffmpeg/shell 命令**。执行见 L4 安全边界。

## F. `asset_pack`（品牌长期素材包，super_admin 管理）
```json
{ "asset_pack_id":"ap_dfd_v1","brand_id":"brand_dfd","brand_name":"达芙荻丽",
  "logo":{"file_id":"img_logo","safe_zone":"bottom_right"},"brand_color":{"primary":"#1E4D5B","accent":"#C8A96A"},
  "product_images":[{"role":"product_front"},{"role":"bottle_detail"},{"role":"oil_drop"}],
  "scene_images":[{"role":"usage"}],"intro_cards":[{"template_id":"intro_premium"}],"outro_cards":[{"template_id":"outro_brand"}],
  "text_card_templates":[{"id":"pain_hook","max_chars":14}],"bgm":[{"id":"bgm_premium_1","license":"owned"}],
  "qr_assets":[{"role":"cta_qr"}],"compliance_notes":"禁医疗功效虚假宣传；禁绝对化用语；BGM 自有版权",
  "status":"active" }
```

## F2. `production_assets`（用户本次上传素材，普通用户可上传）— ★ Rev1 拆分
```json
{ "production_asset_id":"pa_...","production_order_id":"po_...","tenant_id":"t_...","user_id":"138...",
  "file_id":"<uploads.file_id>","type":"image|video|audio","usage_scope":"current_production_order",
  "source_type":"user_upload","created_at":"..." }
```
> 与 `asset_pack` 严格分层：production_assets 普通用户可传、仅当前单可用；asset_pack 仅 super_admin/授权管理员、可被多单复用。

## G. `asset_source`（素材源注册）— ★ Rev1 新增
```json
{ "source_id":"src_pexels","provider":"pexels","source_type":"free_stock", // user_upload|brand_pack|free_stock|paid_stock
  "api_adapter":"pexels_adapter","enabled":true,"auth_required":true,
  "attribution_required_default":true,"commercial_use_default":true,
  "cache_policy":"allow_with_attribution","license_policy":"pexels_terms","risk_level":"low" }
```

## H. `external_asset_candidate`（外部素材候选）— ★ Rev1 新增
```json
{ "external_asset_id":"pexels_video_123","provider":"pexels","type":"video","title":"woman skincare routine",
  "preview_url":"...","thumbnail_url":"...","download_url_or_license_endpoint":"...","duration":8.2,"ratio":"9:16",
  "tags":["skincare","spa","beauty"],"creator":"...","source_url":"...",
  "license_type":"free_stock","attribution_required":true,"commercial_use":true,
  "cost":0,"currency":"CNY","license_required":false,"license_status":"free_recorded","risk_level":"low",
  // 付费素材附加：
  "official_purchase_url":null,"payment_flow":"external_redirect","platform_billing":false,"token_cost":0,
  "requires_user_upload_after_purchase":false,"estimated_price":null,"license_notice":null,
  // 评分（beauty_asset_ranker）：
  "beauty_fit_score":0.86,"brand_fit_score":0.78,"platform_fit_score":0.82,"quality_score":0.91,
  "license_risk_score":0.12,"final_score":0.84 }
```
> 付费候选示例：`license_required:true, payment_flow:"external_redirect", platform_billing:false, token_cost:0, requires_user_upload_after_purchase:true, official_purchase_url:"<adobe/shutterstock...>"`。

## H2. `paid_user_uploaded_asset`（用户外部自购后上传）— ★ Rev1 新增
```json
{ "source_type":"paid_user_uploaded","original_provider":"adobe_stock","original_asset_url":"...",
  "purchase_claimed_by_user":true,"license_claimed_by_user":true,"license_document_url":null,
  "usage_scope":"current_production_order",
  "user_confirmation_text":"我确认该素材由我本人购买或拥有合法使用权，并授权本次视频生产使用。",
  "confirmed_at":"..." }
```

## I. `asset_license_ledger`（素材授权台账）— ★ Rev1 新增（规模化风控核心）
```json
{ "ledger_id":"al_...","production_order_id":"po_...","asset_id":"pexels_video_123","provider":"pexels",
  "external_asset_id":"pexels_video_123","source_type":"free_stock", // free_stock|paid_user_uploaded|user_upload|brand_pack
  "license_type":"free_stock","license_status":"free_recorded","license_id":null,
  "license_price":0,"currency":"CNY","attribution_text":"Video by ... on Pexels","attribution_url":"...",
  "commercial_use":true,"cache_allowed":true,"transform_allowed":true,
  "purchased_by":null,         // 付费时=用户；平台从不作为购买方
  "purchased_at":null,"usage_scope":"current_production_order","created_at":"..." }
```
> 这是「授权使用记录」，**不是平台购买记录**——付费素材 `purchased_by=用户`，`platform_billing=false`。

## J. `qa_result`（质检结果）— 短视频 + 重做/partial
```json
{ "video_id":1310,"production_order_id":"po_...","variant_id":"var_..._03",
  "duration_ok":true,              // duration_check：在 [25,35]±容差（★ 短视频）
  "pts_ok":true,"playable_ok":true,"md5_duplicate":false,"perceptual_similarity":0.31,
  "brand_presence":true,"subtitle_readability":"ok","platform_risk":"low",
  "license_ok":true,               // ★ license_check
  "license_claim_ok":true,         // ★ 付费素材 license_claim_check（无付费素材时默认 true）
  "retry_count":0,"final_status":"pass",  // pass|warn|fail；fail 触发重做(≤max_retry)
  "qa_logs":[{"gate":"pts_check","result":"pass"},{"gate":"duration_check","result":"pass","range":[25,35]}] }
```
> hard gate（pts/playable/duration/md5/license/license_claim）fail → 重做；soft（相似/品牌/字幕）不达标 → `warn`。

## K. QA 重做 & partial_done 规则（★ Rev1）
- 单条 variant hard gate fail → **自动重做最多 `max_retry`(默认 2) 次**。
- 仍失败 → 该 variant `final_status=failed`，**不入 viral 陈列、标「需重做」、不建议下载**。
- batch 允许 `partial_done`：如 30 条里 28 pass、2 failed，**不拖死整个 batch**；前端「28 条可用，2 条需重做」。
- soft warn 可展示但提示风险。

---

## 枚举 & 约束（对齐）
- `role`：pain|product|solution|result|brand|cta；`group_type`：pain_first|selling_first|result_close|brand_double|same_source|reverse。
- `source_type`(素材)：user_upload|brand_pack|free_stock|paid_stock / paid_user_uploaded。
- 时长：母视频 27–30s；**裂变输出 [25,35]**；90–120s 属 P3。
- 付费素材：`payment_flow=external_redirect`、`platform_billing=false`、`token_cost=0`、平台不进 cost_ledger。
- 所有 `*_id` 带 tenant 校验；跨租户拒绝。
