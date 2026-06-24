# 成本对比 · cost_real_vs_mock_compare（mode=DRY-RUN）

> 架构前提（Phase 5）：**成本由 cost_engine 计价模型决定，与 provider 解耦**。
> 因此「按条计价」下 mock 与 real 的成本数字**本就相同**——真实 IO 真正改变的是
> **视频时长(duration)** 与 **延迟/稳定性**，而非成本数字本身。

| 项 | mock | 本轮(DRY-RUN) | 说明 |
| --- | --- | --- | --- |
| 单视频成本(按条计价) | 0.2895 | 0.2895 | 计价驱动，provider 无关 |
| 平均时长/条(s) | 仿真固定值 | 8.54 | **真实 IO 要校准的量** |
| A台延迟 p95(ms) | ≈管线开销 | 1084.634 | 真实=火山出片时延 |
| B台延迟 p95(ms) | ≈管线开销 | 1619.908 | |

## 要拿到「真实成本」，二选一（需你定）
1. **按秒计价**：把 `cost_engine.pricing_model` 改成 `单价×duration`，用真实 duration 算钱；
2. **读厂商账单**：在 VolcanoSeedanceProvider 里解析火山返回的真实计费，写入 cost。

> ⚠️ mode=DRY-RUN。DRY-RUN：duration/延迟为仿真。接火山 key + 定计价口径后得真实成本。
