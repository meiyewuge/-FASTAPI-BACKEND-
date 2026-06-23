"""B台 · 混剪裂变引擎（skeleton）。

职责：母视频 → 自动切片 → 重组 → 改字幕/开头/结尾 → 输出 10~50 条裂变视频。
约束：禁止 import a_engine；共享能力经 utils / services。
"""


def remix_videos(tenant_id: str, source_video_id: str, count: int) -> list[dict]:
    """基于母视频批量产出裂变视频，返回 video 元信息列表。"""
    raise NotImplementedError
