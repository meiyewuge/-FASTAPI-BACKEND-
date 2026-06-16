"""Coze 接入客户端（当前仅 chat 阶段）。

设计同 app/ai.py 的"外部调用 + 失败抛出由上层降级"模式：
- 未配置(无 token/bot_id) → 抛 CozeError，上层走本地模板降级；
- 超时/非2xx/解析失败/空答 → 抛 CozeError；
- 绝不记录 token / 完整请求头等密钥信息。
"""
from __future__ import annotations

import time
import asyncio
import logging
from typing import Optional

import httpx

from .config import settings

logger = logging.getLogger("coze_client")


class CozeError(Exception):
    """Coze 调用失败，调用方据此降级到本地模板。"""


def chat_configured() -> bool:
    return bool(settings.coze_chat_enabled and settings.coze_api_token and settings.coze_chat_bot_id)


async def chat_bot(message: str, user_id: str, timeout: Optional[int] = None) -> str:
    """调用 Coze Bot Chat（v3，非流式），返回 assistant 文本答案。失败抛 CozeError。"""
    if not (settings.coze_api_token and settings.coze_chat_bot_id):
        raise CozeError("coze chat not configured")

    base = settings.coze_api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.coze_api_token}",
        "Content-Type": "application/json",
    }
    body = {
        "bot_id": settings.coze_chat_bot_id,
        "user_id": user_id,
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": message, "content_type": "text"}
        ],
    }
    total_timeout = timeout or settings.coze_timeout

    try:
        async with httpx.AsyncClient(timeout=total_timeout) as client:
            # 1) 发起对话
            resp = await client.post(f"{base}/v3/chat", headers=headers, json=body)
            resp.raise_for_status()
            data = (resp.json() or {}).get("data", {}) or {}
            chat_id = data.get("id")
            conversation_id = data.get("conversation_id")
            status = data.get("status")
            if not chat_id or not conversation_id:
                raise CozeError("coze chat: missing chat_id/conversation_id")

            # 2) 轮询直到完成（受 total_timeout 约束）
            deadline = time.monotonic() + total_timeout
            params = {"chat_id": chat_id, "conversation_id": conversation_id}
            while status in ("created", "in_progress", None):
                if time.monotonic() >= deadline:
                    raise CozeError("coze chat: poll timeout")
                await asyncio.sleep(1)
                r = await client.get(f"{base}/v3/chat/retrieve", headers=headers, params=params)
                r.raise_for_status()
                status = ((r.json() or {}).get("data", {}) or {}).get("status")

            if status != "completed":
                raise CozeError(f"coze chat: status={status}")

            # 3) 取 assistant 答案
            rm = await client.get(f"{base}/v3/chat/message/list", headers=headers, params=params)
            rm.raise_for_status()
            msgs = (rm.json() or {}).get("data", []) or []
            answer = ""
            for m in msgs:
                if m.get("role") == "assistant" and m.get("type") == "answer":
                    answer = (m.get("content") or "").strip()
                    if answer:
                        break
            if not answer:
                raise CozeError("coze chat: empty answer")
            return answer
    except CozeError:
        raise
    except Exception as exc:  # 网络/超时/解析等：不泄露密钥，仅记类型
        logger.warning("coze chat call failed: %s", type(exc).__name__)
        raise CozeError(f"coze chat call failed: {type(exc).__name__}") from exc
