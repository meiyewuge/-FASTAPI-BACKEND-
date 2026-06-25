# 前端迁移要点（Qoder）· V4 P0-B A台导演稿预览

> 一页速查。配套 `BACKEND_V4_P0A_P0B_DIRECTOR_ENGINE_REPORT.md` + `FRONTEND_V4_REDESIGN_API_CONTRACT.md`。
> 后端分支 `claude/v4-staging`（已就绪，但 **A台真生成默认锁住**，见 §5）。所有接口带 `Authorization: Bearer <JWT>`。

---

## 0. A台新流程（核心：先预览，再确认，才生成）

```
用户写文案 + 传图片 + 选风格
   ↓  POST /api/compose/preview   （不花钱，不调火山）
展示导演分镜 + 提示词 + 图片角色 + 费用预估
   ↓  用户确认费用
   ↓  POST /api/compose  { director_plan_id, confirmed_cost:true }
（后端未解锁时返回 4031「生成通道维护中，暂不可用。」→ 前端置灰提示）
```
> **不能**点 A台直接调 `/api/compose` 生成——必须先 preview 拿 `director_plan_id`，避免大白话解析错误直接烧钱。

---

## 1. `POST /api/compose/preview` —— 导演稿预览（不花钱）

### 请求
```json
{ "prompt":"达芙荻丽奢华油，夏季干皮上妆卡粉救星，99%天然植萃",
  "image_file_ids":["fid1","fid2","fid3"],   // 来自 /api/uploads/batch；可空=纯文生
  "style":"premium",                          // premium | fresh | chinese
  "ratio":"9:16", "duration":15, "resolution":"1080p" }
```
### 返回 `data`
```json
{
  "director_plan_id":"...",                    // ★ 正式生成要用它
  "director_plan":{
    "brand_context":{ "brand":"...","product":"...","selling_points":[...],"slogan":"..." },
    "storyboard":[ {"index":1,"timecode":"0-4秒","description":"...","line":"...","image_ref":"first_frame"}, ... ],
    "versions":{ "director_prompt_version":"director_prompt_v1", ... }
  },
  "seedance_text_prompt":"【T1-产品定格】...【T5-禁止项】...",  // 可折叠展示给用户看
  "seedance_content":[ {"type":"text",...}, {"type":"image_url","image_url":{"url":...},"role":"first_frame"}, ... ],
  "image_roles":[ {"file_id":"fid1","role":"first_frame","url":"https://..."}, {"file_id":"fid2","role":"reference_image",...} ],
  "estimated_cost":37.20,                      // ★ 费用确认弹窗用
  "ratio":"9:16","resolution":"1080p","duration":15,
  "generate_audio":true,
  "warnings":["未提供图片，将使用纯文生模式..."]  // 有则提示用户
}
```
- **异步**：否。**花钱**：否。**失败阻断**：是（preview 失败不能进入生成）。
- 图片不可访问 → `code:2002`，message =「图片无法被视频模型访问，请重新上传或等待处理完成。」直接弹给用户。

---

## 2. 图片角色展示（image_roles）

每张图用 `image_roles[].role` 标注：
- `first_frame`（第 1 张）→ 角标「首帧」，提示「视频开场画面以此图为准」。
- `reference_image`（第 2-9 张）→ 角标「参考图」，提示「锚定产品外观」。
> 上传顺序决定角色：**第 1 张自动成首帧**。前端可让用户拖拽调整顺序（顺序即角色优先级）。

---

## 3. 导演稿 / 提示词展示（给用户「看得见的导演」）

- `director_plan.storyboard[]` → 渲染分镜卡片（镜头号 / 时码 / 画面描述 / 台词）。
- `seedance_text_prompt` → 可折叠「查看完整提示词（T1-T5）」，让用户确认品牌名/卖点没解析错。
- 若 `brand_context.brand` 为空或错 → 提示用户「未识别到品牌名，建议在文案开头写清品牌+产品」。

---

## 4. 费用确认（不写固定单价，用 estimated_cost）

- preview 返回 `estimated_cost`（元，按秒×分辨率实算，如 1080p 15s = 37.20）。
- 确认弹窗文案：`本次生成预计消耗 ¥{estimated_cost}（以实际扣费为准）。确认继续吗？`
- 用户确认 → 调 `/api/compose`，**必须带 `confirmed_cost:true` + `director_plan_id`**。

---

## 5. `POST /api/compose` —— 正式生成（受控，默认锁）

### 请求
```json
{ "director_plan_id":"...", "confirmed_cost":true, "total_seconds":15 }
```
### 可能返回
| code | 含义 | 前端处理 |
|----|----|----|
| 0 | 已受理 `{task_id, director_plan_id}` | 轮询 `GET /api/tasks/{task_id}` |
| 4031 | 「生成通道维护中，暂不可用。」（ENABLE_COMPOSE=false） | A台生成按钮置灰 + 显示该文案 |
| 2001 | 未确认费用 / 缺 director_plan 和 prompt | 提示先 preview + 确认 |
| 2002 | 图片不可访问 | 提示重新上传 |
| 4029 | 余额/试用/额度不足 | 提示充值/联系 |
| 3001 | director_plan 不存在/过期 | 重新 preview |

> **当前后端 ENABLE_COMPOSE 默认 false**：A台「生成」按钮可显示，但点击大概率收到 4031。前端按钮可常驻，拿到 4031 即置灰并提示「生成通道维护中」。解锁由运维在 .env 设 `ENABLE_COMPOSE=true` 后开放。

---

## 6. localStorage 草稿（BUG-3 第三层）

- 监听 `prompt` / `image_file_ids` / `style` 变化，debounce 500ms 写 localStorage。
- 页面加载恢复草稿（避免刷新丢内容）。
- 提交成功（拿到 task_id）后清除草稿。
- 注意：localStorage 存 `image_file_ids`（已上传的 id），不存图片二进制。

---

## 7. 改动清单（给 Qoder 排期）
| 改动 | 优先级 |
|----|----|
| A台流程改「先 preview 后 compose」（不直接生成） | 必改 |
| 调 `/api/compose/preview` 并渲染分镜/提示词/image_roles/估价 | 必改 |
| 费用确认弹窗用 `estimated_cost`（不写固定单价） | 必改 |
| `/api/compose` 带 `director_plan_id + confirmed_cost` | 必改 |
| 4031 → A台按钮置灰 +「生成通道维护中，暂不可用。」 | 必改 |
| 2002 图片不可访问错误透传 | 必改 |
| localStorage 草稿（prompt+图片id+风格，提交后清） | 必改 |
| 图片角色角标（首帧/参考图）+ 拖拽排序 | 建议 |
| 风格选择器（premium/fresh/chinese） | 建议 |

---

## 8. 不变 / 复用
- 上传仍 `POST /api/uploads/batch`；图片上传后 `file_id` 用于 preview。
- B台裂变（`source_video_ids`）、列表 `duration_seconds`、删除、storage scope、track/feedback/候选池 → 见 `FRONTEND_V4_REDESIGN_API_CONTRACT.md` 与 `FRONTEND_V4_P1_QODER_MIGRATION_NOTES.md`，本轮不变。
