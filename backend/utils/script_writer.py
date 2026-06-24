"""B5：分镜脚本生成（可插拔）。

把用户一句话扩写为专业分镜脚本。默认规则版（无依赖）；配置 SCRIPT_PROVIDER=llm +
LLM_API_KEY 后走 OpenAI 兼容接口（DeepSeek/通义等），失败自动回退规则版，绝不中断生成。
"""

from __future__ import annotations

import httpx

from config import settings

_SYS_PROMPT = (
    "你是美业短视频分镜脚本专家。把用户一句话需求扩写成专业分镜脚本："
    "开场钩子→核心卖点→效果展示→行动号召，语言简洁、可直接拍摄。"
)


def _rule_script(prompt: str) -> str:
    return f"【脚本】围绕「{prompt}」：开场抓眼球 → 核心卖点 → 行动号召。"


def _llm_script(prompt: str) -> str:
    resp = httpx.post(
        f"{settings.llm_api_base.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": _SYS_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_script(prompt: str) -> str:
    """生成分镜脚本：llm 模式失败回退规则版。"""
    if settings.script_provider == "llm" and settings.llm_api_key:
        try:
            return _llm_script(prompt)
        except Exception:  # noqa: BLE001  LLM 失败不阻断，回退规则版
            return _rule_script(prompt)
    return _rule_script(prompt)
