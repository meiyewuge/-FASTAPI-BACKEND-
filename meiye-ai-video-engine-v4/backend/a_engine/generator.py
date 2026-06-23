"""A台 · 母视频生成引擎（skeleton）。

职责：一句话需求 → AI 脚本 → 调用视频生成 → 输出 1 条精品母视频。
约束：禁止 import b_engine；共享能力经 utils / services。
"""


def generate_mother_video(tenant_id: str, prompt: str) -> dict:
    """生成 1 条母视频，返回 video 元信息（含下载/分发链接）。"""
    raise NotImplementedError
