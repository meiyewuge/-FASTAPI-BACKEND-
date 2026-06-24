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

## stores —— 门店（tenant 内 target，**不是租户**）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, PK | store_id |
| tenant_id | str, index | 所属租户（客户） |
| name | str | 门店名 |
| city | str | 城市 |
| industry | str | 行业（美容院/皮肤管理/医美/养生…） |
| created_at | datetime | |

## videos —— 母视频 / 裂变视频
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int, PK | |
| tenant_id | str, index | 租户隔离 |
| store_id | int, index, null | 归因到门店 |
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
| store_id | int, index, null | 单店任务指向门店；批量子任务也带 store_id |
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
| store_id | int, index, null | 门店归因 |
| api_name | str | 如 `video.generate.a` / `video.remix.b` |
| provider | str | 实际 provider，如 `volcano_seedance` / `mock` |
| task_id | str, index, null | 关联任务 |
| units | float | 调用量 |
| amount | float | 金额 |
| created_at | datetime | |

## 三层结构（系统核心模型）
- **tenant 层（商业层）**：客户 / 计费 / 配额。`tenant = 客户，不是场景`。
- **store 层（业务层）**：门店 / 内容目标。`store = 任务对象，不是租户`。
- **task 层（执行层）**：A台 / B台 视频生成执行单元。
- 关系：`Tenant 1→N Store`，`Tenant 1→N Task`，`Store 1→N Task`。

## 关系与隔离
- 一个 `tenant` → 多个 `stores` / `videos` / `tasks` / `cost_records`。
- `videos.source_video_id` → `videos.id`（裂变 → 母视频）。
- 成本熔断：`sum(cost_records.amount where tenant_id) + 预估 > tenants.quota` 即拒绝。
- 所有查询强制带 `tenant_id`，杜绝跨租户（见 `api/deps.get_tenant_id`）。
