# V4 P2 · L1 PRD — 美业 AI 视频生产中枢

> 项目：**V4 美业 AI 视频生产中枢**（Video Production Manifest + Director Layer + Skill Library + Asset Pack + QA Feedback Loop）。
> 本轮**只做设计，不写业务代码、不改 production、不解锁 A台 compose、不触发火山、不部署**。
> 现状基线：V4 staging 已闭环（A台 Director-Prompt preview 打通；A台真实 compose 由 `ENABLE_COMPOSE=false` 锁住；B台 `source_video_ids` 裂变 30/30；feedback rating 兼容已修；候选池/Patch6/production 零影响均通过）。

---

## 1. 项目背景
A 台负责生成母视频与导演脚本（director_plan）；B 台目前**只拿到 mp4 文件**直接 ffmpeg 裂变。B 台**不知道** A 台导演了什么、每段内容的角色、该调用什么技能与素材。结果：
- A/B 台之间缺「编导统筹层」，信息断裂。
- B 台缺技能库、素材库、质检门。
- 用户能生成，但尚未形成「美业视频生产操作系统」。

## 2. 当前问题（深层）
- **Bug-1（差异化不足）**：同策略下裂变高度重复，平台易判重。
- **Bug-2（PTS 损坏/卡死）**：旧 `b_engine/remixer.py` 用 `-c copy -f segment` 切片 + `-c copy` concat，关键帧不规则导致 PTS 损坏，部分视频 14 秒后卡死/无法播放到结尾。
- **断层**：B 台盲切，不读导演稿；无角色（痛点/卖点/效果/品牌）概念。
- **缺门**：无质检（时长/PTS/可播放/去重/品牌存在）。
- **缺沉淀**：feedback 进候选池但未形成「生产经验库」反哺编导。

## 3. 用户角色
| 角色 | 诉求 | 可见复杂度 |
|----|----|----|
| 普通用户（user，美业商家/运营） | 选用途→传素材→一句话→看 preview→确认→拿 30 条 | **极简**：不看技能/参数/ffmpeg/manifest |
| 发码员（invite_admin） | 同 user + 发码 | 极简 + 发码 |
| 超级管理员（super_admin，平台/吴哥） | 候选池审核、技能库/素材包治理、全局存储、QA 概览 | 后台全量 |

## 4. 业务目标
1. 把 V4 从「视频生成/裂变工具」升级为「美业 AI 视频生产中枢」。
2. 用「生产单（production_order）」打通 A 台导演意图 → B 台施工，**B 台不再盲切**。
3. 引入技能库 + 素材包 + 质检门 + 经验回流，让 30 条裂变**差异化、可播放、带品牌、可沉淀**。

## 5. 产品目标（可度量）
- B 台裂变成片 **PTS 单调、可播放到结尾、duration 正常**（Bug-2 清零）。
- 同批 30 条 **MD5 无重复**、感知相似度低于阈值（差异化达标）。
- 每条裂变可追溯：来自哪个生产单 / 哪些镜头角色 / 调了哪些技能与素材。
- 用户端操作步数 ≤ 7（选用途→传素材→一句话→preview→确认生产单→确认裂变→下载）。
- B 台主路径 **0 API 成本**（不每次调 LLM、不调火山）。

## 6. 非目标（本期不做）
- 不解锁真实 compose（`ENABLE_COMPOSE` 保持 false）、不触发火山、不做 Seedance 2.5。
- 不引入 OpenMontage 代码、不引 AGPL 依赖、不接 HyperFrames/Remotion 到 production（仅 sandbox 预留思想）。
- 不碰 production、不改现有 staging、不直接部署、不大文件压测。
- 不做自动素材推荐 / 行业经验库自动学习（P3）。

## 7. 核心场景（用途）
产品种草 / 门店活动 / 客户案例 / 专家科普 / 直播切片 / 招商说明。
> 每个场景预置：默认 fission_goal、技能序列偏好、平台适配（抖音/小红书/视频号）、QA 阈值。

## 8. 用户流程（前台，极简）
```
选择用途 → 上传素材(图片/视频/品牌素材) → 输入一句话需求
→ A台 Director preview（导演稿+估价，不花钱）
→ 确认「生产单」 → 系统生成/绑定母视频
→ B台「裂变计划 preview」（看清为什么 30 条、分几组、每条由哪两段组成）
→ 确认裂变 → 生成 30 条（0 成本）
→ 筛选/下载/收藏/feedback → 好内容进候选池
```

## 9. 后台流程（复杂度藏在这里）
```
director_plan（A台）
  → Production Manifest 生产单(production_order + shot_map)
    → Director Layer 编导层 生成 fission_plan(groups/variants)
      → Skill Library 选执行技能(skill_registry → skill_executor)
        → Asset Pack 提供品牌素材(logo/产品图/卡片/BGM)
          → B台 Remixer 按 variant 施工(trim+setpts+filter_complex 重编码)
            → QA Gates 自动质检(duration/pts/playable/md5/相似度/品牌/字幕)
              → Feedback Loop 回流经验(reflow) → 候选池沉淀(knowledge_candidates)
```
- **规则引擎为主**：执行决策、参数约束、质检卡控由规则引擎做。
- **LLM 辅助**：理解、建议、preview；**B 台主路径默认零 API 成本**，不依赖每次调用 LLM。

## 10. 成功指标
| 维度 | 指标 |
|----|----|
| 稳定性 | PTS 损坏率 = 0；可播放到结尾率 = 100%；duration 偏差 < 0.5s |
| 差异化 | 同批 MD5 重复 = 0；感知相似度超阈占比 < 5% |
| 品牌 | 品牌存在检测通过率 ≥ 95%（有 asset_pack 时） |
| 成本 | B 台主路径单条 API 成本 = ¥0 |
| 体验 | 用户完成一单步数 ≤ 7；preview→确认转化可观测 |
| 沉淀 | 每单产出 ≥1 条经验候选（prompt/strategy/failure_case） |

## 11. 风险与边界
| 风险 | 缓解 |
|----|----|
| 重编码增加 CPU/耗时 | 技能分级、并发受控、ffmpeg 预设可调；P1.1 先保正确性再调性能 |
| 差异化过度→低质混剪 | quality gate：每条 ≤2 个差异化手段，品牌定帧/产品特写/文字卡优先 |
| asset_pack 缺失 | 无品牌素材时降级纯片段裂变，品牌门以 warning 不卡死 |
| 感知相似度算法成本 | P2 用 MD5 + 轻量 pHash；重算法（OpenCV）按需 |
| 引入第三方许可风险 | 禁 OpenMontage 代码 / AGPL；HyperFrames/Remotion 仅 sandbox |
| 真实 compose 误开 | `ENABLE_COMPOSE` 保持 false，解锁需 7 条件 + 人工确认 |

## 12. 分期路线图
- **P1.1（必修 Bug，可立即进代码）**：Remixer PTS 修复（`safe_trim_setpts` + `safe_concat` 重编码）+ duration/pts/playable 质检 + MD5 去重。**不依赖** P2 全套，可独立交付。
- **P2（MVP，设计后再开发）**：production_order / shot_map / fission_plan / skill_registry / asset_pack / qa_result + fission_plan preview。
- **P3（增强，远期）**：HyperFrames/Remotion sandbox、高级模板渲染、BGM 库、感知哈希、自动素材推荐、行业经验库自动学习。

> 与现有架构关系：P2 是在 A台(director_plans) 与 B台(remixer) 之间**插入编导统筹层**，复用 videos/cost_ledger/knowledge_candidates/reflow/uploads/admin_users，不推翻 P0/P1/P0-A/P0-B。
