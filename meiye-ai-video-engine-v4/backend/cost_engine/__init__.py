"""Cost Engine —— 独立经济层（计价 / 记账 / 台账 / 熔断）。

边界：
- provider 纯执行（出视频），orchestrator 只调度+归因，**价格计算与熔断都在此**。
- 换模型 / 改计费策略 / 接分润，只动本包，不动 provider / engine / orchestrator 业务。

子模块：
- pricing_model: 单价与计价策略
- billing:       记一条成本（写账）
- ledger:        台账查询（已花/统计）
- policy:        配额与熔断规则
"""

from .policy import QuotaExceeded, ensure_budget, get_or_create_tenant
from .pricing_model import price, unit_price
from .billing import record
from .ledger import by_provider, by_store, get_spend, summary

__all__ = [
    "QuotaExceeded",
    "ensure_budget",
    "get_or_create_tenant",
    "price",
    "unit_price",
    "record",
    "get_spend",
    "summary",
    "by_store",
    "by_provider",
]
