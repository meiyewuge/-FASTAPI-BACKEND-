"""Coze 接入客户端 — Bot Chat / Workflow 统一封装。

设计原则（同 app/ai.py 的"外部调用 + 失败抛出由上层降级"模式）：
- 未配置（无 token / bot_id / workflow_id）→ 抛 CozeError，上层走本地模板降级；
- 超时 / 非 2xx / 解析失败 / 空输出       → 抛 CozeError；
- 绝不记录 token / 完整请求头等密钥信息。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from .config import settings

logger = logging.getLogger("coze_client")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_WORKFLOW_PATH = "/v1/workflow/run"
_CHAT_PATH = "/v3/chat"
_CHAT_RETRIEVE_PATH = "/v3/chat/retrieve"
_CHAT_MESSAGE_LIST_PATH = "/v3/chat/message/list"
_POLL_INTERVAL_SEC = 1.0


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class CozeError(Exception):
    """Coze 调用失败，调用方据此降级到本地模板。"""


# ---------------------------------------------------------------------------
# 配置就绪判定
# ---------------------------------------------------------------------------
def chat_configured() -> bool:
    """chat 灰度开关 + token + bot_id 均已配置。"""
    return bool(settings.coze_chat_enabled and settings.coze_api_token and settings.coze_chat_bot_id)


def private_configured() -> bool:
    """private 灰度开关 + token + bot_id 均已配置。"""
    return bool(settings.coze_private_enabled and settings.coze_api_token and settings.coze_private_bot_id)


def content_configured() -> bool:
    """content 灰度开关 + token + bot_id 均已配置。"""
    return bool(settings.coze_content_enabled and settings.coze_api_token and settings.coze_content_bot_id)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _build_headers() -> Dict[str, str]:
    """构造 Coze 鉴权请求头（不含密钥日志）。"""
    return {
        "Authorization": f"Bearer {settings.coze_api_token}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return settings.coze_api_base.rstrip("/")


def _make_client(timeout: int) -> httpx.AsyncClient:
    """创建带超时的 httpx 异步客户端。"""
    return httpx.AsyncClient(timeout=timeout)


# ---------------------------------------------------------------------------
# Workflow 调用（content / private 共用）
# ---------------------------------------------------------------------------
async def run_workflow(
    workflow_id: str,
    parameters: Dict[str, Any],
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """调用 Coze Workflow（非流式），返回 workflow 输出 dict。

    失败时抛 CozeError，由上层决定是否降级到本地模板。
    Coze /v1/workflow/run 的 ``data`` 字段为 JSON 字符串，需二次解析。
    """
    if not (settings.coze_api_token and workflow_id):
        raise CozeError("coze workflow not configured")

    total_timeout = timeout or settings.coze_timeout
    body: Dict[str, Any] = {"workflow_id": workflow_id, "parameters": parameters or {}}
    t0 = time.monotonic()

    try:
        async with _make_client(total_timeout) as client:
            resp = await client.post(
                f"{_base_url()}{_WORKFLOW_PATH}",
                headers=_build_headers(),
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json() or {}

            # Coze 业务码校验
            code = payload.get("code")
            if code not in (0, None):
                raise CozeError(f"coze workflow: code={code}")

            data = payload.get("data")
            # data 可能是 JSON 字符串，也可能已是 dict
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (ValueError, TypeError):
                    raise CozeError("coze workflow: data field is not valid JSON")
            if not isinstance(data, dict):
                raise CozeError("coze workflow: data field is not an object")

            elapsed = round(time.monotonic() - t0, 2)
            logger.info("coze workflow ok | workflow_id=%s | elapsed=%.2fs", workflow_id[:8], elapsed)
            return data

    except CozeError:
        raise
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        logger.warning(
            "coze workflow failed | workflow_id=%s | err=%s | elapsed=%.2fs",
            workflow_id[:8], type(exc).__name__, elapsed,
        )
        raise CozeError(f"coze workflow call failed: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# Bot Chat 调用（chat / private / content 共用）
# ---------------------------------------------------------------------------
async def chat_bot(
    message: str,
    user_id: str,
    bot_id: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """调用 Coze Bot Chat（v3，非流式），返回 assistant 文本答案。

    流程：发起对话 → 轮询至完成 → 取 assistant answer。
    bot_id：显式指定要对话的 Bot；不传则回退 settings.coze_chat_bot_id（chat 现有行为不变）。
    private / content 通过传入各自专用 bot_id 复用本函数。
    失败时抛 CozeError。
    """
    use_bot_id = bot_id or settings.coze_chat_bot_id
    if not (settings.coze_api_token and use_bot_id):
        raise CozeError("coze chat not configured")

    total_timeout = timeout or settings.coze_timeout
    bot_id = use_bot_id  # type: ignore[assignment]
    body: Dict[str, Any] = {
        "bot_id": bot_id,
        "user_id": user_id,
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [
            {"role": "user", "content": message, "content_type": "text"},
        ],
    }
    t0 = time.monotonic()

    try:
        async with _make_client(total_timeout) as client:
            headers = _build_headers()
            base = _base_url()

            # ── Step 1: 发起对话 ──────────────────────────────────
            resp = await client.post(f"{base}{_CHAT_PATH}", headers=headers, json=body)
            resp.raise_for_status()
            data: Dict[str, Any] = (resp.json() or {}).get("data", {}) or {}

            chat_id: Optional[str] = data.get("id")
            conversation_id: Optional[str] = data.get("conversation_id")
            status: Optional[str] = data.get("status")
            if not chat_id or not conversation_id:
                raise CozeError("coze chat: missing chat_id/conversation_id")

            # ── Step 2: 轮询直到完成（受 total_timeout 约束）────────
            deadline = time.monotonic() + total_timeout
            poll_params = {"chat_id": chat_id, "conversation_id": conversation_id}
            while status in ("created", "in_progress", None):
                if time.monotonic() >= deadline:
                    raise CozeError("coze chat: poll timeout")
                await asyncio.sleep(_POLL_INTERVAL_SEC)
                r = await client.get(f"{base}{_CHAT_RETRIEVE_PATH}", headers=headers, params=poll_params)
                r.raise_for_status()
                status = ((r.json() or {}).get("data", {}) or {}).get("status")

            if status != "completed":
                raise CozeError(f"coze chat: unexpected status={status}")

            # ── Step 3: 取 assistant 答案 ─────────────────────────
            rm = await client.get(f"{base}{_CHAT_MESSAGE_LIST_PATH}", headers=headers, params=poll_params)
            rm.raise_for_status()
            msgs: list = (rm.json() or {}).get("data", []) or []

            answer = ""
            for m in msgs:
                if m.get("role") == "assistant" and m.get("type") == "answer":
                    answer = (m.get("content") or "").strip()
                    if answer:
                        break
            if not answer:
                raise CozeError("coze chat: empty answer from assistant")

            elapsed = round(time.monotonic() - t0, 2)
            logger.info("coze chat ok | bot_id=%s | elapsed=%.2fs", bot_id[:8], elapsed)
            return answer

    except CozeError:
        raise
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        logger.warning(
            "coze chat failed | bot_id=%s | err=%s | elapsed=%.2fs",
            bot_id[:8], type(exc).__name__, elapsed,
        )
        raise CozeError(f"coze chat call failed: {type(exc).__name__}") from exc
