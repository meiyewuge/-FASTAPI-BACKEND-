# 文案加工厂服务骨架与 9080 只读召回设计 V0.1

- **版本**: V0.1
- **产出日期**: 2026-07-04
- **状态**: 草案（M1 W1/W2 骨架阶段）
- **代码实现**: `backend/app/content_factory/`（分支 `qoder/m1-w1-w2-factory-skeleton-recall`）
- **前置依赖**: W0.5 模型路由与兜底层（PASS，commit 6ba819d）

---

## 一、定位

文案加工厂是四层架构的第三层编排者：

| 层级 | 名称 | 实现状态 |
|---|---|---|
| 第一层 | Brief 理解层 | W1 骨架 |
| 第二层 | 9080 召回层 | W2 骨架（mock） |
| 第三层 | 大模型生成层 | W0.5 PASS（mock） |
| 第四层 | G1-G6 六硬门 | W4 待实现 |

**核心公式不变：库负责"真"，模型负责"会写"，合规门负责"不能乱"，人负责"值不值得发"。**

---

## 二、W1 服务骨架

### 2.1 Brief 数据结构

```python
Brief(raw_text, task_type, platform, target_audience, risk_hint, batch_id, brief_id, trace_id)
```

- `task_type` 复用 `model_router.TaskType`
- `brief_id` / `trace_id` 自动生成

### 2.2 批量 Brief 输入

- `parse_brief(raw)` 单条解析
- `parse_batch_briefs(raw_list)` 批量解析，自动分配 batch_id

### 2.3 任务状态机

6 态流转：`queued → producing → gated → packaged → in_review → closed`

- 不允许跳态
- 不允许倒退
- 每次转换记录 timestamp + operator
- `closed` 为终态

### 2.4 工厂主编排

`ContentFactory.process_brief(brief)` 串联：

1. Brief 解析 → TraceContext
2. 9080 召回（W2 mock）
3. 模型路由出稿（W0.5 已实现，骨架调用）
4. 六硬门质检（W4 TODO）
5. 打包（W3 TODO）
6. 写入 content_staging

### 2.5 content_staging 私有目录

内存存储，提供 put / get / list_by_brief / list_by_state。

### 2.6 三 ID 溯源

trace_id + task_id + brief_id 三 ID 绑定，每条内容全程可追溯。

---

## 三、W2 9080 只读召回

### 3.1 召回客户端

- `RecallClient` Protocol：可插拔
- `MockRecallClient`：返回预置脚本数据
- `RecallConfig(base_url="mock", mock=True)`：默认 mock

### 3.2 召回结果

四种状态：`approved / candidate / missing / blocked`

### 3.3 白名单过滤

默认白名单：`fact_card / compliance_rule / style_template / engine_asset`

### 3.4 黑名单过滤

默认黑名单：`draft / rejected / archived`

### 3.5 used_materials 绑定

- `bind_materials(recall_result, brief)` → `BoundMaterials`
- 素材充分性判定（按 task_type 最低数量要求）
- 缺料报告桥接 `model_router.MissingMaterialReport`

### 3.6 source_refs 溯源

`SourceRef(material_id, source_type, source_version, recalled_at)`

来源类型：`9080_approved / compliance_lib / style_lib / engine_asset`

### 3.7 召回日志

14 个必记字段，内存存储。

---

## 四、严禁事项

1. 不合并 main
2. 不部署
3. 不启动 M1
4. 不开 /content/generate
5. 不接真实发布池
6. 不自动发布
7. 不推送网站
8. 不自动提交外部 AI 平台
9. 不写 approved
10. 不 reindex
11. 不直连 9200
12. 不接真实模型供应商
13. 不把 Kimi 稿当正式稿
14. 不把平台灵感当事实
15. 不把 missing 字段用于正文事实
16. 不进入 W4 六硬门正式开发

---

## 五、版本

| 版本 | 日期 | 变更 |
|---|---|---|
| V0.1 | 2026-07-04 | 初版，W1 骨架 + W2 召回适配 |
