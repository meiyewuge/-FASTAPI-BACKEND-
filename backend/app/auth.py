"""P0B-2: 结果页鉴权模块。

功能：
  - verify_result_auth: 单条结果页（diagnosis / monthly_checkup）鉴权
  - verify_store_auth: 门店历史/趋势接口鉴权
  - RESULT_TICKET_ISSUERS: ticket issuer 白名单

约束：
  - access_token 为主鉴权凭证（DB 列）
  - ticket 为短期一次性凭证（Redis/TTL=300s）
  - 旧记录（access_token=NULL）兼容期策略由 allow_unauthenticated_results 控制
  - 记录不存在一律返回 401（防止 ID 枚举探测）
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .redis_client import ticket_get, ticket_delete

logger = logging.getLogger("p0b2_auth")

# ── Ticket issuer 白名单（V5 FINAL）──
# 只有服务端可信流程可生成白名单 issuer 的 ticket
RESULT_TICKET_ISSUERS = frozenset({
    "post_create",             # POST 创建成功后服务端生成
    # "duplicate_409",        # V4 删除：POST 无登录，可被猜 store_id 触发
    "miniapp_authenticated",   # 小程序已认证 openid（P0B-4 完成后可用）
})

# ── Target 映射 ──
_TARGET_MAP = {
    "diagnosis": ["diagnosis_result"],
    "monthly_checkup": ["monthly_result"],
}


def generate_access_token() -> str:
    """生成 64 字符随机 access_token。"""
    return secrets.token_hex(32)  # 32 bytes = 64 hex chars


def verify_result_auth(
    record_id: int,
    record_type: str,
    model,
    token: Optional[str],
    ticket: Optional[str],
    db: Session,
) -> object:
    """P0B-2 V5: 结果页鉴权（最终版）。

    Args:
        record_id: 记录 ID
        record_type: "diagnosis" 或 "monthly_checkup"
        model: SQLAlchemy model class
        token: access_token（来自 URL query）
        ticket: Redis ticket（来自 URL query）
        db: DB session

    Returns:
        记录对象（鉴权通过）

    Raises:
        HTTPException(401): 鉴权失败
    """
    # ── Step 1: 查询记录 ──
    record = db.get(model, record_id)

    # ── Step 2: 记录不存在 → 一律 401 ──
    if record is None:
        if ticket:
            ticket_delete(ticket)   # 消费，防重放探测
        logger.warning(
            "result_auth: DENY | type=%s | id=%s | not_found_or_unauthorized",
            record_type, record_id,
        )
        raise HTTPException(status_code=401, detail="无权访问或报告不存在")

    # ── Step 3: 记录存在 ──

    # ── 3a: 旧记录兼容期（V5: 先判旧记录）──
    if record.access_token is None:
        # 旧记录 access_token=NULL
        if settings.allow_unauthenticated_results:
            # 兼容期开 → 放行（不论 token/ticket 是什么）
            logger.warning(
                "result_auth: LEGACY_PASS_BY_COMPAT | type=%s | id=%s",
                record_type, record_id,
            )
            return record

        # 兼容期关 → 只有白名单 ticket 可放行
        if ticket:
            td = ticket_get(ticket)
            if (td
                and td.get("target") in _TARGET_MAP.get(record_type, [])
                and str(td.get("report_id")) == str(record_id)
                and td.get("issuer", "") in RESULT_TICKET_ISSUERS
            ):
                ticket_delete(ticket)
                logger.info(
                    "result_auth: PASS_TICKET_LEGACY | type=%s | id=%s | issuer=%s",
                    record_type, record_id, td.get("issuer"),
                )
                return record
            # ticket 无效 → 消费并 fall through
            if td:
                ticket_delete(ticket)

        logger.warning(
            "result_auth: DENY_LEGACY | type=%s | id=%s | compat_closed",
            record_type, record_id,
        )
        raise HTTPException(status_code=401, detail="无权访问或报告不存在")

    # ── 3b: 新记录 access_token != NULL → 正常鉴权 ──

    # token 校验
    if token:
        if record.access_token == token:
            logger.info("result_auth: PASS_TOKEN | type=%s | id=%s", record_type, record_id)
            return record
        logger.warning("result_auth: DENY_TOKEN | type=%s | id=%s", record_type, record_id)
        raise HTTPException(status_code=401, detail="无权访问或报告不存在")

    # ticket 校验（含 issuer 白名单）
    if ticket:
        td = ticket_get(ticket)
        if td is None:
            logger.warning("result_auth: DENY_TICKET_EXPIRED | type=%s | id=%s", record_type, record_id)
            raise HTTPException(status_code=401, detail="无权访问或报告不存在")

        if td.get("target") not in _TARGET_MAP.get(record_type, []):
            ticket_delete(ticket)
            logger.warning("result_auth: DENY_TICKET_TARGET | type=%s | id=%s", record_type, record_id)
            raise HTTPException(status_code=401, detail="无权访问或报告不存在")

        if str(td.get("report_id")) != str(record_id):
            ticket_delete(ticket)
            logger.warning("result_auth: DENY_TICKET_ID | type=%s | id=%s", record_type, record_id)
            raise HTTPException(status_code=401, detail="无权访问或报告不存在")

        issuer = td.get("issuer", "")
        if issuer not in RESULT_TICKET_ISSUERS:
            ticket_delete(ticket)
            logger.warning(
                "result_auth: DENY_TICKET_ISSUER | type=%s | id=%s | issuer=%s",
                record_type, record_id, issuer,
            )
            raise HTTPException(status_code=401, detail="无权访问或报告不存在")

        ticket_delete(ticket)
        logger.info("result_auth: PASS_TICKET | type=%s | id=%s | issuer=%s", record_type, record_id, issuer)
        return record

    # 无凭证
    logger.warning("result_auth: DENY_NO_CREDENTIAL | type=%s | id=%s", record_type, record_id)
    raise HTTPException(status_code=401, detail="无权访问或报告不存在")


def verify_store_auth(
    store_id: int,
    token: Optional[str],
    ticket: Optional[str],
    db: Session,
) -> None:
    """P0B-2 V5: 门店历史/趋势接口鉴权。

    Args:
        store_id: 门店 ID
        token: access_token（来自 URL query）
        ticket: Redis ticket（来自 URL query）
        db: DB session

    Raises:
        HTTPException(401): 鉴权失败
    """
    # ── A: access_token 校验 ──
    if token:
        match = db.query(models.MonthlyCheckup).filter(
            models.MonthlyCheckup.store_id == store_id,
            models.MonthlyCheckup.access_token == token,
        ).first()
        if match:
            logger.info("store_auth: PASS_TOKEN | store_id=%s", store_id)
            return

        # token 不属于该 store → 降级到兼容期检查
        # （诊断 token 跳趋势时会到这里）

    # ── B: ticket 校验（含 issuer 白名单）──
    if ticket:
        td = ticket_get(ticket)
        if (td
            and td.get("target") == "history"
            and str(td.get("store_id")) == str(store_id)
            and td.get("issuer", "") in RESULT_TICKET_ISSUERS
        ):
            ticket_delete(ticket)
            logger.info("store_auth: PASS_TICKET | store_id=%s | issuer=%s",
                       store_id, td.get("issuer"))
            return
        if td:
            ticket_delete(ticket)

    # ── C: 兼容期（作为 fallback）──
    if settings.allow_unauthenticated_results:
        logger.warning(
            "store_auth: LEGACY_PASS_BY_COMPAT | store_id=%s", store_id,
        )
        return

    raise HTTPException(status_code=401, detail="无权访问或报告不存在")
