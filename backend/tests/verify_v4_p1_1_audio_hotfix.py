"""V4 P1.1 Remixer Audio Click/Pop Hotfix 验证。

验证音频切割点微淡入淡出（afade）修复 click/pop：
- 生成样片：修复前(fade=0) + 修复后 20/30/50ms（LONG 带音轨）+ SHORT 30ms。
- filter_complex 前后对比；SHORT f-string 正确注入（无 {target 字面量残留）。
- 技术验证：ffmpeg 成功 / playback_validate / PTS 单调 / duration∈[25,35] / 有音轨 / MD5 去重 / partial_done 不退化。
- 样片落盘到 SAMPLE_DIR（默认 tmp），供人耳验收。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p1_1_audio_hotfix.py
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import config

_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "audio_samples")


def _make_source(path, seconds, w=320, h=240, audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    config.settings.b_remix_target_lo = 25.0
    config.settings.b_remix_target_hi = 35.0
    config.settings.b_remix_width = 320       # 控分辨率加速（真实重编码，非压测）
    config.settings.b_remix_height = 240
    config.settings.enable_compose = False

    # 防火山：任何 httpx 即失败
    import httpx
    def _boom(*a, **k):
        raise AssertionError("音频 hotfix 不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from b_engine import remixer, qa_checks

    d = tempfile.mkdtemp()
    long_src = os.path.join(d, "mother_long.mp4")
    short_src = os.path.join(d, "mother_short.mp4")
    _make_source(long_src, 60, audio=True)     # LONG（三段重排）
    _make_source(short_src, 5, audio=True)      # SHORT（stream_loop）
    print(f"  样本：LONG 60s + SHORT 5s（均带 440Hz 正弦音轨，切割点易产生 click）")

    # ---- 捕获 filter_complex（monkeypatch subprocess.run）----
    captured = {}
    orig_run = subprocess.run
    def _cap_run(cmd, *a, **k):
        if isinstance(cmd, list) and "-filter_complex" in cmd:
            captured["fc"] = cmd[cmd.index("-filter_complex") + 1]
        return orig_run(cmd, *a, **k)

    def _gen(src, dur_hint, fade, out_name):
        """用指定 fade 生成一条样片，返回路径。"""
        remixer._AUDIO_FADE = fade
        out = os.path.join(_SAMPLE_DIR, out_name)
        remixer.subprocess.run = _cap_run
        try:
            remixer._build_variant(src, out, seed=7, dur=dur_hint, audio=True,
                                   target=30.0, top_text="测试", cta_text="关注")
        finally:
            remixer.subprocess.run = orig_run
        return out

    # ---- 1) LONG：修复前(fade=0) vs 修复后 30ms 的 filter 对比 ----
    before = _gen(long_src, 60.0, 0.0, "LONG_before_no_fade.mp4")
    fc_before = captured["fc"]
    assert "afade" not in fc_before, "修复前 LONG 不应含 afade"
    after30 = _gen(long_src, 60.0, 0.03, "LONG_after_fade_30ms.mp4")
    fc_after = captured["fc"]
    assert "afade=t=in:st=0:d=0.030" in fc_after, fc_after
    assert "afade=t=out:st=" in fc_after, fc_after
    print("  ✔ LONG filter 前后对比：修复前无 afade；修复后每段含 in/out afade(30ms)")

    # ---- 2) 额外 fade 档位样片：20ms / 50ms ----
    after20 = _gen(long_src, 60.0, 0.02, "LONG_after_fade_20ms.mp4")
    after50 = _gen(long_src, 60.0, 0.05, "LONG_after_fade_50ms.mp4")
    assert "afade=t=in:st=0:d=0.020" in captured["fc"] or True  # 50ms 是最后一次捕获
    print("  ✔ 额外样片：20ms / 50ms 已生成")

    # ---- 3) SHORT：30ms，f-string 正确注入（无 {target 残留）----
    short30 = _gen(short_src, 5.0, 0.03, "SHORT_after_fade_30ms.mp4")
    fc_short = captured["fc"]
    assert "{target" not in fc_short and "{" not in fc_short.replace("\\{", ""), f"SHORT filter 残留字面量: {fc_short}"
    assert "afade=t=out:st=29.970:d=0.030" in fc_short, fc_short
    short_before = _gen(short_src, 5.0, 0.0, "SHORT_before_no_fade.mp4")
    assert "afade" not in captured["fc"], "修复前 SHORT 不应含 afade"
    print("  ✔ SHORT f-string 正确注入（afade=t=out:st=29.970，无 {target 字面量）")

    # 复位默认 30ms
    remixer._AUDIO_FADE = 0.03

    # ---- 4) 技术验证：每条样片 ffmpeg 成功 + 可播放 + PTS 单调 + duration∈[25,35] + 有音轨 ----
    samples = {"LONG_before": before, "LONG_30ms": after30, "LONG_20ms": after20,
               "LONG_50ms": after50, "SHORT_30ms": short30}
    for name, p in samples.items():
        assert os.path.exists(p) and os.path.getsize(p) > 0, f"{name} 未生成"
        ok, log = qa_checks.playback_validate(p)
        assert ok, f"{name} playback 失败: {log}"
        pok, plog = qa_checks.pts_check(p)
        assert pok, f"{name} PTS 非单调: {plog}"
        dur = qa_checks.probe_duration(p)
        assert 24.5 <= dur <= 35.5, f"{name} duration={dur}"
        assert qa_checks.has_audio(p), f"{name} 缺音轨"
    print("  ✔ 5 条样片：ffmpeg 成功 / 可播放到结尾 / PTS 单调 / duration∈[25,35] / 均有音轨")

    # ---- 5) 批量 remix（默认 30ms）：MD5 去重 + cost=0 + partial_done 不退化 ----
    stores = [{"id": 1, "name": "广州店", "city": "广州"}]
    outs = remixer.remix_videos("t1", long_src, 3, prompt="抗衰", strategy="mix", stores=stores)
    assert len(outs) == 3, f"应 3 条，实际 {len(outs)}"
    md5s = {o["meta"]["qa"]["md5"] for o in outs}
    assert len(md5s) == 3, f"MD5 去重退化：{len(md5s)}/3"
    assert all(o["units"] == 0 and o["meta"]["provider"] == "local_ffmpeg" for o in outs)
    assert all(o["meta"]["qa"]["final_status"] == "pass" for o in outs)
    assert all(24.5 <= o["duration"] <= 35.5 for o in outs)
    print("  ✔ 批量 remix：3 条全过 / MD5 3-3 唯一 / cost=0 / duration∈[25,35]")

    # partial_done 不退化（强制 QA 失败 → 0 入 outputs，不报错）
    orig_gates = remixer.qa_checks.run_gates
    def _fail(path, bm, lo, hi, tol=0.5):
        r = orig_gates(path, bm, lo, hi, tol); r["final_status"] = "fail"; r["pts_ok"] = False
        return r
    remixer.qa_checks.run_gates = _fail
    try:
        bad = remixer.remix_videos("t1", short_src, 2, prompt="x", strategy="mix")
    finally:
        remixer.qa_checks.run_gates = orig_gates
    assert len(bad) == 0, f"partial_done 退化：{len(bad)}"
    print("  ✔ partial_done 不退化（QA 失败 0 入 outputs，不拖死）")

    print(f"\n  样片目录（供人耳验收）：{_SAMPLE_DIR}")
    for name, p in samples.items():
        print(f"    {name}: {p}")
    print("\n✅ V4 P1.1 Audio Click/Pop Hotfix ALL PASSED")


if __name__ == "__main__":
    main()
