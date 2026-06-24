"""API 依赖：DB 会话 + 租户解析（tenant 强制）。"""

from __future__ import annotations

from fastapi import Header

from config import settings
from db import get_db  # noqa: F401  re-export 供路由使用


def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    """从请求头解析 tenant_id；缺省回落到默认租户。

    所有数据访问必须经此拿到 tenant_id 并据此过滤，杜绝跨租户。
    （真实鉴权可在此从 JWT 解出 tenant_id。）
    """
    return x_tenant_id or settings.default_tenant
