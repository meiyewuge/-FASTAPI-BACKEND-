# SECURITY_NOTE — WUGE Search Router P0 T5 入口层

## 0. 一句话结论

T5 仅新增入口层（SearchRouter 主路由 + CLI + E2E 测试）。
基于 T4 V0.1.1 完整基线（T1+T2A+T2B+T3+T4），未修改 T1/T2A/T2B/T3/T4 已通过源码。
**未联网、未接真实 Key、未调用真实 GLM、未写生产库、未部署、未碰 production、未替换线上 codeact_search_web。**

## 1. 未联网

- T5 新模块无 `requests` / `httpx` / `aiohttp` / `socket` 等真实网络调用
- `router.py` 使用 `asyncio` 编排全链路，不发起网络请求
- `examples/run_single_search.py` 和 `examples/run_daily_intel.py` 仅调用 SearchRouter，不联网
- dry_run=true 时全链路走 Mock，不触网

## 2. 未使用真实 API Key

- 不读取任何 API Key
- 不使用 `ZHIPU_API_KEY` / `BOCHA_API_KEY` / `TAVILY_API_KEY`
- CLI 脚本不读取 .env，不接收 Key 参数

## 3. 未调用真实 GLM

- GLMEnhancer 三锁默认全关，强制 Mock
- E2E 测试中三锁 True 时使用 fake adapter，不接真实 GLM

## 4. 未调用真实 Provider

- dry_run=true 时强制 MockProviderAdapter
- Bocha / GLM / Tavily Adapter 不被调用
- codeact 仅作为 F3 emergency 标记，不真实调用，不替换线上 `codeact_search_web`

## 5. 未部署

- 不部署到任何服务器
- 不注册 systemd
- 不开放公网端口

## 6. 未写入生产数据库

- DedupManager 默认 `:memory:`
- CandidatePool 使用内存列表
- CostTracker 默认 `:memory:`
- 不写 ECS 真实库
- 不入正式知识库

## 7. 未碰 production

- 不访问 8.152.169.71
- 不访问 video.beautypeaceai.com
- 不替换线上搜索

## 8. 未越界（T5 是最终层）

- T5 是 P0 最后一个 Task，无 T6
- 未修改 T1/T2A/T2B/T3/T4 已通过源码

## 9. dry_run 铁律保持

- `SEARCH_ROUTER_DRY_RUN=true` 默认
- dry_run=true 时 SearchRouter 强制使用 MockProviderAdapter
- CLI 脚本默认 dry_run=true

## 10. 三锁铁律保持

- GLMEnhancer 三锁默认全关
- E2E 测试中三锁 True 时使用 fake adapter

## 11. codeact F3 仅标记

- codeact 在 T5 仅作为 F3 emergency 标记
- 不真实调用 `codeact_search_web`
- 不替换线上脚本

## 12. .gitignore 保持

- `.env` 已被排除
- `*.db` / `*.sqlite` 已被排除
- `logs/` 已被排除
