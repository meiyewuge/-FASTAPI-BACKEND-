"""B台裂变质检（V4 P1.1）。

四道 hard gate：duration_check / pts_check / playback_validate / md5_duplicate_check。
纯本地 ffmpeg/ffprobe，零成本、不触发火山。失败的视频不得进入 completed（由 remixer 重试/剔除）。
"""

from __future__ import annotations

import hashlib
import subprocess


def probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def has_audio(path: str) -> bool:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return bool(out)
    except Exception:  # noqa: BLE001
        return False


def _pts_series(path: str) -> list[float]:
    """取视频帧时间戳序列。优先 best_effort_timestamp_time，兜底 pkt_pts_time / pts_time。

    不同 ffprobe 版本字段可能为空/缺失，故按优先级逐项回退取值。
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=best_effort_timestamp_time,pkt_pts_time,pts_time",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip().splitlines()
    series: list[float] = []
    for line in out:
        cols = [c.strip() for c in line.split(",")]
        val = None
        for c in cols:                       # 取该帧第一个可解析的时间戳
            if c and c.lower() != "n/a":
                try:
                    val = float(c)
                    break
                except ValueError:
                    continue
        if val is not None:
            series.append(val)
    return series


def pts_check(path: str) -> tuple[bool, str]:
    """PTS 单调递增检查：发现时间回退 / 重复 / 异常跳跃即判失败。"""
    series = _pts_series(path)
    if len(series) < 2:
        return False, f"PTS 帧数不足({len(series)})"
    regress = dups = bigjump = 0
    last = series[0]
    diffs = []
    for t in series[1:]:
        d = t - last
        if d < 0:
            regress += 1            # 时间回退
        elif d == 0:
            dups += 1               # 重复
        else:
            diffs.append(d)
        last = t
    # 异常跳跃：单帧间隔 > 中位帧距 * 8
    if diffs:
        diffs_sorted = sorted(diffs)
        med = diffs_sorted[len(diffs_sorted) // 2]
        thr = max(med * 8, 1.0)
        bigjump = sum(1 for d in diffs if d > thr)
    ok = regress == 0 and dups == 0 and bigjump == 0
    return ok, f"frames={len(series)} regress={regress} dups={dups} bigjump={bigjump} monotonic={ok}"


def playback_validate(path: str) -> tuple[bool, str]:
    """完整解码到结尾：ffmpeg -v error -f null - 无 error 即通过。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"],
        capture_output=True, text=True, timeout=180,
    )
    err = (r.stderr or "").strip()
    ok = r.returncode == 0 and not err
    return ok, "decode ok" if ok else f"decode error: {err[:200]}"


def duration_check(path: str, lo: float, hi: float, tol: float = 0.5) -> tuple[bool, str]:
    dur = probe_duration(path)
    ok = (lo - tol) <= dur <= (hi + tol)
    return ok, f"duration={dur:.2f} target=[{lo},{hi}]±{tol} ok={ok}"


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def run_gates(path: str, batch_md5: set[str], lo: float, hi: float,
              tol: float = 0.5) -> dict:
    """跑四道 hard gate。md5 与 batch_md5 重复判失败。返回 qa 结果（不修改 batch_md5）。"""
    d_ok, d_log = duration_check(path, lo, hi, tol)
    p_ok, p_log = pts_check(path)
    v_ok, v_log = playback_validate(path)
    md5 = md5_of(path)
    dup = md5 in batch_md5
    final = "pass" if (d_ok and p_ok and v_ok and not dup) else "fail"
    return {
        "duration_ok": d_ok, "pts_ok": p_ok, "playable_ok": v_ok,
        "md5": md5, "md5_duplicate": dup,
        "final_status": final,
        "logs": [
            {"gate": "duration_check", "result": "pass" if d_ok else "fail", "detail": d_log},
            {"gate": "pts_check", "result": "pass" if p_ok else "fail", "detail": p_log},
            {"gate": "playback_validate", "result": "pass" if v_ok else "fail", "detail": v_log},
            {"gate": "md5_duplicate_check", "result": "fail" if dup else "pass", "detail": md5},
        ],
    }
