"""W7 联调准备 — feature flags + 联调准备清单（M1 条件施工 · 骨架阶段）。

设计依据：M1-W7 条件施工许可 二.6/二.7。

铁律：
- 所有 feature flag **默认 False**（严禁 21：不把 flag 默认打开）；
- 联调准备 ≠ 联调上线（严禁 22）——本模块只给清单与门控开关，不执行任何真实动作。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


# ──────────────────────────────────────────────────────────────────────
# Feature Flags（许可二.6，全部默认 False）
# ──────────────────────────────────────────────────────────────────────
@dataclass
class FeatureFlags:
    """M1 上线门控开关。全部默认关闭；打开需吴哥签发 + 逐项联调验证。"""

    M1_ENABLED: bool = False
    CONTENT_GENERATE_ENABLED: bool = False       # /content/generate
    REAL_9080_ENABLED: bool = False
    REAL_MODEL_ENABLED: bool = False
    APPROVED_WRITE_ENABLED: bool = False
    PUBLISH_ENABLED: bool = False
    REAL_OBSERVABILITY_ENABLED: bool = False      # 真实 DB/调度/监控

    def any_enabled(self) -> bool:
        return any(getattr(self, f.name) for f in self.__dataclass_fields__.values()
                   if isinstance(getattr(self, f.name), bool))

    def as_dict(self) -> Dict[str, bool]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# 冻结的默认实例（全 False）——导入即安全
DEFAULT_FLAGS = FeatureFlags()


# ──────────────────────────────────────────────────────────────────────
# 联调准备清单（许可二.7）
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ChecklistItem:
    key: str
    description: str
    done: bool = False           # 骨架期恒 False（未联调）
    blocking: bool = True        # 是否阻塞上线


@dataclass
class ReadinessChecklists:
    """五张联调准备清单（骨架期全部未勾）。"""

    env_var: List[ChecklistItem] = field(default_factory=list)
    service_dependency: List[ChecklistItem] = field(default_factory=list)
    rollback: List[ChecklistItem] = field(default_factory=list)
    red_line: List[ChecklistItem] = field(default_factory=list)
    smoke_test: List[ChecklistItem] = field(default_factory=list)

    def all_items(self) -> List[ChecklistItem]:
        return (self.env_var + self.service_dependency + self.rollback
                + self.red_line + self.smoke_test)

    @property
    def is_ready(self) -> bool:
        """全部阻塞项完成才算 ready（骨架期恒 False）。"""
        return all(i.done for i in self.all_items() if i.blocking)


def default_checklists() -> ReadinessChecklists:
    """M1 联调准备清单 v0.1（骨架，全未勾）。"""
    return ReadinessChecklists(
        env_var=[
            ChecklistItem("env_9080_base_url", "9080 只读召回地址（环境变量注入，非明文入库）"),
            ChecklistItem("env_model_provider", "模型供应商 provider/model/key（环境变量注入）"),
            ChecklistItem("env_ecs_ports", "ECS 端口分配（避开 18080/9080/9200/4013）"),
            ChecklistItem("env_report_db_dsn", "日报存储 DSN（REAL_OBSERVABILITY_ENABLED 门控）"),
        ],
        service_dependency=[
            ChecklistItem("dep_9080_readonly", "9080 只读可达且白名单装配就绪"),
            ChecklistItem("dep_9200_unreachable", "9200 对加工厂不可达（安全组+本机双保险）", blocking=True),
            ChecklistItem("dep_model_smoke", "模型供应商连通性 + 成本/延迟实测"),
            ChecklistItem("dep_rulepack_signed", "G1-G6 规则集正式签收（is_production_ready=True）"),
        ],
        rollback=[
            ChecklistItem("rb_flags_off", "所有 feature flag 可一键回到 False"),
            ChecklistItem("rb_git_tag", "回滚到明确 commit/tag，服务只读消费无库残留"),
            ChecklistItem("rb_private_storage", "加工厂私有存储可清，不污染正式库"),
        ],
        red_line=[
            ChecklistItem("rl_no_content_generate", "/content/generate 未开"),
            ChecklistItem("rl_no_approved_write", "approved 零写入口"),
            ChecklistItem("rl_no_9200", "9200 未触达"),
            ChecklistItem("rl_no_reindex", "reindex 未触发"),
            ChecklistItem("rl_no_site_published", "site_published 未产生"),
            ChecklistItem("rl_no_publish_pool", "真实发布池未接"),
        ],
        smoke_test=[
            ChecklistItem("st_brief_to_candidate", "Brief→候选全链路 mock 冒烟通过"),
            ChecklistItem("st_missing_halt", "缺料停单冒烟"),
            ChecklistItem("st_gate_blocked", "门检拦截冒烟"),
            ChecklistItem("st_review_flow", "审读→备发标记（非发布）冒烟"),
            ChecklistItem("st_daily_report", "日报生成冒烟"),
        ],
    )
