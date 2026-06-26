# V4 P2 · L1–L4 设计包交付报告

> 本轮**只做设计**，未写业务代码、未改 production、未解锁 compose、未触发火山、未部署。供 ChatGPT 审核是否进入代码。

## 1. 本次输出文件
| 层 | 文件 | 作用 |
|----|----|----|
| L1 | `V4_P2_L1_PRD_VIDEO_PRODUCTION_CENTER.md` | PRD：背景/问题/角色/目标/场景/流程/指标/风险/路线图 |
| L2 | `V4_P2_L2_CLICKABLE_PROTOTYPE.html` | 单文件可点击原型（mock，11 区域 A–K） |
| L2.3 | `V4_P2_L2_3_DATA_CONTRACT_AND_MANIFEST_SPEC.md` | **核心**：7 个 JSON 契约（production_order/shot_map/fission_plan/fission_variant/skill_registry/asset_pack/qa_result） |
| L3 | `V4_P2_L3_INTERACTION_SPEC.md` | 交互规格（11 步流程、状态机、异常/锁态文案、两视角） |
| L4 | `V4_P2_L4_TECHNICAL_DESIGN.md` | 技术设计（7 模块、与现有连接、8 新表、API 草案、**P1.1 Remixer PTS 修复**、QA、安全、12 技能、DFD 素材包） |
| 报告 | `V4_P2_L1_L4_DELIVERY_REPORT.md` | 本文件 |

## 2. 核心设计结论
- 在 A台(director_plans) 与 B台(remixer) 之间**插入编导统筹层**：`production_order + shot_map → fission_plan + fission_variant`，B 台据施工单精确施工，**不再盲切**。
- **规则引擎为主、LLM 辅助**；B 台主路径**零 API 成本**，不调火山、不每次调 LLM。
- **质感优先于去重**：每条 ≤2 差异化手段，品牌定帧/产品特写/文字卡优先。
- 复用现有 `videos/cost_ledger/knowledge_candidates/reflow/uploads/admin_users`，**与 P0/P1/P0-A/P0-B 零冲突**（只新增表/服务/接口）。

## 3. 必答的 12 个关键问题（逐条）
1. **director_plan → production_order**：`production_order.director_plan_id` 引用现有 director_plans；其 storyboard/image_roles + 用户选的 scenario/platform/asset_pack → 生成生产单字段。
2. **production_order 让 B 台不盲切**：B 台不再只拿 mp4，而是拿 `fission_plan + fission_variant.segment_plan`（每段 shot_id/in/out/role）+ skill_sequence + asset_sequence，按单施工。
3. **shot_map 三对齐**：`mother_segment_mapper_v1` 把母视频时间轴(start/end) ↔ 导演稿(text/visual_description) ↔ 片段(source.video_id) 对齐，并由 `shot_role_labeler_v1` 打 role。
4. **fission_plan 生成 30 条**：6 组排比矩阵（痛点前置/卖点前置/效果收束/品牌双定/同源前后/倒叙）×5 条 = 30，每条一张 fission_variant 施工单（沿用 P1 的 1:10/30-50 与 source_video_ids 选源）。
5. **skill_registry v1 技能**：12 个核心（probe/safe_trim_setpts/normalize/safe_concat/playback_validate/shot_role_labeler/mother_segment_mapper/fission_strategy_planner/text_card_insert/product_image_insert/subtitle_brand_style/md5_duplicate_check）。
6. **skill_executor 调底层**：统一按 skill_id 找实现 → 调 ffmpeg/ffprobe/opencv，记 skill_runs（params/status/耗时/错误）；engine 字段决定走哪条工具链。
7. **asset_pack 冷启动**：最小集 = logo×1 + 产品图×3 + 文字卡模板×2 + 自有 BGM×1 + 品牌色；引用 uploads.file_id，HTTPS 校验沿用 image_url_check。
8. **DFD_ASSET_PACK_V1**：见 L4 §I（达芙荻丽：品牌色 #1E4D5B/#C8A96A、产品正面/瓶身/滴油 3 图、intro/outro 卡、pain_hook/selling_point 文字卡、自有 BGM、合规备注）。
9. **QA gates 拦截**：`pts_check`(ffprobe PTS 单调) + `playback_validate`(ffmpeg -f null 解码到尾) + `duration_check` 为 hard gate，fail→重做不入列；`md5_duplicate_check` hard 去重；相似/品牌/字幕为 soft warn。
10. **feedback 反哺经验库**：QA pass + 高分 → 候选(source_type=strategy)；fail → 候选(source_type=failure_case)；批次摘要 → workflow_summary，经 super_admin 审核沉淀（P3 自动学习）。
11. **用户端极简**：用户只见 用途/素材/一句话/导演稿(人话)/估价/裂变计划(6组+为什么30条)/结果(绿黄红点)；技能/参数/ffmpeg/manifest/PTS/MD5 全部隐藏。
12. **HyperFrames/Remotion 预留**：skill_registry 占位 `template_render_card_v1`(engine=template)，P3 在独立 sandbox 渲染高级卡片回流给 safe_concat；**不引代码到 production**。

## 4. 哪些可进入 P1.1 修复（立即，独立于 P2 全套）
- **Remixer PTS 修复**：废弃 `-c copy` 切/拼，改 `safe_trim_setpts`(trim+setpts+重编码) + `normalize` + `safe_concat`(重编码) → PTS 单调、可播放到结尾、duration 正常。
- **质检最小集**：`duration_check` / `pts_check` / `playback_validate` / `md5_duplicate_check`。
- 保持 cost=0、不调火山、不碰 production。
> P1.1 只动 `b_engine/remixer.py` + 加轻量质检，不依赖 production_order/fission_plan，可先交付清掉 Bug-2。

## 5. 哪些只是 P2 设计（审核通过后再开发）
production_order / shot_map / fission_plan / fission_variant / skill_registry / skill_runs / asset_packs / qa_results 八表 + 7 服务 + 10 API 草案 + fission_plan preview。

## 6. 哪些需要 ChatGPT 拍板
1. 7 个 JSON 契约的字段/枚举是否定稿（role/group_type/status 机）。
2. P1.1 是否**先单独发**（清 Bug-2）再做 P2，还是合并。
3. 6 组排比矩阵是否就是默认裂变策略（可否按 scenario 变体）。
4. QA 哪些设为 hard gate（建议 pts/playable/duration/md5），soft 阈值取值。
5. 感知相似度(perceptual_hash)放 P2 还是 P3（OpenCV 成本）。
6. asset_pack 合规校验深度（是否需违禁词库）。
7. 重编码性能预算（并发/preset）与 staging 机器配额。

## 7. 风险清单
| 风险 | 等级 | 缓解 |
|----|----|----|
| 重编码 CPU/耗时上升 | 中 | preset veryfast + 受控并发；P1.1 先正确后性能 |
| 差异化过度→低质 | 中 | quality gate ≤2 手段，品牌优先 |
| asset_pack 缺失 | 低 | 降级纯片段裂变，品牌门 warn 不卡 |
| 第三方许可（OpenMontage/AGPL/HyperFrames/Remotion） | 高 | 一律不引代码到 production；仅思想/ sandbox 预留 |
| 真实 compose 误开 | 高 | ENABLE_COMPOSE 保持 false，7 条件+人工确认 |
| 新表与现有冲突 | 低 | 只新增表，零改现有 schema |

## 8. 下一步建议
1. ChatGPT 审核本设计包（重点 L2.3 契约 + L4 P1.1 修复 + 12 问答）。
2. 通过后**优先发 P1.1**（Remixer PTS 修复 + 质检最小集），清掉线上 Bug-2，cost=0。
3. 再分批做 P2 MVP（先 production_order/shot_map/fission_plan preview，后 skill_registry/asset_pack/qa）。
4. P3（HyperFrames/Remotion sandbox、感知哈希、自动素材、经验自学习）远期评估。

## 9. 约束遵守自查
- ✅ 仅设计文档 + 可点击原型，未写业务代码
- ✅ 未改 production / 未解锁 ENABLE_COMPOSE / 未触发火山 / 未部署 / 未改 staging
- ✅ 未引 OpenMontage 代码 / AGPL；HyperFrames/Remotion 仅 sandbox 预留
- ✅ 所有 API/JSON/DDL 标注为草案，不得直接执行
- ✅ 与 V4 P0/P1/P0-A/P0-B 不冲突；明确区分 P1.1 立即修复 vs P2/P3 设计
