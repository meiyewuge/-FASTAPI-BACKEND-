# 后端 V4 P1 · B台裂变真实工作流 代码报告

> 范围：**后端 only**（不改前端 / 不碰 production / 不触发真实火山压测 / 不大文件压测）。
> 依据：已通过复审的 `V4_P1_TECHNICAL_DESIGN.md`（L4）+ `V4_P1_INTERACTION_SPEC.md`（L3）+ `V4_P1_L2L3L4_REVIEW_FIX_REPORT.md`。
> 分支 `claude/v4-staging`。

## 1. commit 号
- **`143e6eb`**（`V4 P1: B台裂变真实工作流（duration_seconds + source_pool优先 + 1:10/30-50 + 0成本）`）。
- 已推送 `claude/v4-staging`。

## 2. 修改文件
| 文件 | 变更 |
|----|----|
| `models/video.py` | 新增 `duration_seconds FLOAT`（统一命名，**未新增 `duration`**） |
| `utils/video_probe.py`（新增） | `probe_duration(path)` ffprobe 探测，失败=None |
| `services/upload_service.py` | 上传 video 落库时 ffprobe 写 `duration_seconds` |
| `services/a_service.py` | A台单段落库写 `duration_seconds`（=请求 duration） |
| `services/compose_service.py` | A台 compose 落库写 `duration_seconds`（=total_seconds） |
| `services/b_service.py` | 裂变 viral 落库写 `duration_seconds`（ffprobe 成片） |
| `services/orchestrator.py` | `submit_b_batch` 重写：source_pool 优先 + 硬门槛 + 1:10 + 前5封顶 + ignored |
| `schemas/dto.py` | `BatchGenerateIn` 改 P1 标准字段（`source_video_ids/auto_ratio/max_outputs/strategy`），`sources/total_limit` 仅兼容 |
| `api/routes.py` | `/b/batch-generate` 适配新字段与返回；`/api/videos` 返回 `duration_seconds` |
| `tasks/backfill_duration.py`（新增） | 存量 `duration_seconds` 回填脚本 |
| `tests/verify_v4_p1_remix.py`（新增） | 14 项 P1 裂变验证 |
| `tests/verify_v4_p0.py` / `verify_v4_reflow.py` | 适配 P1 门槛（源视频 ≥30s + ≥3） |

## 3. DB migration SQL
```sql
-- 唯一 schema 变更：
ALTER TABLE videos ADD COLUMN duration_seconds FLOAT;   -- 单位秒；NULL=时长未知
-- 回滚：
ALTER TABLE videos DROP COLUMN duration_seconds;        -- SQLite<3.35 保留空列即可
```
> 全新库 / 测试库无需 ALTER（`create_all` 建表即含该列）。

## 4. 回填脚本路径
- **`backend/tasks/backfill_duration.py`**，运行：`cd backend && python -m tasks.backfill_duration`。
- 行为：扫 `storage_status='active' 且 duration_seconds IS NULL` 的视频，ffprobe 本地文件回填；找不到文件/探测失败 → 保持 NULL（= 时长未知，不计入合格源）。
- 已自测：3s 测试视频 → 回填为 `3.0`，`{scanned:1,updated:1,unknown:0}`。

## 5. duration_seconds 是否完成 —— ✅ 是
- 列已加；上传/A台单段/compose/裂变四处落库均写时长；`GET /api/videos` 返回 `duration_seconds`；回填脚本就绪。
- **统一命名 `duration_seconds`**，未引入 `duration` 字段（`cost_records.duration` 是无关既有列，未动）。

## 6. batch-generate 是否支持 source_video_ids —— ✅ 是
P1 标准请求体：
```json
{ "prompt":"抗衰主题", "source_video_ids":[11,12,13], "auto_ratio":10, "max_outputs":50, "strategy":"mix" }
```
返回：
```json
{ "batch_id":"...", "source_count":3, "total_outputs":30, "ignored_source_video_ids":[], "status":"queued", "cost":0 }
```

## 7. sources 是否仅做兼容 —— ✅ 是
- 旧字段 `sources`（`[{source_video_id,count,strategy}]`）后端内部映射为 `source_video_ids`，**仅兼容 P0，不推荐前端继续用**（测试第 9 项验证仍可用）。

## 8. ≥3 个 30 秒源视频硬门槛 —— ✅ 完成
- 合格判定：`tenant_id=当前租户 AND type='mother' AND storage_status='active' AND duration_seconds>=30`。
- `duration_seconds` 为 NULL（时长未知）或 `<30` **不计入合格源**。
- 合格源 `<3` → 返回 `code:2001`，中文 message：**「请至少上传 3 个时长 30 秒以上的视频，才能稳定裂变。」**
- **强制本租户**：`source_video_ids` 仅在本租户内筛，**super_admin 也不能用此接口跨租户混源**（测试第 8 项验证跨租户 → 2001）。

## 9. 1:10 / 30~50 条 —— ✅ 完成
- 3 合格源→30、4→40、5→50；每源 `auto_ratio`(默认10) 条。
- `total_outputs = min(used_source_count * auto_ratio, max_outputs)`，`max_outputs` 硬上限 50。

## 10. 超过 5 个源视频如何处理 —— ✅ 写死
- `used = 合格源[:5]`（保持传入 `source_video_ids` 顺序，前 5 个优先）；
- `used_source_count` 最大 5；`total_outputs = used_source_count * auto_ratio`（≤50）；
- 其余合格源记入返回的 **`ignored_source_video_ids`**（测试第 5 项：6 源→用前 5、total=50、ignored=[第6个]）。

## 11. 裂变结果是否进入 viral —— ✅ 是
- 每条产物：`type='viral'`、`source_type='remixed'`、`parent_video_id=source_video_id`、`batch_id` 正确、`expires_at=created_at+5天`、`storage_status='active'`、`cost=0`、`provider='local_ffmpeg'`。
- `GET /api/b/batch/{batch_id}`（done）返回 `{status:'done', completed, total_outputs, video_ids:[...]}`。
- `GET /api/videos?type=viral&batch_id=xxx` 可查到（测试第 10 项）。

## 12. A台 /api/compose 权限确认 —— ✅ 仍 require_auth
- `/api/compose` 依赖 `get_tenant_id`（基于 JWT，登录即可）；无 JWT → 401（测试第 14 项）。
- 不返回「请联系管理员操作」；保留 cost_engine / trial / subscription / quota / budget 保护（`submit_compose` 仍走 `ensure_budget` 熔断 4029、Patch5 试用扣减）。
- 本轮**未触发真实火山**（A台逻辑未改，仅确认权限）。

## 13. 测试结果
**`tests/verify_v4_p1_remix.py`（14/14 ✅）**：
```
✔ 2 个合格源 → 2001（门槛拒绝）
✔ 3 个合格源 → total_outputs=30, cost=0
✔ 4 个合格源 → total_outputs=40
✔ 5 个合格源 → total_outputs=50
✔ 6 个合格源 → 只用前5, total=50, ignored=[...]
✔ NULL 时长不计入合格源（→ 2001）
✔ <30 秒不计入合格源（→ 2001）
✔ source_video_ids 跨租户 → 2001（不混源）
✔ 旧字段 sources 仍兼容
✔ 裂变结果进入 viral 列表（batch done, 30 条, source_type=remixed）
✔ 裂变视频 expires_at ≈ created_at + 5 天
✔ B台成本=0 且 provider=local_ffmpeg（不调火山）
✔ /api/compose 无 JWT → 401（require_auth）
✔ Patch6 管理员权限不受影响
```
**全量回归（全部 ✅）**：`verify_v4_p0`（已适配 P1 门槛）、`verify_v4_closeout`、`verify_v4_reflow`（已适配）、`test_volcano_pipeline`、`test_b9_local_remix`、`verify_patch4/4.1/5/6`。
- 验证环境：本地 sandbox + 真实 ffmpeg/ffprobe + 小样本（**无真实火山 key、无大文件压测**）。

## 14. 是否可以交 Qoder 前端开发 —— ✅ 可以
- B台真实工作流后端打通：上传 3~5 合格源 → `POST /api/b/batch-generate {source_video_ids}` → 1:10 产 30~50 条 → 写 viral → `GET /api/videos?type=viral` 可查 → 成本 0。
- 前端按 `FRONTEND_V4_REDESIGN_API_CONTRACT.md` + L3/L4 对接即可（B台请求体改 `source_video_ids`，列表读 `duration_seconds`，门槛文案见 L3）。

**联调注意**
1. 生产/staging 部署须执行 `ALTER TABLE videos ADD COLUMN duration_seconds FLOAT;` + **强制** `python -m tasks.backfill_duration`（存量视频时长回填；NULL 不计入合格源）。
2. 所有接口带 `Authorization: Bearer <JWT>`。

## 未做（按指令归档）
- 90~120s 裂变成片深度优化 → **P1-B**（remixer ffmpeg `-t`）。
- 素材库 / 阿里云大库正式导出 / 真实火山大批量压测 / 大文件压测 → **P2 / 不做**。
