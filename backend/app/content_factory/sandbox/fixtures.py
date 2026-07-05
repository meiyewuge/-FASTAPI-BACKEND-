"""W8 全链路 mock fixture 构造器。

设计依据：M1-W8 条件施工许可 二.3。

构造一条完整的 mock 产线：
- MockRecallClient（预置 approved 素材）
- DraftGenerator（MockModelClient × 4 角色）
- GatePipeline（MockG3Adjudicator）
- MidPlatformMock（审读队列 + 前台提示）
- ProductionLineObserver（观测 + 日报）
- MockReportStore / MockScheduler / MockAlertSink

所有组件均为 mock，不接真实服务。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.app.content_factory.drafting.generator import DraftGenerator
from backend.app.content_factory.gates.pipeline import GatePipeline
from backend.app.content_factory.midplatform.pages import MidPlatformMock
from backend.app.content_factory.obs_contracts.mocks import (
    MockAlertSink,
    MockReportStore,
    MockScheduler,
)
from backend.app.content_factory.observability.observer import ProductionLineObserver
from backend.app.content_factory.recall.client import MockRecallClient, RecallConfig
from backend.app.content_factory.recall.results import (
    RecallMetadata,
    RecallResult,
    RecallStatus,
)
from backend.app.model_router.clients import MockModelClient, ModelReply
from backend.app.model_router.config import ModelRouterConfig
from backend.app.model_router.router import ModelRouter
from backend.app.model_router.schemas import ModelRole

from .runner import SandboxRunner


# ──────────────────────────────────────────────────────────────────────
# 素材工厂
# ──────────────────────────────────────────────────────────────────────
def make_material(mat_id: str, content: str, mat_type: str = "fact_card") -> Dict[str, Any]:
    """构造一条 mock approved 素材。"""
    return {
        "id": mat_id,
        "content": content,
        "material_type": mat_type,
        "source_type": "9080_approved",
        "status": "active",
    }


# 预置合规素材（过 G1-G6 全清）
CLEAN_MATERIALS = [
    make_material("dfd_fact_001", "润养安肤奢华油为普通化妆品"),
    make_material("dfd_fact_002",
                  "体外法检测报告编号XYJCR241029-005，检测机构为广东欣研检验检测有限公司"),
]

# 预置一份"过 G1-G6 全清"的合规稿（小红书结构）
CLEAN_XHS_TEXT = (
    "标题：奢华油的日常。"
    "正文：润养安肤奢华油为普通化妆品，体外法检测报告编号XYJCR241029-005，"
    "检测机构为广东欣研检验检测有限公司。"
    "标签：护肤。"
)


# ──────────────────────────────────────────────────────────────────────
# mock 组件构造
# ──────────────────────────────────────────────────────────────────────
def build_mock_recall_client(
    materials: Optional[List[Dict[str, Any]]] = None,
    status: RecallStatus = RecallStatus.APPROVED,
) -> MockRecallClient:
    """构造预置素材的 MockRecallClient。"""
    mats = materials if materials is not None else CLEAN_MATERIALS
    result = RecallResult(
        materials=mats,
        status=status,
        source_refs=[],
        metadata=RecallMetadata(
            recall_id="recall_sandbox_001",
            timestamp=datetime.now(timezone.utc).isoformat(),
            query_hash="sandbox",
            source_count=len(mats),
        ),
    )
    return MockRecallClient(
        config=RecallConfig(base_url="mock", mock=True),
        scripted_results=[result],
    )


def build_mock_model_router(
    scripted_text: Optional[str] = None,
) -> ModelRouter:
    """构造全 mock 的 ModelRouter（4 角色 × MockModelClient）。"""
    text = scripted_text or CLEAN_XHS_TEXT
    reply = ModelReply(text=text, input_tokens=100, output_tokens=50, latency_ms=10)
    mock_client = MockModelClient(
        provider="mock", model_name="mock-sandbox",
        scripted_replies=[reply],
    )
    clients = {role: mock_client for role in ModelRole}
    return ModelRouter(config=ModelRouterConfig.default(), clients=clients)


def build_mock_gate_pipeline() -> GatePipeline:
    """构造 GatePipeline（默认 MockG3Adjudicator）。"""
    return GatePipeline()


def build_mock_midplatform() -> MidPlatformMock:
    """构造中台 mock。"""
    return MidPlatformMock()


def build_mock_observer() -> ProductionLineObserver:
    """构造观测器。"""
    return ProductionLineObserver()


def build_mock_report_store() -> MockReportStore:
    """构造内存日报存储。"""
    return MockReportStore()


def build_mock_scheduler() -> MockScheduler:
    """构造内存调度器。"""
    return MockScheduler()


def build_mock_alert_sink() -> MockAlertSink:
    """构造内存告警池。"""
    return MockAlertSink()


# ──────────────────────────────────────────────────────────────────────
# 一键构造完整 SandboxRunner
# ──────────────────────────────────────────────────────────────────────
def build_sandbox_runner(
    scripted_text: Optional[str] = None,
    materials: Optional[List[Dict[str, Any]]] = None,
    recall_status: RecallStatus = RecallStatus.APPROVED,
) -> SandboxRunner:
    """一键构造全 mock 的 SandboxRunner。

    默认配置：充足素材 + 清洁稿 → 成功路径。
    可通过参数切换到缺料/拦截等路径。
    """
    recall_client = build_mock_recall_client(materials, recall_status)
    model_router = build_mock_model_router(scripted_text)
    draft_generator = DraftGenerator(router=model_router)
    gate_pipeline = build_mock_gate_pipeline()

    return SandboxRunner(
        recall_client=recall_client,
        draft_generator=draft_generator,
        gate_pipeline=gate_pipeline,
        midplatform=build_mock_midplatform(),
        observer=build_mock_observer(),
        report_store=build_mock_report_store(),
        scheduler=build_mock_scheduler(),
        alert_sink=build_mock_alert_sink(),
    )
