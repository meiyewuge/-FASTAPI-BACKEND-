"""W5 审读包与内容经营中台联动子包（M1 条件施工 · 骨架阶段）。

设计依据：M1-W5 条件施工许可。

本子包为纯库层 mock：
- 接入 W4 ReviewPackagePre → candidate_review 队列 → 审读包详情 → 三页一弹窗；
- 人审动作只改内存状态 + 留痕，**不写库、不发布、不写 approved、不接真实后端**；
- marked_ready_to_publish 只是"人工备发标记"，不是发布/入库/approved；
- 不挂 FastAPI、不开 /content/generate、不触 9200/9080/reindex/site_published；
- publish_allowed / writes_approved 无写入口常量 False。

模块：
- schemas.py：CandidateReviewState / ReviewPackageDetail / VersionReviewView / GateSummaryRow / 队列条目
- state_machine.py：candidate_review 状态机 + 人审动作守卫
- detail.py：ReviewPackagePre → 审读包详情装配（G1/G3 高亮）
- queue.py：candidate_review 候选审读队列（内存）
- pages.py：中台三页一弹窗 mock 联动 + factory 结果分流
"""
from .schemas import (
    CandidateReviewEntry,
    CandidateReviewState,
    GateSummaryRow,
    ReviewPackageDetail,
    VersionReviewView,
)
from .state_machine import (
    InvalidReviewAction,
    mark_ready_to_publish,
    reject_for_revision,
    settle_from_review,
    submit_for_signoff,
)
from .detail import build_review_package_detail, map_review_state
from .queue import CandidateReviewQueue
from .pages import FrontdeskNotice, MidPlatformMock

__all__ = [
    "CandidateReviewEntry",
    "CandidateReviewQueue",
    "CandidateReviewState",
    "FrontdeskNotice",
    "GateSummaryRow",
    "InvalidReviewAction",
    "MidPlatformMock",
    "ReviewPackageDetail",
    "VersionReviewView",
    "build_review_package_detail",
    "map_review_state",
    "mark_ready_to_publish",
    "reject_for_revision",
    "settle_from_review",
    "submit_for_signoff",
]
