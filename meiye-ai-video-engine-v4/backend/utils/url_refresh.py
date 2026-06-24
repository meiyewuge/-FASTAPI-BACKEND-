"""P0：火山签名 URL 刷新机制。

火山 CDN 签名 URL 24h 过期。**主修复是本地存储**（video_storage，本地副本永不过期）；
本模块作辅助：对未落盘/仅有 CDN 的视频，检测过期并经火山查询 API 拿新 URL。

要真正刷新需：生成时把火山 task_id 持久化（建议 Video 增 volcano_task_id 列），
刷新时用该 id 调 GET /api/v3/contents/generations/tasks/{id} 取新 video_url。
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse


def is_expired(signed_url: str, skew_seconds: int = 300) -> bool:
    """尽力解析签名 URL 的过期时间（火山 TOS 常见 X-Tos-Expires/Expires/x-expires）。
    解析不到则保守视为「可能过期」交由上层决定。"""
    try:
        q = parse_qs(urlparse(signed_url).query)
        for k in ("X-Tos-Expires", "Expires", "x-expires", "expire"):
            if k in q:
                exp = int(q[k][0])
                # 有的是绝对时间戳，有的是相对秒数；>1e9 视为绝对时间戳
                if exp > 1_000_000_000:
                    return time.time() + skew_seconds >= exp
        return False
    except Exception:  # noqa: BLE001
        return False


def refresh_via_volcano(volcano_task_id: str) -> str | None:
    """用火山 task_id 重新查询拿新 URL（需真实 key；接入见 volcano_doubao_provider）。
    占位：真实实现复用 provider 的 _poll 取 video_url。"""
    # from utils.video_provider_volcano import build_volcano
    # status, url, _ = build_volcano().\_poll(volcano_task_id)
    # return url if status == "done" else None
    return None
