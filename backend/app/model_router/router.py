"""模型路由器 — 四角色路由 + Fallback 纪律 + 四条硬边界编排。

设计依据：《模型路由与兜底层设计 V0.1》第二、三、五、八章。

本层职责边界（再次钉死）：
- 模型零事实产出：事实只能来自 task.used_materials（9080 approved 素材）；
- 出口只到 draft_candidate 候选态，publish_allowed 恒为 False；
- 不挂路由、不写库、不发布——这里只是"会写"，"真/不能乱/值不值得发"在别处。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .call_log import CallLog
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .clients import ModelClient, ModelReply, ModelTimeout
from .config import ModelRouterConfig, RoleConfig
from .prescan import prescan_g1
from .schemas import (
    DraftTask,
    FailReason,
    GateResult,
    MissingMaterialReport,
    ModelRole,
    RouterResult,
    TaskStatus,
    TaskType,
)
from .sensitive_guard import scan_sensitive

# ──────────────────────────────────────────────────────────────────────
# 任务类型 → 出稿角色路由表（设计 2.2）
# 值为 (出稿角色, 是否 review 双检, 是否 rewrite 润色)
# ──────────────────────────────────────────────────────────────────────
_ROUTING: Dict[TaskType, ModelRole] = {
    TaskType.FACT_STRICT: ModelRole.PRIMARY,        # 必须带 used_materials，模型不得补充事实
    TaskType.STATE_AESTHETIC: ModelRole.PRIMARY,    # + rewrite_model 润色
    TaskType.PLATFORM_REWRITE: ModelRole.REWRITE,   # 低成本批量多版本
    TaskType.HIGH_RISK: ModelRole.PRIMARY,          # + review_model 双检 + must_sign
    TaskType.IP_OPINION: ModelRole.REWRITE,         # 扩写 + primary 结构（Kimi 候选，受限扩写）
    TaskType.LONG_EXPANSION: ModelRole.REWRITE,     # Kimi 候选：只吃 used_materials 扩写
}

_NEEDS_REVIEW_DOUBLE_CHECK = {TaskType.HIGH_RISK}
_NEEDS_REWRITE_POLISH = {TaskType.STATE_AESTHETIC}
# Kimi 受限扩写模式适用的任务类型（设计第三章）
_RESTRICTED_EXPANSION = {TaskType.LONG_EXPANSION, TaskType.IP_OPINION}

# 受限扩写模式提示词前缀（Kimi 10 条件的调用侧落实：3/4/5/10）
RESTRICTED_EXPANSION_RULES = (
    "【受限扩写模式】你只能基于 used_materials 中给出的素材做表达扩写与润色；"
    "不得新增任何事实、数据、功效、案例；不得越过素材范围；"
    "只做表达扩写，不做事实定稿。"
)


def build_prompt(task: DraftTask) -> str:
    """组装生成提示词：Brief + used_materials。事实只能来自素材。"""
    material_lines = "\n".join(
        f"- [{m.get('id', '')}] {m.get('content', '')}" for m in task.used_materials
    )
    parts = []
    if task.task_type in _RESTRICTED_EXPANSION:
        parts.append(RESTRICTED_EXPANSION_RULES)
    parts.append(f"Brief：{task.brief}")
    parts.append(f"used_materials（唯一事实来源）：\n{material_lines}")
    if task.platform:
        parts.append(f"目标平台：{task.platform}")
    return "\n\n".join(parts)


@dataclass
class ModelRouter:
    """四角色模型路由器（mock 阶段：clients 全部为 MockModelClient）。

    gate_pipeline：G1-G6 六硬门挂接点（W4 工单实现后注入）。
    无论出稿方是 primary 还是 fallback，同一条 pipeline、同一套标准（硬边界一）。
    """

    config: ModelRouterConfig
    clients: Dict[ModelRole, ModelClient]
    gate_pipeline: Optional[Callable[[str, DraftTask], List[GateResult]]] = None
    call_log: CallLog = field(default_factory=CallLog)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    def __post_init__(self) -> None:
        self.call_log.daily_cost_limit = self.config.daily_cost_limit
        self.call_log.on_cost_alert = self.breaker.on_cost_exceeded

    # ──────────────────────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────────────────────
    def generate_draft(self, task: DraftTask):
        """生成候选草稿。

        返回 RouterResult（候选/失败/熔断态）或 MissingMaterialReport（缺料）。
        """
        # 硬边界二：没有 used_materials，唯一合法输出是缺料报告
        if not task.used_materials:
            return self._missing_material_report(task)

        # 硬边界四：熔断中 → 任务排队等待，不丢弃、不调用模型
        try:
            self.breaker.check_or_queue(task.content_id)
        except CircuitOpenError as e:
            status = TaskStatus.HELD if e.action == "hold" else TaskStatus.MANUAL_REVIEW
            return RouterResult(
                content_id=task.content_id,
                status=status,
                task_type=task.task_type,
                fail_reason=f"{FailReason.CIRCUIT_OPEN.value}:{e.reason}",
            )

        drafting_role = _ROUTING[task.task_type]
        prompt = build_prompt(task)

        reply, produced_role, fail = self._draft_with_fallback(task, drafting_role, prompt)
        if reply is None:
            status = (
                TaskStatus.BLOCKED_SENSITIVE
                if fail == FailReason.SENSITIVE_DATA.value
                else TaskStatus.MANUAL_REVIEW
                if self.breaker.is_open
                else TaskStatus.FAILED
            )
            return RouterResult(
                content_id=task.content_id,
                status=status,
                task_type=task.task_type,
                fail_reason=fail,
                total_model_calls=self.call_log.calls_for_content(task.content_id),
            )

        text = reply.text
        gate_results: List[GateResult] = []

        # 状态美学表达：rewrite_model 润色（设计 2.2 第二行）
        if task.task_type in _NEEDS_REWRITE_POLISH:
            polished = self._call_role_logged(
                task, ModelRole.REWRITE, f"【状态美学润色，不得新增事实】\n{text}"
            )
            if polished is not None:
                text = polished.text

        # 高风险内容：review_model 双检（设计 2.2 第四行），不依赖单模型直接过稿
        if task.task_type in _NEEDS_REVIEW_DOUBLE_CHECK:
            review = self._call_role_logged(
                task, ModelRole.REVIEW, f"【结构完整性+合规预检】\n{text}"
            )
            gate_results.append(
                GateResult(gate="review_model_precheck", passed=review is not None)
            )

        # 硬边界一：G1-G6 对 primary 与 fallback 输出执行完全相同的扫描，标准不降级
        gate_results.extend(self._run_gates(text, task))
        g1 = next((g for g in gate_results if g.gate == "G1_prescan"), None)
        if g1 and not g1.passed:
            self.breaker.on_g1_fail(task.content_id)

        must_sign = task.task_type == TaskType.HIGH_RISK or bool(task.risk_hint)

        return RouterResult(
            content_id=task.content_id,
            status=TaskStatus.DRAFT_CANDIDATE,
            task_type=task.task_type,
            text=text,
            produced_by_role=produced_role,
            produced_by_model=self.clients[produced_role].model_name,
            used_materials_ids=task.used_materials_ids,   # 硬边界二：输出必须绑定素材 ID
            gate_results=gate_results,
            must_sign=must_sign,
            total_model_calls=self.call_log.calls_for_content(task.content_id),
        )

    # ──────────────────────────────────────────────────────────────
    # 出稿 + Fallback 纪律（设计 5.1 / 5.2）
    # ──────────────────────────────────────────────────────────────
    def _draft_with_fallback(
        self, task: DraftTask, first_role: ModelRole, prompt: str
    ) -> tuple:
        """按 Fallback 纪律出稿：
        - 主→fallback 最多切 1 次；
        - 同一任务不重复调用同一失败模型（failed_models 集合）；
        - 质量不达标同模型打回重试 ≤max_retries；
        - 禁用词命中直接打回，不重试同模型；
        - 双失败 → 熔断 stop + manual_review。
        返回 (reply|None, produced_role|None, fail_reason|None)。
        """
        failed_models: Set[str] = set()
        chain = [first_role, ModelRole.FALLBACK] if first_role != ModelRole.FALLBACK else [first_role]
        last_fail: Optional[str] = None

        for idx, role in enumerate(chain):
            client = self.clients[role]
            role_cfg = self.config.roles[role]
            if client.model_name in failed_models:
                continue  # 纪律：不重复调用同一失败模型

            # 硬边界三：免费/低成本模型不得接触敏感数据（拦到即拒发，不自动脱敏）
            if role_cfg.is_low_cost:
                hits = scan_sensitive(prompt)
                if hits:
                    self._log(task, role, role_cfg, None, success=False,
                              fail_reason=f"{FailReason.SENSITIVE_DATA.value}:{';'.join(hits)}")
                    last_fail = FailReason.SENSITIVE_DATA.value
                    # 敏感数据是任务本身的问题，换模型也不行——直接终止
                    return None, None, last_fail

            attempts = 1 + role_cfg.max_retries
            for attempt in range(attempts):
                # 硬边界四：单篇文案模型调用次数熔断
                calls = self.call_log.calls_for_content(task.content_id)
                if calls + 1 > self.config.max_calls_per_content:
                    self.breaker.on_calls_exceeded(
                        task.content_id, calls + 1, self.config.max_calls_per_content
                    )
                    return None, None, FailReason.EXHAUSTED.value

                try:
                    reply = client.generate(prompt, task.used_materials)
                except ModelTimeout:
                    self._log(task, role, role_cfg, None, success=False,
                              fail_reason=FailReason.TIMEOUT.value)
                    last_fail = FailReason.TIMEOUT.value
                    if role == ModelRole.PRIMARY:
                        self.breaker.on_primary_failure()
                    failed_models.add(client.model_name)
                    break  # 超时：自动切 fallback，不在同模型上重试

                # G1 预扫描：命中禁用词 → 直接打回，不重试同模型
                banned = prescan_g1(reply.text)
                if banned:
                    self._log(task, role, role_cfg, reply, success=False,
                              fail_reason=f"{FailReason.BANNED_WORD.value}:{','.join(banned)}",
                              g1_result="fail")
                    self.breaker.on_g1_fail(task.content_id)
                    if role == ModelRole.PRIMARY:
                        self.breaker.on_primary_failure()
                    last_fail = FailReason.BANNED_WORD.value
                    failed_models.add(client.model_name)
                    break

                # 质量检查（mock 阶段以 reply.quality_score 代 review_model 评分）
                if reply.quality_score < self.config.quality_threshold:
                    self._log(task, role, role_cfg, reply, success=False,
                              fail_reason=FailReason.QUALITY_FAIL.value)
                    self.breaker.on_quality_low()
                    last_fail = FailReason.QUALITY_FAIL.value
                    if attempt + 1 < attempts:
                        continue  # 打回重试，≤max_retries 次
                    failed_models.add(client.model_name)
                    break

                # 成功
                self._log(task, role, role_cfg, reply, success=True, fail_reason=None,
                          g1_result="pass")
                self.breaker.on_quality_ok()
                if role == ModelRole.PRIMARY:
                    self.breaker.on_primary_success()
                return reply, role, None

            # 本角色失败；若已是链尾（fallback 也失败）→ 双失败熔断
            if idx == len(chain) - 1:
                self.breaker.on_double_failure(task.content_id)

        return None, None, last_fail or FailReason.EXHAUSTED.value

    # ──────────────────────────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────────────────────────
    def _run_gates(self, text: str, task: DraftTask) -> List[GateResult]:
        """六硬门挂接点：W4 注入完整 G1-G6；本层始终自带 G1 预扫描兜底。"""
        results = [GateResult(gate="G1_prescan", passed=not prescan_g1(text), hits=prescan_g1(text))]
        if self.gate_pipeline:
            results.extend(self.gate_pipeline(text, task))
        return results

    def _call_role_logged(self, task: DraftTask, role: ModelRole, prompt: str) -> Optional[ModelReply]:
        """润色/审读位单次调用（失败不致命，降级为跳过该环节并留痕）。"""
        client = self.clients.get(role)
        if client is None:
            return None
        role_cfg = self.config.roles[role]
        if role_cfg.is_low_cost and scan_sensitive(prompt):
            self._log(task, role, role_cfg, None, success=False,
                      fail_reason=FailReason.SENSITIVE_DATA.value)
            return None
        try:
            reply = client.generate(prompt, task.used_materials)
        except ModelTimeout:
            self._log(task, role, role_cfg, None, success=False,
                      fail_reason=FailReason.TIMEOUT.value)
            return None
        self._log(task, role, role_cfg, reply, success=True, fail_reason=None)
        return reply

    def _log(
        self,
        task: DraftTask,
        role: ModelRole,
        role_cfg: RoleConfig,
        reply: Optional[ModelReply],
        *,
        success: bool,
        fail_reason: Optional[str],
        g1_result: Optional[str] = None,
    ) -> None:
        client = self.clients[role]
        self.call_log.record(
            model_role=role,
            provider=client.provider,
            model_name=client.model_name,
            input_tokens=reply.input_tokens if reply else 0,
            output_tokens=reply.output_tokens if reply else 0,
            cost_per_1k_tokens=role_cfg.cost_per_1k_tokens,
            latency_ms=reply.latency_ms if reply else 0,
            success=success,
            fail_reason=fail_reason,
            content_id=task.content_id,
            used_materials_ids=task.used_materials_ids,
            g1_result=g1_result,
        )

    @staticmethod
    def _missing_material_report(task: DraftTask) -> MissingMaterialReport:
        """缺料报告：标记缺失素材类型 + 建议召回关键词（硬边界二）。"""
        type_hint = {
            TaskType.FACT_STRICT: ["事实卡", "检测摘要"],
            TaskType.STATE_AESTHETIC: ["事实卡", "引擎允许词表"],
            TaskType.PLATFORM_REWRITE: ["事实卡", "平台工艺卡素材"],
            TaskType.HIGH_RISK: ["事实卡", "合规依据"],
            TaskType.IP_OPINION: ["观点素材", "金句素材"],
            TaskType.LONG_EXPANSION: ["事实卡", "已审草稿"],
        }[task.task_type]
        return MissingMaterialReport(
            content_id=task.content_id,
            task_type=task.task_type,
            missing_material_types=type_hint,
            suggested_recall_keywords=[w for w in task.brief.split() if w][:5] or [task.brief[:20]],
        )
