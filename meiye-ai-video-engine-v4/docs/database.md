# 数据库结构 · database.md

默认 SQLite（零依赖即可运行），生产可切 PostgreSQL（改 `DATABASE_URL`）。
所有业务表均含 `tenant_id`（默认 `default`），用于 SaaS 多租户隔离。
ORM：SQLAlchemy 2.0，模型见 `backend/models/`。

## tenants —— 租户 + 成本配额
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | str, PK | tenant_id |
| name | str | 名称 |
| quota | float | 成本配额（货币单位），熔断依据，默认 100 |
| created_at | datetime | |

## videos —— 母视频 / 裂变视频
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, PK | |
| tenant_id | str, index | 租户隔离 |
| type | str | `mother` \| `viral` |
| title | str | |
| source_video_id | int, null | 裂变视频指向其母视频 |
| status | str | 默认 `ready` |
| download_url | str | 下载链接 |
| share_url | str | 分发链接 |
| meta | text(JSON) | 脚本/分镜/改动方案 |
| created_at | datetime | |

## tasks —— 异步任务
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | str(uuid), PK | task_id |
| tenant_id | str, index | |
| type | str | `a` \| `b` |
| status | str | `pending`\|`running`\|`done`\|`failed` |
| progress | float | 0~1 |
| payload | text(JSON) | 输入 |
| result | text(JSON) | 产出（video ids/urls） |
| error | text | 失败原因 |
| retry_count | int | 重试次数 |
| created_at / updated_at | datetime | |

## cost_records —— 成本记录
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, PK | |
| tenant_id | str, index | |
| api_name | str | 如 `video.generate.a` / `video.remix.b` |
| task_id | str, index, null | 关联任务 |
| units | float | 调用量 |
| amount | float | 金额 |
| created_at | datetime | |

## 关系与隔离
- 一个 `tenant` → 多个 `videos` / `tasks` / `cost_records`。
- `videos.source_video_id` → `videos.id`（裂变 → 母视频）。
- 成本熔断：`sum(cost_records.amount where tenant_id) + 预估 > tenants.quota` 即拒绝。
- 所有查询强制带 `tenant_id`，杜绝跨租户（见 `api/deps.get_tenant_id`）。
