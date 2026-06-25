"""订阅/试用业务（Patch5，暂不接支付）。

规则（保留口径，便于后续接支付）：
- 试用余量 trial_remaining 仅在 A台（母视频生成）扣减；B台裂变不扣。
- 当前阶段不做硬熔断（无支付），扣减到 0 仅作展示/埋点；放行与否由成本配额（cost_engine）决定。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cost_engine import get_or_create_tenant
from cost_engine.ledger import get_spend


def get_status(db: Session, tenant_id: str) -> dict:
    t = get_or_create_tenant(db, tenant_id)
    db.commit()
    spend = get_spend(db, tenant_id)
    return {
        "status": t.subscription_status,
        "trial_remaining": int(t.trial_remaining or 0),
        "quota_remaining": round(float(t.quota) - spend, 4),
    }


def consume_trial(db: Session, tenant_id: str) -> int:
    """A台扣减一次试用额度（仅试用态且有余量时扣）。返回扣减后的余量。"""
    t = get_or_create_tenant(db, tenant_id)
    if t.subscription_status == "trial" and (t.trial_remaining or 0) > 0:
        t.trial_remaining = int(t.trial_remaining) - 1
    # 提交以释放 SQLite 写锁（避免后续后台任务写库被锁）
    db.commit()
    return int(t.trial_remaining or 0)
