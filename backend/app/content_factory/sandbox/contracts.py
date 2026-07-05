"""W8 契约校验 — rulepack / feature flags / readiness checklist / W1-W7 兼容性。

设计依据：M1-W8 条件施工许可 二.4/二.5/二.6/二.7。

校验项：
1. rulepack：6 门规则集 md5 可校验、is_mock=True（不当正式规则）、is_production_ready=False
2. feature flags：全部默认 False、any_enabled()=False
3. readiness checklist：全部 done=False、is_ready=False
4. W1-W7 接口兼容性：各子包可导入、关键数据结构可实例化
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from backend.app.content_factory.readiness import (
    DEFAULT_FLAGS,
    FeatureFlags,
    ReadinessChecklists,
    default_checklists,
)
from backend.app.content_factory.rulepacks.gates import all_gate_rulepacks
from backend.app.content_factory.rulepacks.platform_contract import platform_rulesets
from backend.app.content_factory.rulepacks.schemas import RulePack


# ──────────────────────────────────────────────────────────────────────
# 校验结果
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ContractValidationResult:
    """单项契约校验结果。"""

    name: str
    passed: bool
    detail: str = ""
    items: List[Dict] = field(default_factory=list)


@dataclass
class SandboxContractReport:
    """W8 契约校验总报告。"""

    rulepack_checks: List[ContractValidationResult] = field(default_factory=list)
    flag_checks: List[ContractValidationResult] = field(default_factory=list)
    readiness_checks: List[ContractValidationResult] = field(default_factory=list)
    compat_checks: List[ContractValidationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        all_checks = (self.rulepack_checks + self.flag_checks
                      + self.readiness_checks + self.compat_checks)
        return all(c.passed for c in all_checks)

    def summary(self) -> Dict:
        all_checks = (self.rulepack_checks + self.flag_checks
                      + self.readiness_checks + self.compat_checks)
        passed = sum(1 for c in all_checks if c.passed)
        failed = sum(1 for c in all_checks if not c.passed)
        return {"total": len(all_checks), "passed": passed, "failed": failed}


# ──────────────────────────────────────────────────────────────────────
# Rulepack 校验
# ──────────────────────────────────────────────────────────────────────
def validate_rulepacks() -> List[ContractValidationResult]:
    """校验 G1-G6 规则集契约。"""
    results = []
    packs = all_gate_rulepacks()

    # 1. 六门齐备
    expected_scopes = {
        "G1_compliance", "G2_state_boundary", "G3_fact_ref",
        "G4_platform_structure", "G5_brand_consistency", "G6_format_complete",
    }
    actual = set(packs.keys())
    results.append(ContractValidationResult(
        "rulepack_six_gates_present",
        passed=expected_scopes == actual,
        detail=f"期望 {sorted(expected_scopes)}，实际 {sorted(actual)}",
    ))

    # 2. 每个 rulepack md5 可校验
    for scope, pack in packs.items():
        results.append(ContractValidationResult(
            f"rulepack_md5_valid_{scope}",
            passed=pack.verify_md5(),
            detail=f"scope={scope}, md5={pack.md5[:12]}...",
        ))

    # 3. 每个 rulepack is_mock=True（骨架期）
    for scope, pack in packs.items():
        results.append(ContractValidationResult(
            f"rulepack_is_mock_{scope}",
            passed=pack.is_mock is True,
            detail=f"scope={scope}, is_mock={pack.is_mock}",
        ))

    # 4. 每个 rulepack is_production_ready=False
    for scope, pack in packs.items():
        results.append(ContractValidationResult(
            f"rulepack_not_production_{scope}",
            passed=pack.is_production_ready is False,
            detail=f"scope={scope}, is_production_ready={pack.is_production_ready}",
        ))

    # 5. 四平台规则集
    prs = platform_rulesets()
    platforms = {"brand_site", "xiaohongshu", "douyin", "shipinhao"}
    results.append(ContractValidationResult(
        "platform_rulesets_four_present",
        passed=set(prs.keys()) == platforms,
        detail=f"期望 {sorted(platforms)}，实际 {sorted(prs.keys())}",
    ))

    for platform, rs in prs.items():
        results.append(ContractValidationResult(
            f"platform_ruleset_is_mock_{platform}",
            passed=rs.is_mock is True,
            detail=f"platform={platform}, is_mock={rs.is_mock}",
        ))

    return results


# ──────────────────────────────────────────────────────────────────────
# Feature Flags 校验
# ──────────────────────────────────────────────────────────────────────
def validate_feature_flags() -> List[ContractValidationResult]:
    """校验 feature flags 全部默认 False。"""
    results = []
    flags = DEFAULT_FLAGS

    # 1. 每个 flag 默认 False
    for name in flags.__dataclass_fields__:
        val = getattr(flags, name)
        results.append(ContractValidationResult(
            f"flag_default_false_{name}",
            passed=val is False,
            detail=f"{name}={val}",
        ))

    # 2. any_enabled() = False
    results.append(ContractValidationResult(
        "flags_any_enabled_false",
        passed=flags.any_enabled() is False,
        detail=f"any_enabled()={flags.any_enabled()}",
    ))

    # 3. as_dict 全 False
    d = flags.as_dict()
    results.append(ContractValidationResult(
        "flags_as_dict_all_false",
        passed=all(v is False for v in d.values()),
        detail=f"keys={sorted(d.keys())}, count={len(d)}",
    ))

    return results


# ──────────────────────────────────────────────────────────────────────
# Readiness Checklist 校验
# ──────────────────────────────────────────────────────────────────────
def validate_readiness_checklists() -> List[ContractValidationResult]:
    """校验联调准备清单全部未勾。"""
    results = []
    cl = default_checklists()

    # 1. is_ready = False
    results.append(ContractValidationResult(
        "readiness_is_ready_false",
        passed=cl.is_ready is False,
        detail=f"is_ready={cl.is_ready}",
    ))

    # 2. 全部 done=False
    all_items = cl.all_items()
    all_done_false = all(item.done is False for item in all_items)
    results.append(ContractValidationResult(
        "readiness_all_items_not_done",
        passed=all_done_false,
        detail=f"total_items={len(all_items)}",
    ))

    # 3. 五张清单齐备
    categories = ["env_var", "service_dependency", "rollback", "red_line", "smoke_test"]
    for cat in categories:
        items = getattr(cl, cat)
        results.append(ContractValidationResult(
            f"readiness_category_{cat}",
            passed=len(items) > 0,
            detail=f"category={cat}, count={len(items)}",
        ))

    return results


# ──────────────────────────────────────────────────────────────────────
# W1-W7 接口兼容性校验
# ──────────────────────────────────────────────────────────────────────
def validate_w1_w7_compat() -> List[ContractValidationResult]:
    """校验 W1-W7 各子包关键接口可导入、可实例化。"""
    results = []

    # W1: Brief / FactoryTaskState / parse_brief
    try:
        from backend.app.content_factory import Brief, FactoryTaskState, parse_brief
        results.append(ContractValidationResult("compat_w1_brief", True, "Brief/parse_brief 可导入"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w1_brief", False, str(e)))

    # W2: MockRecallClient / RecallResult
    try:
        from backend.app.content_factory.recall import MockRecallClient, RecallResult, RecallStatus
        client = MockRecallClient()
        results.append(ContractValidationResult("compat_w2_recall", True, "MockRecallClient 可实例化"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w2_recall", False, str(e)))

    # W3: DraftGenerator / DraftCandidate
    try:
        from backend.app.content_factory.drafting import DraftCandidate, DraftCandidateStatus
        results.append(ContractValidationResult("compat_w3_draft", True, "DraftCandidate 可导入"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w3_draft", False, str(e)))

    # W4: GatePipeline / CandidateGateReport
    try:
        from backend.app.content_factory.gates import GatePipeline, CandidateGateReport
        pipeline = GatePipeline()
        results.append(ContractValidationResult("compat_w4_gates", True, "GatePipeline 可实例化"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w4_gates", False, str(e)))

    # W5: MidPlatformMock / CandidateReviewQueue
    try:
        from backend.app.content_factory.midplatform.pages import MidPlatformMock
        mp = MidPlatformMock()
        results.append(ContractValidationResult("compat_w5_midplatform", True, "MidPlatformMock 可实例化"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w5_midplatform", False, str(e)))

    # W6: ProductionLineObserver / build_daily_report
    try:
        from backend.app.content_factory.observability.observer import ProductionLineObserver
        from backend.app.content_factory.observability.report import build_daily_report
        obs = ProductionLineObserver()
        results.append(ContractValidationResult("compat_w6_observer", True, "Observer/DailyReport 可实例化"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w6_observer", False, str(e)))

    # W7: RulePack / FeatureFlags / ReadinessChecklists / obs_contracts
    try:
        from backend.app.content_factory.rulepacks.schemas import RulePack
        from backend.app.content_factory.readiness import FeatureFlags, ReadinessChecklists
        from backend.app.content_factory.obs_contracts.mocks import (
            MockAlertSink, MockReportStore, MockScheduler,
        )
        results.append(ContractValidationResult("compat_w7_contracts", True, "W7 全部契约可导入"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w7_contracts", False, str(e)))

    # W8: SandboxResult / SandboxRunner
    try:
        from backend.app.content_factory.sandbox.schemas import SandboxResult, SandboxPathKind
        from backend.app.content_factory.sandbox.runner import SandboxRunner
        results.append(ContractValidationResult("compat_w8_sandbox", True, "Sandbox 可导入"))
    except Exception as e:
        results.append(ContractValidationResult("compat_w8_sandbox", False, str(e)))

    return results


# ──────────────────────────────────────────────────────────────────────
# 总入口
# ──────────────────────────────────────────────────────────────────────
def run_all_contract_validations() -> SandboxContractReport:
    """运行全部契约校验。"""
    return SandboxContractReport(
        rulepack_checks=validate_rulepacks(),
        flag_checks=validate_feature_flags(),
        readiness_checks=validate_readiness_checklists(),
        compat_checks=validate_w1_w7_compat(),
    )
