# 后端冻结版本 · V4 (B1~B9)

> 🔒 **状态：冻结（FROZEN）**。后端 B 类功能开发到此为止，**不再新增功能**。
> 此后仅允许：bug 修复 / 部署适配 / 合并到 ECS。新能力进入下一阶段（Qoder 前端 + 扣子部署）。

- **分支**：`claude/ecs-b-fixes`（基于 ECS 真实生产快照 `ecs-production-snapshot`）
- **基线**：你 ECS `/opt/v4-video-engine/backend/` 正在跑的代码（含真火山 + 按秒计费）

## 核心架构（B9 修正后定型）
- **A台 = 火山豆包视频2.0**（花钱出高质量母视频，按秒计费）
- **B台 = 纯本地 ffmpeg 裂变**（切片/重组/文案叠加，**0元/条，不调火山**）

## 冻结内容（9 项，逐项独立 commit，均已验证）
| commit | 项 | 内容 |
| --- | --- | --- |
| `3bea370` | B1 | 火山签名URL刷新（task_id落库+过期重查）；附带修复 fallback→mock 崩溃隐患 |
| `37755af` | B2 | 视频本地存储（mother/viral 双存，download_url 本地优先，根治24h过期） |
| `6b574ce` | B4 | Intent误判修复（「15秒」→duration 而非 count，计费灾难bug）+ duration/resolution 透传 |
| `9e8256f` | B8 | 视频封面（ffmpeg 抽首帧 → cover_url） |
| `340da61` | B7 | B台含视频输入（火山video-to-video）—— **已被 B9 取代**，B台不再走火山，此改动对 B台 失效（保留不影响 A台） |
| `91fd7fc` | B6 | 长视频多段拼接（切片→逐段生成→ffmpeg concat→完整成片） |
| `f0fb8ae` | B3 | 进程内任务恢复（启动扫 pending/running 任务重跑，防 systemd 重启丢任务） |
| `04d3733` | B5 | build_script 接 LLM（可插拔 rule/llm，失败回退规则版） |
| `e41fd1d` | **B9** | **B台架构修正：纯本地 ffmpeg 裂变，不走火山，0元/条**（remixer 重写 + b_service 取本地母视频） |

## 新增对外接口（给 Qoder/扣子）
- `GET  /api/videos/{id}/url` —— 取可用播放/下载URL，过期自动刷新（B1）
- `POST /api/compose { prompt, total_seconds, resolution }` —— 长视频一次成型（B6）
- `GET  /api/videos` 返回项新增 `cover_url`（B8）
- `POST /api/a/generate` / `/api/generate` 支持 duration/resolution（B4）

## 合并到 ECS 清单（必做，不动 .env 的 VIDEO_PROVIDER/Key）
1. **DB 迁移**（SQLite 加 4 列）：
   ```sql
   ALTER TABLE videos ADD COLUMN volcano_task_id VARCHAR(64);
   ALTER TABLE videos ADD COLUMN cdn_url   VARCHAR(1024);
   ALTER TABLE videos ADD COLUMN local_url VARCHAR(512);
   ALTER TABLE videos ADD COLUMN cover_url VARCHAR(512);
   ```
2. **ffmpeg + 中文字体**：`apt install -y ffmpeg fonts-wqy-zenhei`
   （字体供 B9 的 B台文案叠加；缺失则自动跳过叠加，不报错）
3. **.env 追加**：
   ```
   STORAGE_ENABLED=true
   STORAGE_DIR=/opt/v4-video-engine/storage/videos
   STORAGE_BASE_URL=https://video.beautypeaceai.com/static/videos
   # 可选 B5：SCRIPT_PROVIDER=llm / LLM_API_KEY=... / LLM_API_BASE=https://api.deepseek.com/v1
   ```
4. **nginx 静态**：`location /static/videos/ { alias /opt/v4-video-engine/storage/videos/; }`
5. **重启**：`systemctl restart v4-video-engine`

## 成本（B9 后）
- A台：火山按秒计费（720P 1元/秒 等，由 cost_engine per-second 计价）
- B台：**0元/条**（纯本地 ffmpeg，`provider=local_ffmpeg`，amount=0）

## 合并前需你校准的 1 点
- **B3 恢复**：为「至少恢复」（重跑残留任务），极端情况 running 任务重跑可能重复产出；严格去重需后续接 Celery/RQ。
- （B7 火山视频输入字段已无需校准——B9 后 B台不走火山。）

## 验证基线（沙箱，真跑）
- B1/B2/B4/B8/B6/B9 端到端 + B3/B5 单元 —— 全通过
- `tests/test_volcano_pipeline.py`（已适配 B9）—— 无回归
- ffmpeg 真切片/拼接/抽帧/裂变、http 桩真下载

## 冻结边界（不在本版，属下一阶段）
- ❌ 前端 F1~F8（Qoder）
- ❌ 平台层 O1~O5（分镜LLM编排/并行调度/质检/成本护栏UI）
- ❌ 真实 LLM/火山 key 联调（需在 ECS .env 配置）
- ❌ 异步队列升级（Celery/RQ）、成本熔断UI、防刷限流
