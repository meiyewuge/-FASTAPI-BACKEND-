"""业务指标层（Business Metrics）—— 从真实成本/产出数据「纯推导」的指标。

只做客观可推导的成本侧效率/产能指标，**不含收入/ROI/分润/定价等需业务口径的内容**。
依赖 cost_engine（成本）+ models（产出），向上提供「成本 → 业务解释」。
"""

from .business_metrics import overview, by_store, by_strategy

__all__ = ["overview", "by_store", "by_strategy"]
