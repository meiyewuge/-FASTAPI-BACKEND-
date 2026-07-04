"""模型客户端接口与 Mock 实现。

M1 条件施工许可约束：本阶段只允许 mock，不发起任何真实模型调用；
真实 provider 适配器待供应商实测后另行工单接入（密钥经环境变量注入）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class ModelReply:
    """一次模型调用的原始返回。"""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    quality_score: float = 88.0    # mock 阶段由脚本注入；真实阶段由 review_model 评出


class ModelTimeout(Exception):
    """模型超时（>timeout_seconds）。"""


class ModelClient(Protocol):
    """模型客户端协议 — 可插拔：任何 provider 适配器实现本协议即可挂入路由。"""

    provider: str
    model_name: str

    def generate(self, prompt: str, materials: List[Dict[str, Any]]) -> ModelReply:
        """生成文本。超时抛 ModelTimeout，其余失败抛异常。"""
        ...


@dataclass
class MockModelClient:
    """Mock 模型客户端 — 按预置脚本返回/失败，供单测与红线测试使用。

    scripted_replies：依次弹出的回复；耗尽后重复最后一条。
    fail_times：前 N 次调用抛 ModelTimeout（模拟主模型超时）。
    """

    provider: str = "mock"
    model_name: str = "mock-model"
    scripted_replies: List[ModelReply] = field(default_factory=list)
    fail_times: int = 0
    calls: List[str] = field(default_factory=list)   # 记录收到的 prompt，供测试断言

    def generate(self, prompt: str, materials: List[Dict[str, Any]]) -> ModelReply:
        self.calls.append(prompt)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ModelTimeout(f"{self.model_name} mock timeout")
        if not self.scripted_replies:
            ids = ",".join(str(m.get("id", "")) for m in materials)
            return ModelReply(
                text=f"[mock:{self.model_name}] 基于素材({ids})的草稿。",
                input_tokens=len(prompt),
                output_tokens=64,
                latency_ms=5,
            )
        if len(self.scripted_replies) > 1:
            return self.scripted_replies.pop(0)
        return self.scripted_replies[0]
