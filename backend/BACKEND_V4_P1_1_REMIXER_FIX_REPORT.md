# 后端 V4 P1.1 · Remixer PTS / 去重 修复报告

> 范围：**B 台短视频裂变止血**。只改 `b_engine/remixer.py` + 新增 QA/测试。
> 硬约束守住：B 台 `cost=0`；`ENABLE_COMPOSE=false`；A 台真实 compose 锁住；不触发火山；**production 零影响**；不建 P2 表、不改前端、不接素材、不部署。

## 1. commit
- 见推送结果（`fix: P1.1 Remixer 短视频 PTS/去重 全程重编码 + QA + 重试/partial`）。分支 `claude/v4-staging`。

## 2. 修改 / 新增文件
| 文件 | 动作 |
|----|----|
| `b_engine/remixer.py` | **重写主流程**：废弃 `_slice()/_concat(-c copy)`/`-c:a copy`，改 trim+setpts/atrim+asetpts/filter_complex 全程重编码 + [25,35] + 多维差异化 + QA/重试/partial |
| `b_engine/qa_checks.py`（新增） | `duration_check / pts_check(best_effort 兜底) / playback_validate / md5_duplicate_check` + `run_gates` |
| `tests/verify_p1_1_remixer.py`（新增） | 真实样本（60s 带音轨）30 条全链路验证 |
| `config.py` | 新增 `b_remix_target_lo/hi(25/35) / duration_tol / width(1080) / height(1920) / fps(30) / max_retry(2)` |
| `tests/*`（6 个 remix 用例） | 仅加「裂变目标/分辨率调小」提速开关（速度，不改断言；生产口径不变） |
> `services/b_service.py` **未改**；`remix_videos()` 对外返回结构兼容（local_path/title/strategy/store_id/duration/units/meta），QA 放 `meta["qa"]`，批级汇总放最后一条 `meta["qa_summary"]`。

## 3. 旧流程问题（基于真实代码）
- `_slice()`：`-c copy -f segment` 非关键帧切点 + GOP 不规则。
- `_concat()`：`concat -c copy` 拼接处 **PTS 非单调** → 30 秒视频 **14 秒后卡死** / duration 异常。
- `_render_variant()`：`-c:a copy` 音频直拷 → A/V 失步、尾段卡顿。
- 去重仅 crop 4 档 + 段轮转 → 同策略高相似 / **MD5 重复**。
- 无时长控制、无任何 QA。

## 4. 新流程说明
```
remix_videos: probe(dur,has_audio)
 for i in count, retry≤2:
   选策略 → 选段方案/seed → 单次 ffmpeg：
     LONG(dur≥9): trim+setpts 三段重排(重复到≥target) → filter_complex concat
     SHORT(dur<9): stream_loop 补足 → setpts 规范化
     无音轨→anullsrc 静音；有音轨→atrim+asetpts 重采样
     差异化叠加：crop + eq(色调) [视觉≤2] + fade(轻转场) + drawtext(策略字幕/CTA)
     -t target∈[25,35]，libx264 veryfast，统一 fps/scale/SAR/44100，+faststart（全程重编码）
   QA run_gates(duration/pts/playable/md5)；pass→入 outputs；fail→换 seed 重试；仍失败→剔除
 partial_done：失败不入 outputs，batch 不拖死
```
**第一版禁止任何 `-c copy` 快路径**（含单源单段，一律重编码）。

## 5. FFmpeg 命令模板（实测生效）
```bash
# LONG（三段重排 + 概念示意，单次 ffmpeg）
ffmpeg -y -i src.mp4 -filter_complex "
 [0:v]trim=start=S0:end=E0,setpts=PTS-STARTPTS,fps=30,scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1[v0];
 [0:a]atrim=start=S0:end=E0,asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[a0];
 ... ;
 [v0][v1]...concat=n=K:v=1:a=0[vc]; [a0][a1]...concat=n=K:v=0:a=1[ac];
 [vc]crop=...,eq=saturation=..:brightness=..,fade=t=in:st=0:d=0.3,drawtext=..,drawtext=..[vout]" \
 -map "[vout]" -map "[ac]" -t <target∈[25,35]> \
 -c:v libx264 -preset veryfast -pix_fmt yuv420p -r 30 -c:a aac -ar 44100 -ac 2 -movflags +faststart out.mp4
# SHORT：ffmpeg -y -stream_loop N -i src.mp4 -filter_complex "[0:v]setpts...,scale..,pad..[vc];[vc]crop..,eq..,drawtext..[vout]" -map [vout] -map [ac] -t <target> ...（无音轨用 anullsrc）
# 校验：ffmpeg -v error -i out.mp4 -f null -    ；   ffprobe ... frame=best_effort_timestamp_time,pkt_pts_time,pts_time
```

## 6. 证据（`tests/verify_p1_1_remixer.py`，真实 60s 母视频，30 条）
- **PTS 修复证据**：每条 `pts_check` 通过（best_effort_timestamp_time → pkt_pts_time → pts_time 兜底取值；检测时间回退/重复/异常跳跃，全 0）。
- **playback 验证证据**：每条 `ffmpeg -v error -f null -` 无 error（可完整解码到结尾，**不再 14 秒卡死**），并二次独立复验。
- **duration 验证证据**：每条 duration ∈ [25,35]。
- **MD5 去重证据**：**30/30 全唯一**；同策略下 MD5 不全相同。
- **30 条生成结果**：30 条全部生成，0 stuck。
- **failed / partial_done 结果**：QA 强制失败场景下 0 条入 outputs，batch 不报错、不拖死。
- **cost=0**：units=0，provider=local_ffmpeg。
- **未触发火山**：测试中 httpx.post/get 设陷阱，未触发。
- **ENABLE_COMPOSE=false**：保持。
- **production 零影响**：仅改 staging 分支引擎 + QA/测试，不部署、不碰 production。

## 7. 测试命令与结果
```bash
cd backend && python tests/verify_p1_1_remixer.py
# ✅ 30 条全生成 / PTS 单调 / 可播放到结尾 / duration∈[25,35] / MD5 30-30 唯一 / 同策略不同 / cost=0 / 不触发火山 / ENABLE_COMPOSE=false / partial_done
```
回归（全过）：`test_b9_local_remix`、`verify_v4_p1_remix`、`verify_v4_p0`、`verify_v4_reflow`、`verify_patch5`、`test_volcano_pipeline`、`verify_v4_closeout`、`verify_v4_p0a_p0b`、`verify_patch4/4.1/6`。
> 回归用例对 remix 路径加了「目标时长/分辨率调小」的提速开关（仅测试速度，生产默认仍 [25,35]/1080×1920）。

## 8. 影响面确认
| 项 | 结论 |
|----|----|
| 是否需要前端改动 | **否**（返回结构兼容） |
| 是否需要 DB migration | **否**（不新增表/列） |
| 是否触发火山 | **否**（纯本地 ffmpeg，httpx 陷阱验证零调用） |
| 是否影响 production | **否**（仅 staging 分支，未部署，ENABLE_COMPOSE 保持 false） |
| 是否保留 -c copy 快路径 | **否**（第一版全程重编码） |

## 9. 未做（按边界）
不新增 P2 大表 / 不改前端主流程 / 不接 Asset Supply Gateway / 不接素材 API / 不接 HyperFrames·Remotion / 不改 cost_ledger / 不解锁 compose / 不大文件压测 / 不部署。
> 性能优化（并发、预设、单源单段快路径评估）留 **P1.2**。

## 10. 交付
本轮完成代码 + 自测 + 回归，**不部署**，先交 ChatGPT 审核。
