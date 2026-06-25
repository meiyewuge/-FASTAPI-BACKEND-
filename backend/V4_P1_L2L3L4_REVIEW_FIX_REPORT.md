# V4 P1 · L2/L3/L4 ChatGPT 审核意见修订报告

> 阶段：文档收口（**不写业务代码、不改 production、不触发火山、不压测**）。
> 修订对象：`V4_P1_WIREFRAME_PROTOTYPE.html`、`V4_P1_INTERACTION_SPEC.md`、`V4_P1_TECHNICAL_DESIGN.md`、`V4_P1_L2L3L4_DELIVERY_REPORT.md`。

## 逐条落实（对照 ChatGPT 九条意见）

### 1. A台主按钮是否已统一为 `/api/compose` —— ✅ 已统一
- **L2**：主工作台「🟠 A台·母视频」按钮 API 标注由 `/api/a/generate` 改为 **`POST /api/compose`**；A台费用确认弹窗的提交标注改为 `POST /api/compose（文字+图片→多段15s→后端自动拼接）`。
- **L3**：A台按钮状态机「确认中」→ 调 `POST /api/compose`；新增备注「A台主入口=compose，`/api/a/generate` 仅底层单段/技术备用」；§6.2 一键成片流程改为 compose。
- **L4**：§3.3 升级为 **`POST /api/compose`（A台主工作台默认入口）**；§3.4 把 `/api/a/generate` 明确为「底层单段生成/技术备用接口，非主入口」；权限表新增 compose 行。
- **费用文案**：固定 ¥1.50 全部删除，统一为 **「A台会调用火山API生成母视频，具体费用以实际扣费为准。确认继续吗？」**（L2/L3/L4 一致）。

### 2. B台 source_pool 优先级是否已写清 —— ✅ 已写清（三层）
三层优先级（L2 注释 + L3 §1.2/§6.3 + L4 §3.1/§6 伪代码均体现）：
1. **优先**：本次会话刚上传/刚生成的视频 `current_source_video_ids`。
2. 用户在「高级选择」手动更换 → 用用户指定 id。
3. `source_video_ids` 为空时**后端才 fallback** 到本租户最近合格历史源。
- 明确「**不再让后端默认盲扫全租户历史视频**」。
- L3 §6.1 上传成功后「加入 `current_source_video_ids`」已写入。

### 3. B台请求字段是否统一为 `source_video_ids` —— ✅ 已统一
P1 标准请求体（L4 §3.1，L2/L3 同步）：
```json
{ "prompt":"抗衰主题", "source_video_ids":[11,12,13], "auto_ratio":10, "max_outputs":50, "strategy":"mix" }
```
- 旧字段 `sources`：**仅兼容 P0，不推荐前端继续用**（L4 写明后端内部兼容映射）。
- `source_video_ids` 为空 → 后端 fallback 自动选源。
- `total_outputs = min(len(合格 source_video_ids) * auto_ratio, max_outputs)`。

### 4. 30 秒硬门槛是否已写清 —— ✅ 已写清
- 合格源视频：**`duration_seconds >= 30`（硬门槛）**；`<30s` 或 `NULL（时长未知）`**不计入合格源**。
- 合格源 < 3 → **B台不可用**；前端提示 **「请至少上传 3 个时长 30 秒以上的视频，才能稳定裂变」**。
- L3 边界表、L4 §13 业务规则、L4 §6 伪代码三处一致。

### 5. `duration_seconds` 命名是否已统一 —— ✅ 已统一
- 采用方案：**DB 列名 = `duration_seconds`，API 返回字段 = `duration_seconds`（同名）**。
- L4 §0 显式声明命名规范，并提示 `cost_records.duration` 是既有成本时长列、与此无关、不改名。
- 全文不再出现裸 `videos.duration`（已校验 0 处）。

### 6. staging 回填脚本是否已写入部署清单 —— ✅ 已写入（且改为强制）
- L4 §10 部署清单新增 **Step 4b（必须）** 运行 `python -m tasks.backfill_duration`（ffprobe 扫存量本地文件写 `duration_seconds`）。
- 空值处理：`duration_seconds` 为空 → 不计入合格源；回填失败 → 保持 NULL，前端显示 **「时长未知（需重新上传或等待解析）」**。
- L4 §2 数据迁移段、§12 范围表同步标注「强制回填」。

### 7. P1-B / P2 范围是否已重新划分 —— ✅ 已重新划分
- **本轮核心**：`duration_seconds` 列+回填、B台 source_pool 优先+1:10（30/40/50）+`source_video_ids`、`/api/videos` 返回 `duration_seconds`、A台主入口 compose、前端删文本/蓝按钮/取消勾选/维护源池。
- **P1-B（不并入本轮核心）**：B台裂变成片 **90–120s** ffmpeg `-t` 时长优化；A台参考图真正图生视频（待真实 key）。
- **P2**：素材库 `/api/stock-library/*`、zip 深解析/rar/OSS、回流 approved→阿里云大库导出器。

### 8. 候选池维持平台级审核 —— ✅ 维持
- super_admin 看全局候选池；user/invite_admin **不显示候选池**；feedback 仅生成 `pending` 候选；**不直接写阿里云正式大库**（L4 §13 + L2 候选池区 + L3 §0 角色表一致）。

### 9. 重新输出修订版 —— ✅ 已输出
四份文件已更新 + 本报告 `V4_P1_L2L3L4_REVIEW_FIX_REPORT.md`。

---

## 是否可以再次交 ChatGPT 审核 —— ✅ 可以
九条意见已逐条落实，三份文档内部一致、命名统一、与真实代码对齐。可再次整体交 ChatGPT 复审。

## 修订后仍保留的事实澄清（提醒）
- **A台后端从来就是 `require_auth`**（非 require_super_admin），「取消授权卡控」在后端无守卫可改，仅前端文案/交互调整 + A台主入口切到 compose。此点在 L4 §0/§4 已显式写明，避免复审误判为「后端漏改」。
- `videos.duration_seconds` 是 P1 唯一 DB schema 变更（ALTER + 强制 ffprobe 回填），SQL/回滚/迁移/空值处理均已在 L4 写全。

## 仍需吴哥拍板（缩减后）
1. A台费用是否需要在确认弹窗附带实时余额（`quota_remaining`）展示，还是仅文案提示（当前文档为「仅文案，不写固定单价」）。
2. 90–120s 裂变成片（P1-B）是否要紧接本轮排期。

---

### 约束遵守自查
- ✅ 仅改文档（含可点击原型 HTML），未写业务代码
- ✅ 未改 production、未触发火山、未大文件压测、未泄露密钥
- ✅ 四份文件 + 本报告将推送 `claude/v4-staging`
