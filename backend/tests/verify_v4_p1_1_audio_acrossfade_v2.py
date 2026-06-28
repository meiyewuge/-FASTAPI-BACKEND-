"""V4 P1.1 Remixer Audio Acrossfade Hotfix V2 验证。

V2 用 audio acrossfade（重叠混合）替代「单段 afade + 硬 concat」，从根上消除拼接点
相位/斜率不连续残留的「呲」声（9-10 秒切割点）。

验证：
- LONG filter 前后对比：80ms afade(对照，V1 兜底路径) vs acrossfade(80ms tri/qsin、120ms tri)。
- 方案A：acrossfade 路径每段不叠加单段 afade。
- 4 条样片落盘供人耳验收。
- 技术：ffmpeg 成功 / playback / PTS 单调 / duration∈[25,35] / 有音轨 / 音画同步 / MD5 去重 / partial_done。
- duration 缩短量说明：acrossfade 内在缩短 ≈ d×(段数-1)，被 windows 余量吸收 → 输出仍 = target。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p1_1_audio_acrossfade_v2.py
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import config

_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "audio_samples_v2")


def _make_source(path, seconds, w=320, h=240, audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def _stream_dur(path, kind):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries",
         "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True).stdout.strip().splitlines()
    return float(out[0]) if out and out[0] not in ("", "N/A") else None


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    config.settings.b_remix_target_lo = 25.0
    config.settings.b_remix_target_hi = 35.0
    config.settings.b_remix_width = 320
    config.settings.b_remix_height = 240
    config.settings.enable_compose = False

    import httpx
    def _boom(*a, **k):
        raise AssertionError("V2 不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from b_engine import remixer, qa_checks

    d = tempfile.mkdtemp()
    long_src = os.path.join(d, "mother_long.mp4")
    short_src = os.path.join(d, "mother_short.mp4")
    _make_source(long_src, 60, audio=True)
    _make_source(short_src, 5, audio=True)
    print("  样本：LONG 60s + SHORT 5s（440Hz 正弦音轨，9-10s 切割点易暴露相位不连续）")

    captured = {}
    orig_run = subprocess.run
    def _cap_run(cmd, *a, **k):
        if isinstance(cmd, list) and "-filter_complex" in cmd:
            captured["fc"] = cmd[cmd.index("-filter_complex") + 1]
        return orig_run(cmd, *a, **k)

    # 默认 V2 常量备份
    base = dict(D=remixer._AUDIO_XFADE_D, C1=remixer._AUDIO_XFADE_C1, C2=remixer._AUDIO_XFADE_C2,
                MIN=remixer._AUDIO_XFADE_MIN_SEG, FADE=remixer._AUDIO_FADE)

    def _gen(src, dur_hint, out_name, *, xd=None, c1=None, c2=None, xmin=None, fade=None):
        if xd is not None: remixer._AUDIO_XFADE_D = xd
        if c1 is not None: remixer._AUDIO_XFADE_C1 = c1
        if c2 is not None: remixer._AUDIO_XFADE_C2 = c2
        if xmin is not None: remixer._AUDIO_XFADE_MIN_SEG = xmin
        if fade is not None: remixer._AUDIO_FADE = fade
        out = os.path.join(_SAMPLE_DIR, out_name)
        remixer.subprocess.run = _cap_run
        try:
            remixer._build_variant(src, out, seed=7, dur=dur_hint, audio=True,
                                   target=30.0, top_text="测试", cta_text="关注")
        finally:
            remixer.subprocess.run = orig_run
            remixer._AUDIO_XFADE_D, remixer._AUDIO_XFADE_C1 = base["D"], base["C1"]
            remixer._AUDIO_XFADE_C2, remixer._AUDIO_XFADE_MIN_SEG = base["C2"], base["MIN"]
            remixer._AUDIO_FADE = base["FADE"]
        return out

    # ---- 样片 1：80ms afade 对照（强制 V1 兜底：xmin 设极大 → 不走 acrossfade）----
    s_afade = _gen(long_src, 60.0, "LONG_80ms_afade_baseline.mp4", xmin=9999.0, fade=0.08)
    fc_afade = captured["fc"]
    assert "acrossfade" not in fc_afade and "afade=t=out:st=" in fc_afade, fc_afade
    print("  ✔ 对照样片：80ms afade（V1 兜底路径，含 afade、无 acrossfade）")

    # ---- 样片 2：acrossfade 80ms tri（主方案，方案A 不叠加单段 afade）----
    s_tri = _gen(long_src, 60.0, "LONG_acrossfade_80ms_tri.mp4")
    fc_tri = captured["fc"]
    assert "acrossfade=d=0.080:c1=tri:c2=tri" in fc_tri, fc_tri
    assert "afade=t=in" not in fc_tri, "方案A：acrossfade 路径不应叠加单段 afade"
    print("  ✔ 主方案样片：acrossfade 80ms tri（方案A，无单段 afade）")

    # ---- 样片 3：acrossfade 80ms qsin（备选，等功率）----
    s_qsin = _gen(long_src, 60.0, "LONG_acrossfade_80ms_qsin.mp4", c1="qsin", c2="qsin")
    assert "acrossfade=d=0.080:c1=qsin:c2=qsin" in captured["fc"], captured["fc"]
    print("  ✔ 备选样片：acrossfade 80ms qsin（等功率曲线）")

    # ---- 样片 4：acrossfade 120ms tri（强兜底）----
    s_120 = _gen(long_src, 60.0, "LONG_acrossfade_120ms_tri.mp4", xd=0.12)
    assert "acrossfade=d=0.120:c1=tri:c2=tri" in captured["fc"], captured["fc"]
    print("  ✔ 强兜底样片：acrossfade 120ms tri")

    # ---- SHORT 保持 V1 整段首尾 fade（不引入 loop acrossfade）----
    s_short = _gen(short_src, 5.0, "SHORT_v1_global_fade.mp4")
    fc_short = captured["fc"]
    assert "acrossfade" not in fc_short and "afade=t=out:st=" in fc_short, fc_short
    assert "{target" not in fc_short, fc_short
    print("  ✔ SHORT 保持 V1 整段首尾 fade（未引入 acrossfade，f-string 正确）")

    # ---- 技术验证 + 音画同步 + duration 缩短量 ----
    samples = {"80ms_afade": s_afade, "acrossfade_80ms_tri": s_tri,
               "acrossfade_80ms_qsin": s_qsin, "acrossfade_120ms_tri": s_120, "SHORT": s_short}
    print("  —— 各样片 时长/音画同步 ——")
    for name, p in samples.items():
        assert os.path.exists(p) and os.path.getsize(p) > 0, f"{name} 未生成"
        ok, log = qa_checks.playback_validate(p)
        assert ok, f"{name} playback 失败: {log}"
        pok, plog = qa_checks.pts_check(p)
        assert pok, f"{name} PTS 非单调: {plog}"
        cont = qa_checks.probe_duration(p)
        assert 24.5 <= cont <= 35.5, f"{name} duration={cont}"
        assert qa_checks.has_audio(p), f"{name} 缺音轨"
        vd, ad = _stream_dur(p, "v"), _stream_dur(p, "a")
        drift = abs((vd or 0) - (ad or 0))
        assert drift <= 0.30, f"{name} 音画流时长漂移过大: v={vd} a={ad}"
        print(f"    {name}: 容器={cont:.3f}s 视频流={vd}s 音频流={ad}s 漂移={drift:.3f}s")
    print("  ✔ 4+1 样片：ffmpeg 成功 / 可播放 / PTS 单调 / duration∈[25,35] / 有音轨 / 音画同步(漂移≤0.30s)")

    # duration 缩短量说明（acrossfade 内在缩短被 windows 余量吸收 → 输出仍 = target）
    n_seg = fc_tri.count("concat=n=")  # 仅作存在性；真实段数从 video concat 解析
    import re
    m = re.search(r"concat=n=(\d+):v=1:a=0", fc_tri)
    nseg = int(m.group(1)) if m else 0
    intrinsic_shrink = 0.08 * max(nseg - 1, 0)
    print(f"  ✔ duration 缩短量：段数={nseg}，acrossfade 内在缩短≈{intrinsic_shrink:.3f}s，"
          f"被 windows(总长≥target+1.0) 余量吸收 → 输出容器仍=30s（实测在 [25,35]）")

    # ---- 批量 remix（默认 acrossfade 80ms tri）：MD5 去重 + cost=0 + partial_done ----
    outs = remixer.remix_videos("t1", long_src, 3, prompt="抗衰", strategy="mix",
                                stores=[{"id": 1, "name": "广州店", "city": "广州"}])
    assert len(outs) == 3, len(outs)
    assert len({o["meta"]["qa"]["md5"] for o in outs}) == 3, "MD5 去重退化"
    assert all(o["units"] == 0 and o["meta"]["provider"] == "local_ffmpeg" for o in outs)
    assert all(24.5 <= o["duration"] <= 35.5 for o in outs)
    print("  ✔ 批量 remix：3 条全过 / MD5 3-3 唯一 / cost=0 / duration∈[25,35]")

    orig_gates = remixer.qa_checks.run_gates
    def _fail(path, bm, lo, hi, tol=0.5):
        r = orig_gates(path, bm, lo, hi, tol); r["final_status"] = "fail"; r["pts_ok"] = False
        return r
    remixer.qa_checks.run_gates = _fail
    try:
        bad = remixer.remix_videos("t1", short_src, 2, prompt="x", strategy="mix")
    finally:
        remixer.qa_checks.run_gates = orig_gates
    assert len(bad) == 0, f"partial_done 退化: {len(bad)}"
    print("  ✔ partial_done 不退化（QA 失败 0 入 outputs）")

    print(f"\n  样片目录（供人耳验收，重点听 9-10s 切割点）：{_SAMPLE_DIR}")
    for name, p in samples.items():
        print(f"    {name}: {p}")
    print("\n✅ V4 P1.1 Audio Acrossfade Hotfix V2 ALL PASSED")


if __name__ == "__main__":
    main()
