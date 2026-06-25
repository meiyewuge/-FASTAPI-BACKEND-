"""业务资产回流层（V4 P0 预留）。

目标：把视频生产过程中的高价值「过程与经验」沉淀为候选池，未来经审核再进阿里云大库。
**不把 mp4 原文件 / Word 全文 / 压缩包内容默认写入大库**，仅记录过程数据与脱敏摘要。

三张表：
- workflow_runs        每次 A台/B台/批量任务的工作流记录（过程）
- video_feedback_signals 用户对视频的行为信号（play/select/download/...）
- knowledge_candidates  知识候选池（pending→approved/rejected/archived），审核后才进大库
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func

from db import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    run_id = Column(String(40), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    phone = Column(String(32), nullable=True)
    prompt = Column(Text, nullable=True)
    mode = Column(String(16), nullable=False)            # a_generate | b_remix | batch
    input_image_count = Column(Integer, nullable=False, default=0)
    input_file_count = Column(Integer, nullable=False, default=0)
    input_video_count = Column(Integer, nullable=False, default=0)
    input_text_length = Column(Integer, nullable=False, default=0)
    source_video_count = Column(Integer, nullable=False, default=0)
    output_video_count = Column(Integer, nullable=False, default=0)
    cost_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False, default="running")  # running|done|failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)


class VideoFeedbackSignal(Base):
    __tablename__ = "video_feedback_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    phone = Column(String(32), nullable=True)
    video_id = Column(Integer, nullable=True, index=True)
    action = Column(String(16), nullable=False)          # play|select|send_to_b|download|export|favorite|dislike|delete
    context = Column(Text, nullable=True)                # JSON：脱敏的轻量上下文
    created_at = Column(DateTime, server_default=func.now())


class KnowledgeCandidate(Base):
    __tablename__ = "knowledge_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    phone = Column(String(32), nullable=True)
    source_module = Column(String(16), nullable=False, default="video_v4")
    # prompt | script | strategy | workflow_summary | failure_case | user_feedback
    source_type = Column(String(24), nullable=False)
    task_id = Column(String(40), nullable=True)
    batch_id = Column(String(40), nullable=True)
    video_id = Column(Integer, nullable=True)
    title = Column(String(255), nullable=True)
    content_summary = Column(Text, nullable=True)        # 脱敏摘要，非原始全文
    tags = Column(Text, nullable=True)                   # JSON 数组
    raw_ref = Column(String(255), nullable=True)         # 指向原始数据的引用（不内联原文）
    risk_level = Column(String(8), nullable=False, default="low")  # low|medium|high
    status = Column(String(12), nullable=False, default="pending")  # pending|approved|rejected|archived
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(32), nullable=True)
    review_note = Column(String(255), nullable=True)
