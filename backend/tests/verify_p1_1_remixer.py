"""V4 P1.1 Remixer 修复验证（短视频 PTS / 去重 / 可播放）。

基于真实问题样本（60 秒 / 较大视频）：验证 30 条全生成、0 stuck、不再 14 秒卡死、
PTS 单调、duration∈[25,35]、可播放到结尾、MD5 唯一、同策略不全同、cost=0、不触发火山、
ENABLE_COMPOSE=false、partial_done。

跑法：cd backend && python tests/verify_p1_1_remixer.py
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import config


def _make_source(path, seconds, w=640, h=360, audio=True):
    """生成接近真实样本的母视频（60 秒级、带音轨）。"""
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    # 生产口径短视频：duration ∈ [25,35]；用 540x960 控时长（仍真实重编码，非压测）
    config.settings.b_remix_target_lo = 25.0
    config.settings.b_remix_target_hi = 35.0
    config.settings.b_remix_width = 360       # 真实重编码，控分辨率以免单测过慢（非压测）
    config.settings.b_remix_height = 640
    config.settings.enable_compose = False

    # 防火山：任何 httpx 调用即失败
    import httpx
    def _boom(*a, **k):
        raise AssertionError("P1.1 裂变不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from b_engine import remixer, qa_checks

    d = tempfile.mkdtemp()
    # 真实问题样本：60 秒母视频（模拟 58/59/60），带音轨
    src = os.path.join(d, "mother60.mp4")
    _make_source(src, 60, 640, 360, audio=True)
    src_size_mb = os.path.getsize(src) / (1024 * 1024)
    print(f"  样本：60s 母视频 {src_size_mb:.1f}MB（带音轨）")

    stores = [{"id": 1, "name": "广州店", "city": "广州"}, {"id": 2, "name": "深圳店", "city": "深圳"}]
    outs = remixer.remix_videos("t1", src, 30, prompt="抗衰", strategy="mix", stores=stores)

    # 1) 30 条全部生成 + 0 stuck（全部走完 QA）
    assert len(outs) == 30, f"应生成 30 条，实际 {len(outs)}"
    print("  ✔ 30 条全部生成（0 stuck）")

    md5s, durs, strategies_md5 = set(), [], {}
    for o in outs:
        q = o["meta"]["qa"]
        # 2) PTS 单调 / 3) 可播放到结尾 / 4) duration∈[25,35]
        assert q["pts_ok"], f"PTS 非单调：{q['logs']}"
        assert q["playable_ok"], f"不可播放到结尾：{q['logs']}"
        assert q["duration_ok"] and 24.5 <= o["duration"] <= 35.5, f"duration={o['duration']}"
        # 复核 playback（独立再验，确认不再 14 秒卡死）
        ok, _ = qa_checks.playback_validate(o["local_path"])
        assert ok, "二次 playback_validate 失败"
        md5s.add(q["md5"]); durs.append(o["duration"])
        strategies_md5.setdefault(o["strategy"], set()).add(q["md5"])
    print("  ✔ 每条 PTS 单调 / 可播放到结尾 / duration∈[25,35]（不再 14 秒卡死）")

    # 5) MD5 唯一数显著高（理想全唯一）
    assert len(md5s) == 30, f"MD5 唯一数={len(md5s)}/30（应全唯一）"
    print(f"  ✔ MD5 唯一数={len(md5s)}/30（去重达标，远高于旧版）")

    # 6) 同策略下不能完全相同
    for skey, ms in strategies_md5.items():
        # 同策略至少 2 条时，MD5 不能全相同
        cnt = sum(1 for o in outs if o["strategy"] == skey)
        if cnt >= 2:
            assert len(ms) >= 2, f"策略 {skey} 下 {cnt} 条 MD5 全相同"
    print("  ✔ 同策略下不完全相同")

    # 7) cost=0（units=0）
    assert all(o["units"] == 0 for o in outs)
    assert all(o["meta"]["provider"] == "local_ffmpeg" for o in outs)
    print("  ✔ cost=0（units=0, provider=local_ffmpeg，不调火山）")

    # 8) ENABLE_COMPOSE=false
    assert config.settings.enable_compose is False
    print("  ✔ ENABLE_COMPOSE=false 保持")

    # 9) partial_done：QA 强制失败 → 该条不入 outputs，batch 不报错、不拖死
    bad = os.path.join(d, "bad.mp4")
    _make_source(bad, 2, 64, 64, audio=False)
    config.settings.b_remix_max_retry = 1
    orig_gates = remixer.qa_checks.run_gates
    def _fail_gates(path, batch_md5, lo, hi, tol=0.5):
        r = orig_gates(path, batch_md5, lo, hi, tol)
        r["final_status"] = "fail"; r["pts_ok"] = False   # 模拟坏段
        return r
    remixer.qa_checks.run_gates = _fail_gates
    try:
        outs_bad = remixer.remix_videos("t1", bad, 3, prompt="x", strategy="mix")
    finally:
        remixer.qa_checks.run_gates = orig_gates
    assert len(outs_bad) == 0, f"QA 全失败应 0 条入 outputs，实际 {len(outs_bad)}"
    print("  ✔ partial_done：QA 失败不入 outputs（坏样本 0 条通过，不拖死/不报错）")

    print("\n✅ V4 P1.1 Remixer ALL PASSED")


if __name__ == "__main__":
    main()
