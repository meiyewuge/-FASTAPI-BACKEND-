"""压测模块（Phase 6）—— 只新增，不改主系统逻辑。

驱动现有公开链路（orchestrator → task runner → provider(mock/flaky) → cost_engine），
采集产能/稳定性/性能/成本指标，输出生产级压测报告。
"""
