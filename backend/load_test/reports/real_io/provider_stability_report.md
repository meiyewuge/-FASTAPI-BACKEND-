# Provider 稳定性报告 · provider_stability_report（mode=DRY-RUN）

provider=`loadtest_flaky` 并发=6 注入失败率=0.3 仿真延迟=300.0ms

## 指标
- A台成功率 100.0% · B台成功率 100.0%
- fallback 触发率 **1.8%** · retry 率 0.0% · 失败任务 0
- A台延迟 p95 1084.634ms / p99 1241.965ms
- B台延迟 p95 1619.908ms / p99 1799.468ms
- 排队延迟 p95：A 676.653ms · B 1974.72ms

## 验收对照
- [x] 成功率高
- [x] fallback<20%
- [x] 无大量失败
- [x] 6并发稳定运行

> ⚠️ mode=DRY-RUN。DRY-RUN 验证管线/并发/排队/兜底正确；真实延迟与成本需火山 key 实跑。
