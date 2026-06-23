# 工作流与分支策略 · workflow.md

## 1. A台流程（母视频生产）

```
一句话需求
  → services 编排
  → AI 生成脚本
  → tasks 投递视频生成任务
  → a_engine 调用视频生成
  → 输出 1 条精品母视频
  → 写入 models（带 tenant_id） + 生成 下载/分发 链接
```

## 2. B台流程（混剪裂变）

```
选择母视频
  → tasks 投递混剪任务
  → b_engine：
      自动切片 → 重组 → 改字幕 → 改开头 → 改结尾
  → 输出 10~50 条裂变视频
  → 批量写入 models + 生成分发链接（多账号矩阵）
```

## 3. 任务系统

- 入口：`backend/tasks/video_task.py`
- API 只投递任务并返回 `task_id`，真实生成在 worker/队列中执行。
- 状态机：`pending → running → done | failed`。

## 4. Git 分支策略（强制）

| 分支 | 用途 |
| --- | --- |
| `main` | 生产环境，只接受经评审的合并 |
| `dev` | 开发集成环境 |
| `feature/a` | A台（母视频）开发 |
| `feature/b` | B台（混剪）开发 |
| `feature/ui` | 前端 UI（Qoder） |

> 工程铁律：**先定 Git 结构，再写代码，而不是写代码再整理结构。**

## 5. 协作边界

- 前端只碰 `frontend/`，通过 `/api/*` 对接。
- A台只碰 `backend/a_engine/`，B台只碰 `backend/b_engine/`，互不 import。
- 跨模块协作一律经 `backend/services/` 编排或 `/api`。
