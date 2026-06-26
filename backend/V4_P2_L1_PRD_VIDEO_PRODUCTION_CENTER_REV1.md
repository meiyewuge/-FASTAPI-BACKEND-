# V4 P2 · L1 PRD（Rev1）— 美业 AI 视频生产中枢

> Rev1 小修定稿（取代原 `V4_P2_L1_PRD_VIDEO_PRODUCTION_CENTER.md`）。仍**纯设计，不写代码、不改 production、不解锁 compose、不触发火山、不部署**。
> Rev1 主修：**时长口径统一为短视频**、P1.1/P2 边界拆清、skill_executor 安全边界、素材权限分层、QA fail 重做策略、**素材供应网关（Asset Supply Gateway）**。

---

## 0. Rev1 关键口径（先定，全包一致）
| 项 | 口径 |
|----|----|
| A台 preview 估价 | 仍按 15 秒说明（真实 compose 锁住，仅展示估价） |
| A台 母视频目标（P2） | **27–30 秒** |
| B台 合格源视频 | `duration_seconds >= 30`（不变） |
| **B台 裂变输出（默认）** | **`target_seconds = [25,35]` 短视频** |
| **duration_check** | **[25,35]±容差** |
| P1.1 修复目标 | **30 秒级短视频不卡死、不重复、可播放到结尾** |
| 90–120 秒长视频 | **移到 P3**（长视频/课程切片/直播切片扩展），不属于 P1.1/P2 MVP |

> Bug-2 现象正是 30 秒视频在 14 秒后卡死——P1.1 修的是 **30 秒级短视频**的 PTS/播放/去重，**不改成 90–120 秒**。

---

## 1. 背景 / 当前问题
A 台生成母视频与导演稿；B 台目前只拿 mp4 盲切，不知道 A 台导演了什么、每段角色、该用什么技能与素材。
- **Bug-1**：同策略裂变高度重复，差异化不足。
- **Bug-2**：旧 `b_engine/remixer.py` 用 `-c copy -f segment` 切/拼，关键帧不规则 → PTS 损坏，**30 秒视频 14 秒后卡死**。
- 缺编导统筹层、技能库、素材供应、质检门、经验回流。

## 2. 角色
| 角色 | 诉求 | 可见复杂度 |
|----|----|----|
| user | 选用途→传素材(可选素材增强)→一句话→preview→确认→拿短视频裂变 | 极简 |
| invite_admin | 同 user + 发码 | 极简 + 发码 |
| super_admin | 候选池/技能库/品牌素材包治理/QA 概览/全局存储 | 后台全量 |

## 3. 业务目标
1. V4 升级为「美业 AI 视频生产中枢」。
2. 用「生产单」打通 A→B，B 台不再盲切。
3. 技能库 + **素材供应网关** + 质检门 + 经验回流，让短视频裂变**差异化、可播放、带品牌、可沉淀**。

## 4. 产品目标（短视频口径，可度量）
- B 台裂变成片 **PTS 单调、可播放到结尾、duration 在 [25,35]**（Bug-2 清零）。
- 同批 **MD5 无重复**、感知相似度低于阈值。
- 每条可追溯：生产单 / 镜头角色 / 技能 / 素材 / 授权。
- 用户操作步数 ≤ 7；B 台主路径 **0 平台 API 成本**（不调火山、付费素材不走平台账）。

## 5. 成功指标（短视频）
| 维度 | 指标 |
|----|----|
| 稳定性 | PTS 损坏率=0；可播放到结尾=100%；**duration 落在 [25,35]，偏差<0.5s** |
| 差异化 | 同批 MD5 重复=0；相似度超阈占比<5% |
| 品牌 | 品牌存在检测通过率≥95%（有素材包时） |
| 成本 | B 台主路径单条平台 API 成本=¥0；**付费素材费不经平台、不扣 token** |
| 体验 | 完成一单步数≤7 |
| 沉淀 | 每单≥1 条经验候选 |

## 6. 非目标（本期不做）
- 不解锁真实 compose（ENABLE_COMPOSE=false）、不触发火山、不做 Seedance 2.5。
- 不接真实素材 API、不接任何素材支付、不代购素材、不做素材收银台。
- 不引 OpenMontage 代码 / AGPL；HyperFrames/Remotion 仅 sandbox。
- 不碰 production、不改 staging、不部署、不大文件压测。
- **90–120 秒长视频不做（P3）**。

## 7. 核心场景（用途）
产品种草 / 门店活动 / 客户案例 / 专家科普 / 直播切片 / 招商说明。每场景预置默认 fission_goal、技能序列、平台适配、QA 阈值（均为短视频口径）。

## 8. 素材供应网关（Asset Supply Gateway）— Rev1 升级
素材丰富度不靠用户自己找，也不靠自建。四类来源：
1. **production_assets**：用户本次上传，仅绑定当前生产单（普通用户可上传）。
2. **brand_asset_pack**：品牌长期可复用素材包（super_admin/授权管理员维护）。
3. **free_stock_gateway**：国际免费源（预留 Pexels/Pixabay/Unsplash），**默认优先**，需记录来源/作者/授权/是否署名/是否商用/缓存策略。
4. **paid_stock_gateway**：国际付费源（预留 Adobe Stock/Shutterstock/Getty/Storyblocks），**用户主动开启，外部跳转自购自传，不走平台账、不扣 token、不进 cost_ledger**。
> 铁律：平台只「找/筛/推荐/记录/混剪」，**不代购、不收银、不垫资**。后续规模化的分佣/批发为 **P4 商业化**，不在本期。

## 9. 用户流程（前台，极简）
```
选择用途 → 上传素材 + 选「素材增强」(仅我上传/优先免费/允许付费推荐, 默认优先免费)
→ 一句话需求 → A台 Director preview（导演稿+估价, 不花钱）
→ 确认生产单 → 生成/绑定母视频(27–30s, 受 compose 锁)
→ B台「裂变计划 preview」(6 组+为什么 30 条+将用哪些素材+预计素材成本)
→ 确认裂变 → 生成短视频(25–35s, 0 平台成本)
→ 筛选/下载/收藏/反馈(QA 绿/黄/红) → 好内容进候选池
```

## 10. 后台流程
```
director_plan → production_order + shot_map → fission_plan + fission_variant
→ Skill Library(白名单 adapter) → Asset Supply Gateway(四源 + 授权台账)
→ B台 Remixer(safe_trim_setpts+safe_concat 重编码, 短视频) → QA Gates(含 license_check/license_claim_check)
→ Feedback Loop(reflow) → 候选池
```

## 11. 风险与边界
| 风险 | 缓解 |
|----|----|
| 时长口径误写成长视频 | Rev1 全包统一 [25,35]，90–120 标 P3 |
| 重编码 CPU/耗时 | preset veryfast + 受控并发；P1.1 先正确后性能 |
| skill 命令注入 | **DB 不存可执行命令**；skill_id 白名单→adapter→固定参数模板→校验→路径白名单 |
| 付费素材版权/财务 | 外部跳转自购自传；license_claim_check；平台不垫资不走账 |
| 免费素材同质化/合规 | beauty_asset_ranker 评分 + 二次品牌化加工 |
| QA fail 拖死 batch | 单条重做 1–2 次→失败标 failed；batch partial_done |

## 12. 分期路线图
- **P1.1（立即止血）**：Remixer 短视频 PTS 修复 + 最小 QA（duration/pts/playable/md5）。只动 `remixer.py`，不建 P2 表、不改前端、cost=0、compose 锁定。
- **P2（MVP）**：production_order/shot_map/fission_plan/fission_variant/skill_registry/asset_pack/qa_result + production_assets/brand_asset_pack 实现 + free_stock adapter 占位 + paid 预算/授权流程**设计** + license_check 结构 + fission_plan preview + 用户侧生产单/裂变计划页面。
- **P3（增强）**：真实接入 Pexels/Pixabay/Unsplash + Adobe/Shutterstock/Getty/Storyblocks、真实购买授权与 license ledger、感知哈希、自动素材推荐、**90–120 秒长视频/课程切片**、HyperFrames/Remotion sandbox。
- **P4（商业化）**：素材分佣（CPS）、企业批量采购、素材会员包、批发商模式。
