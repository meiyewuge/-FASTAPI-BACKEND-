"""V0.1.3 公共工具：统一东八区（CST, UTC+8）时间。

审查要求：所有 datetime.now() 统一为东八区，避免跨零点日期口径不一致。
"""
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    return datetime.now(CST)


def today_cst() -> str:
    return now_cst().strftime("%Y-%m-%d")


def now_iso_cst() -> str:
    return now_cst().isoformat()
