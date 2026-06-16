# MWUZS_RUNTIME_BASELINE_CHAT_COZE_WIRING_STEP1_REVIEW

> 工单：CHAT_COZE_WIRING_STEP1 审查包 ｜ **只做 chat**，未合 main/未 push/未部署/Coze 未介入。
> base：`main`（`ab29dc5`） → target：`fix/chat-coze-wiring-step1`（代码提交 `04bc8ba`）

## 1. 只做了 chat
本轮仅把 `POST /api/ai/chat` 从硬编码模板改成「真实 Coze Bot 调用 + 灰度 + 降级 + 真实标签」。**未碰 private、未碰 content、未迁 manager、未动 `/api/store-manager/*`、未改前端。**

## 2. changed files（3 个，+161/-18）
| 文件 | 改动 |
|------|------|
| `backend/app/coze_client.py`（新增, +94） | Coze v3 Bot Chat 客户端：httpx async、超时、未配置/失败抛 `CozeError`、**不记录 token/请求头** |
| `backend/app/config.py`（+7） | 新增 `coze_chat_enabled / coze_api_base / coze_api_token / coze_chat_bot_id / coze_timeout`（**仅读取，无真实值**） |
| `backend/app/routers/weapp.py`（+? ） | `/api/ai/chat` async 化 + Coze/降级分流 + 硬护栏 + 真实标签；import coze_client |

## 3. chat 修复前后契约对比
| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 实现 | 纯硬编码模板 | `COZE_CHAT_ENABLED=true` 且配置完整 → 调 Coze Bot；否则/任何失败 → 本地模板降级 |
| 前端契约 | `data.answer` | `data.answer`（**不变，前端无感**）+ 附 `source/confidence_label/degraded/confidence` |
| 标签 | 永远 `知识库+模型生成`（**假标**） | 真实：成功=`source:coze`/`扣子知识库+模型生成`/`degraded:false`；模板=`source:local_fallback`/`本地模板(降级)`/`degraded:true` |
| 护栏 | 模板内 safe_note | 医疗/敏感词 → 追加免责，**只追加一次**（真实/降级都生效） |
| 健壮性 | — | `answer` 始终可用（极端兜底"暂无回复"），**不白屏、不 500** |

## 4. 测试摘要（9 PASS / 0 FAIL，见 TEST_OUTPUT.txt）
1. `COZE_CHAT_ENABLED=false` → 降级 `local_fallback`、不假标、answer 非空 ✅
2. enabled=true 但缺 token/id → 降级 ✅
3. Coze 成功 → `source=coze`、`degraded=false`、`扣子知识库+模型生成`、answer 来自 Coze ✅
4. 医疗问题（祛斑）→ 追加免责，且**只追加一次** ✅
5. Coze 异常 → 降级模板、不假标 ✅

## 5. 关键治理点落实
- **模板降级标签真实化**：任何模板/降级输出强制 `degraded=true / source=local_fallback / 本地模板(降级)`，**绝不标"知识库+模型生成"**。
- **医疗免责只追加一次**：`_apply_chat_guardrail` 检测已含免责则不重复。
- **灰度独立**：仅 `COZE_CHAT_ENABLED`（默认 false），不影响 private/content。
- **密钥安全**：配置项默认空，真实值经环境变量注入；client 不记录 token；本 patch 经扫描**无 token 明文**。

## 6. 边界声明
- 未 merge main、未 push main、未部署、未 scp、未动 ECS/Nginx/SSL/安全组/18080/18081。
- 未写 private 代码、未写 content 代码、未迁 manager、未动 `/api/store-manager/*`。
- 未碰真实 token/env。
- **当前仍未轮到 Coze 介入**（Coze 侧 Bot/知识库/ID 备齐 + 本包审过后，才进灰度联调）。

## 7. 下一步（待授权）
阶段2 吴哥+ChatGPT 审本包 → 通过后阶段3 我做 private（同模式）。代码合 main / 部署 / 开 `COZE_CHAT_ENABLED=true` 灰度，均需单独授权。
