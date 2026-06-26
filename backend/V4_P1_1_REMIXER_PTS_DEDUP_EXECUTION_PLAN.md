# V4 P1.1 · Remixer PTS / 去重 修复执行方案

> **本轮只输出方案文档，不写代码。** 供 ChatGPT 审核后再决定是否进代码。
> 目标：修 B 台短视频裂变两个硬 Bug（Bug-1 重复、Bug-2 14 秒卡死/PTS 损坏）。
> 硬约束：B 台 `cost=0`；`ENABLE_COMPOSE=false`；A 台真实 compose 锁住；**production 零影响**；不触发火山。
> 口径：短视频，裂变输出 **duration ∈ [25,35]**（沿用 P2 Rev1）。

---

## 1. 当前问题复盘（基于真实代码 `b_engine/remixer.py`）
- **Bug-2（14 秒卡死 / PTS 损坏）**
  - `_slice()`（L51–58）用 `ffmpeg -c copy -f segment -segment_time -reset_timestamps 1`：**不重编码**，切点强制落在原始关键帧；`reset_timestamps` 只重置容器时间基，GOP 仍不规则。
  - `_concat()`（L61–73）用 `concat demuxer -c copy`：把这些 GOP/PTS 不规则的段直接拼，**拼接处 PTS 非单调**，部分播放器解码到中段（约 14s）冻结、duration 异常。
  - `_render_variant()`（L92–93）视频重编码但 **`-c:a copy` 音频直拷**：音频 PTS 与重编码后的视频 PTS 不对齐，A/V 失步、尾段卡顿。
- **Bug-1（裂变重复 / 高相似 / MD5 重复）**
  - 去重手段仅：`crop` 边缘裁切 `pad=2+(i%4)*2`（L82–83，仅 4 档循环）+ 段轮转 `segs[k:]+segs[:k]`（L137–139）。手段单一、循环周期短 → 同策略下高度相似、**MD5 易重复**。
- **无时长控制**：输出 duration = 重组后原始时长，**未约束到 [25,35]**。
- **无任何质检**：不校验 PTS / 可播放 / duration / MD5；坏视频直接进 completed。

---

## 2. 根因
| Bug | 根因 |
|----|----|
| 14 秒卡死 / PTS 损坏 | `-c copy` 切片 + `-c copy` 拼接 → 非关键帧切点 + GOP/PTS 不规则 + 拼接 PTS 非单调；`-c:a copy` 音视频失步 |
| 重复 / MD5 重复 | 去重维度少（crop 4 档 + 段轮转），无策略级多维差异化 |
| 时长不达标 | 无目标时长控制，未裁到 [25,35] |
| 坏视频入库 | 无 QA 门 |

---

## 3. 修改文件清单（P1.1 允许范围）
| 文件 | 动作 |
|----|----|
| `b_engine/remixer.py` | **重写主流程**：废弃 `_slice()+_concat(-c copy)`，改 `trim+setpts / atrim+asetpts / filter_complex` 重编码切片 + 规范化重编码拼接 + 时长裁到 [25,35] + 多维差异化 |
| `b_engine/qa_checks.py`（新增，轻量） | 封装 `duration_check / pts_check / playback_validate / md5_duplicate_check` + 重试/partial 辅助 |
| `tests/verify_p1_1_remixer.py`（新增，轻量） | 真实样本回归（见 §8） |
| `BACKEND_V4_P1_1_REMIXER_FIX_REPORT.md`（新增，代码阶段产出） | 修复报告（本轮不产，仅占位说明） |
> **不动**：`services/b_service.py` 的对外签名（`remix_videos(...)` 返回结构保持兼容，仅内部实现更稳 + 每条附 QA 结果字段）；orchestrator / 路由 / 前端 / cost_ledger / 任何 P2 表均不改。

---

## 4. 新 Remixer 流程图
```
remix_videos(source_path, count, strategy, stores)
  └─ probe(source)  [probe_video: duration/fps/分辨率]
  └─ for i in count:
       1) 选策略 + 选段方案(plan)：按策略决定取哪几段、顺序(段落顺序变化/组合变化/倒叙)
       2) safe_trim_setpts(每段)         # trim+setpts / atrim+asetpts，重编码
       3) normalize(每段)                # 1080x1920 / 30fps / SAR=1 / 44100 立体声（统一）
       4) safe_concat(filter_complex)    # 重编码拼接，PTS 单调
       5) 裁/补到目标 [25,35]            # -t / 末段裁切
       6) 差异化叠加：策略字幕 + 文字卡(片头/片尾) + 轻转场(xfade) + 轻微色调/裁切
       7) 重编码输出 out.mp4 (+faststart)
       8) QA: duration_check / pts_check / playback_validate / md5_duplicate_check
       9) QA 失败 → 重试(≤2，换段方案/换裁切种子) → 仍失败标 failed（不入 completed）
  └─ 返回 outputs（含每条 qa 结果）；batch 允许 partial_done
```
> **P1.1 第一版：全程重编码，禁止任何 `-c copy` 快路径**（含「单源单段不拼」也重编码）。原因：Bug-2 正是关键帧/原始 PTS 引发，第一版先保正确性，性能优化另开。

---

## 5. FFmpeg 命令模板（草案）

### 5.1 safe_trim_setpts（单段精确切 + 重置 PTS，重编码）
```bash
ffmpeg -y -i src.mp4 \
  -vf "trim=start=<in>:end=<out>,setpts=PTS-STARTPTS,fps=30,\
scale=1080:1920:force_original_aspect_ratio=decrease,\
pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1" \
  -af "atrim=start=<in>:end=<out>,asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 44100 -ac 2 -movflags +faststart \
  seg_i.mp4
```
> 无音轨源：用 `-f lavfi -t <len> -i anullsrc=r=44100:cl=stereo` 补静音轨，保证段参数一致可拼。

### 5.2 safe_concat（多段重编码拼接，PTS 单调）
```bash
# 段已 normalize 为等参 → filter_complex concat（首选，最稳）
ffmpeg -y -i seg_0.mp4 -i seg_1.mp4 -i seg_2.mp4 \
  -filter_complex "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1[v][a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 44100 -ac 2 -movflags +faststart -t <target∈[25,35]> out_concat.mp4
```

### 5.3 差异化叠加（策略字幕 + 文字卡 + 轻转场 + 轻色调/裁切；≤2 个手段叠加）
```bash
# 例：策略字幕 + 轻微色调 + 边缘微裁（重编码）
ffmpeg -y -i out_concat.mp4 \
  -vf "crop=iw-<pad*2>:ih-<pad*2>:<pad>:<pad>,\
eq=saturation=<0.95~1.08>:brightness=<-0.02~0.02>,\
drawtext=fontfile='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc':text='<策略字幕>':\
fontcolor=white:fontsize=36:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=30,\
drawtext=...text='<CTA>':fontcolor=yellow:fontsize=40:y=h-text_h-40" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 -c:a aac -ar 44100 -ac 2 \
  -movflags +faststart out_final.mp4
# 片头/片尾轻量卡片：用 color/卡片片段 + xfade 转场拼接（同 5.2 等参重编码）
```
> 差异化维度池（每条随机取 ≥3，叠加视觉手段 ≤2，避免廉价炫酷）：段落顺序、片段组合、策略字幕文案、文字卡(片头/片尾)、轻 xfade 转场、轻微色调(eq)、轻微裁切(crop)。

---

## 6. QA 检测方法（`b_engine/qa_checks.py`）
| 检测 | 命令/方法 | 通过条件 |
|----|----|----|
| `duration_check` | `ffprobe -show_entries format=duration` | duration ∈ [25,35]±0.5s |
| `pts_check` | `ffprobe -select_streams v -show_entries frame=pkt_pts_time -of csv` | PTS 序列严格单调递增（无回退/重复） |
| `playback_validate` | `ffmpeg -v error -i out.mp4 -f null -` | stderr 无 error（可完整解码到结尾） |
| `md5_duplicate_check` | 文件 md5，维护本 batch 已见集合 | 同 batch 内唯一 |
> hard gate（四项全 hard）任一 fail → 该条进入重试/failed 流程，不入 completed。

---

## 7. 重试 / partial_done 策略
- 单条 variant QA fail → **自动重试 ≤2 次**：每次换「段方案 / 裁切种子 / 色调系数」（也提升差异化），重切重拼重检。
- 2 次后仍失败 → `final_status=failed`，**不进 completed**，标「需重做」。
- batch **允许 partial_done**：如 30 条里 28 pass / 2 failed → 返回 28 条可用 + 2 条 failed，**不因个别失败拖死整批**。
- MD5 重复也算 fail：重试时换差异化种子，直到唯一或标 failed。

---

## 8. 测试用例（`tests/verify_p1_1_remixer.py`，真实样本）
样本：母视频 **58 / 59 / 60**（或同类），**重点覆盖 60 秒 / 约 48MB 大视频**（真实文件，非压测——单文件、小批量）。
| # | 断言 |
|---|----|
| 1 | 30 条全部生成（count=30，输出 30 个 mp4） |
| 2 | **0 stuck**（无任务挂起；全部走完 QA） |
| 3 | **不再出现 14 秒卡死**：每条 `playback_validate` 通过（解码到结尾无 error） |
| 4 | 每条 **PTS 单调**（pts_check 通过） |
| 5 | 每条 **duration ∈ [25,35]** |
| 6 | 每条可播放到结尾（同 3） |
| 7 | **MD5 唯一数显著高于旧版**（理想：30 条全唯一；至少远高于旧版重复率） |
| 8 | **同策略下两条不能完全相同**（MD5 不同 + 段方案/字幕差异） |
| 9 | **cost=0**（cost_records / 不产生 precharge） |
| 10 | **不触发火山**（httpx 桩：若被调用即失败） |
| 11 | **ENABLE_COMPOSE=false**（配置不变） |
| 12 | partial_done：人为注入 1 条坏段 → 该条 failed、其余成功、batch 不崩 |
> 测试为「轻量真实样本」：单母视频小批量跑通，不做大批量/大文件压测。

---

## 9. 回归范围（必须复跑通过）
- `tests/test_b9_local_remix.py`（B 台本地裂变 / 0 成本 / provider=local_ffmpeg）。
- `tests/verify_v4_p1_remix.py`（P1 source_video_ids / 1:10 / 30-50 / cost=0）。
- `tests/verify_v4_p0.py`、`tests/verify_v4_reflow.py`（间接用 remix_videos：viral 落库 / expires_at / 回流）。
- `tests/verify_v4_p0a_p0b.py`、`verify_patch4/4.1/5/6`、`test_volcano_pipeline`（确认无连带破坏）。
> `remix_videos(...)` 对外返回结构保持兼容（仍含 local_path/title/strategy/store_id/duration/units=0/meta），仅 duration 现落在 [25,35]、meta 增 qa 字段——`b_service` 落库不需改。

---

## 10. 风险点
| 风险 | 缓解 |
|----|----|
| 全程重编码 → CPU/耗时上升 | preset veryfast + 受控并发；P1.1 先正确后性能（性能优化另开 P1.2） |
| 60s/48MB 大视频处理慢 | 单段 trim 后才重编码；目标只裁 [25,35]，不全量转码原片 |
| 无音轨/异常音频源 | anullsrc 补静音轨；aresample async 对齐 |
| 差异化过度→廉价 | 视觉手段叠加 ≤2，禁炫酷特效；以字幕/文字卡/轻转场为主 |
| 滤镜在个别样本失败 | 重试换种子；最终兜底仍走「整段重编码（非 -c copy）」，绝不回退 -c copy |
| MD5 仍偶发重复 | 重试换差异化种子直至唯一或标 failed |

---

## 11. 不做事项（P1.1 禁止）
- 不新增 production_order / shot_map / fission_plan / skill_registry / asset_pack / qa_result 等 **P2 大表**。
- 不改前端主流程；不接 Asset Supply Gateway；不接免费/付费素材 API；不接 HyperFrames/Remotion。
- 不触发火山；不解锁 ENABLE_COMPOSE；不碰 production；不做大文件压测；不改 cost_ledger；不接任何付费素材购买。
- **不保留 `-c copy` 快路径**（第一版全程重编码）。

---

## 12–15. 影响面确认
| 问题 | 结论 |
|----|----|
| **12. 是否需要前端改动** | **否**。返回结构兼容；前端裂变结果展示不变（duration 现为短视频值，QA 字段可选用）。 |
| **13. 是否需要 DB migration** | **否**。不新增表/列；`videos.duration_seconds` 已存在（P1），裂变落库照旧。 |
| **14. 是否触发火山** | **否**。纯本地 ffmpeg，cost=0；测试用 httpx 桩验证零调用。 |
| **15. 是否影响 production** | **否**。仅改 staging 分支 `b_engine/remixer.py` + 新增轻量 QA/测试；ENABLE_COMPOSE 保持 false；不部署、不碰 production。 |

---

## 交付边界
- 本文件为**方案文档**，不含代码改动。
- 审核通过后，P1.1 编码仅落在 §3 清单文件，产出 `BACKEND_V4_P1_1_REMIXER_FIX_REPORT.md` + 测试结果。
