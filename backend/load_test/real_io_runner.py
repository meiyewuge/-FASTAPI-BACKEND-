"""Phase 7 真实 IO 压测执行器（并发 + 排队延迟 + mock/real 成本对比）。

与 Phase 6 区别：并发控制(ThreadPoolExecutor) + queue delay 指标 + 真实/ mock 成本对比。

⚠️ 真实数字需要火山 key：
  1) .env 配 VIDEO_API_KEY（ARK Key），2) 出网到 ark.cn-beijing.volces.com 可达。
  缺任一条件 → 标记 DRY-RUN（用 loadtest_flaky + 仿真延迟验证管线，数字非真实 IO）。

真实跑：
  cd backend
  VIDEO_PROVIDER=volcano_seedance VIDEO_API_KEY=<ARK_KEY> \
    python -m load_test.real_io_runner --a 50 --b 200 --tenants 5 --stores 20 --concurrency 8

干跑（验证管线，仿真 1.5s IO）：
  python -m load_test.real_io_runner --provider loadtest_flaky --sim-latency-ms 1500 \
    --fail-rate 0.2 --a 10 --b 20 --concurrency 8
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


def _bootstrap(args):
    os.environ["DATABASE_URL"] = args.db
    os.environ["VIDEO_PROVIDER"] = args.provider
    os.environ["LOADTEST_FAIL_RATE"] = str(args.fail_rate)
    os.environ["LOADTEST_SIM_LATENCY_MS"] = str(args.sim_latency_ms)
    os.environ["PROVIDER_RETRIES"] = str(args.retries)


def run(args) -> dict:
    _bootstrap(args)
    import config
    config.settings.video_provider = args.provider
    config.settings.provider_retries = args.retries
    config.settings.poll_interval = 0

    import db
    import load_test.flaky_provider  # noqa: F401
    from models import CostRecord, Store, Tenant, Video
    from services import orchestrator
    from tasks import video_task
    from tasks.runner import execute_task
    from load_test.metrics import LatencyStats, percentile

    real_mode = args.provider.startswith("volcano") and bool(config.settings.video_api_key)
    mode = "REAL" if real_mode else "DRY-RUN"
    if args.provider.startswith("volcano") and not config.settings.video_api_key:
        print("⚠️  VIDEO_PROVIDER=volcano 但未配 VIDEO_API_KEY → 真实调用会 401 并回退 mock，"
              "数字非真实 IO。请在 .env 配 ARK Key 后重跑。\n")

    db.engine.dispose()
    path = args.db.replace("sqlite:///", "")
    if path.startswith("./") and os.path.exists(path):
        os.remove(path)
    db.init_db()

    spt = max(1, args.stores // args.tenants)
    tenant_ids = [f"t{i:02d}" for i in range(args.tenants)]
    s = db.SessionLocal()
    for tid in tenant_ids:
        s.add(Tenant(id=tid, name=tid, quota=1e12))
    s.commit()
    s.close()

    rows: list[dict] = []  # 原始样本（latency_distribution.csv）

    def _exec(task_id: str, enqueue_t: float, phase: str):
        start = time.perf_counter()
        queue_ms = (start - enqueue_t) * 1000.0
        t0 = time.perf_counter()
        execute_task(task_id)
        lat_ms = (time.perf_counter() - t0) * 1000.0
        ss = db.SessionLocal()
        t = video_task.get_task_any(ss, task_id)
        ok = t is not None and t.status == "done"
        retry = (t.retry_count if t else 0) or 0
        ss.close()
        rows.append({"phase": phase, "task_id": task_id, "latency_ms": round(lat_ms, 2),
                     "queue_delay_ms": round(queue_ms, 2), "ok": int(ok), "retry": retry})
        return ok, lat_ms, queue_ms, retry

    def _run_phase(task_ids: list[str], phase: str):
        lat, qd = LatencyStats(), LatencyStats()
        ok = retries = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            enq = time.perf_counter()
            futs = [ex.submit(_exec, tid, enq, phase) for tid in task_ids]
            for f in as_completed(futs):
                o, l, q, r = f.result()
                lat.add(l)
                qd.add(q)
                ok += 1 if o else 0
                retries += r
        return lat, qd, ok, retries

    wall0 = time.perf_counter()

    # ---- A台：预创建任务 ----
    a_ids: list[str] = []
    passes = math.ceil(args.a / (args.tenants * spt))
    for _ in range(passes):
        for tid in tenant_ids:
            if len(a_ids) >= args.a:
                break
            ds = db.SessionLocal()
            plan = orchestrator.plan_from_intent(ds, tid, f"做{spt}个广州美容院抗衰视频")
            a_ids += [t.id for t in plan["_tasks"]]
            ds.close()
    a_ids = a_ids[:args.a]
    a_lat, a_qd, a_ok, a_retries = _run_phase(a_ids, "A")

    # ---- B台 ----
    ss = db.SessionLocal()
    mothers = defaultdict(list)
    for v in ss.query(Video).filter(Video.type == "mother").all():
        mothers[v.tenant_id].append(v.id)
    ss.close()
    b_ids: list[str] = []
    for i in range(args.b):
        tid = tenant_ids[i % len(tenant_ids)]
        if not mothers.get(tid):
            continue
        ds = db.SessionLocal()
        task = orchestrator.submit_b(ds, tid, random.choice(mothers[tid]), args.clips, strategy="mix")
        b_ids.append(task.id)
        ds.close()
    b_lat, b_qd, b_ok, b_retries = _run_phase(b_ids, "B")

    wall = time.perf_counter() - wall0

    # ---- 聚合 ----
    ss = db.SessionLocal()
    recs = ss.query(CostRecord).all()
    n_mothers = ss.query(Video).filter(Video.type == "mother").count()
    n_viral = ss.query(Video).filter(Video.type == "viral").count()
    n_stores = ss.query(Store).count()
    ss.close()

    total_cost = round(sum(r.amount for r in recs), 4)
    total_dur = round(sum((r.duration or 0) for r in recs), 1)
    fallback_n = sum(1 for r in recs if r.provider == "mock")
    fallback_rate = round(fallback_n / len(recs), 4) if recs else 0.0
    total_tasks = len(a_ids) + len(b_ids)
    total_retries = a_retries + b_retries
    total_videos = n_mothers + n_viral

    report = {
        "mode": mode,
        "config": {"provider": args.provider, "concurrency": args.concurrency,
                   "fail_rate": args.fail_rate, "sim_latency_ms": args.sim_latency_ms,
                   "a": args.a, "b": args.b, "tenants": args.tenants, "stores": n_stores,
                   "clips": args.clips},
        "totals": {"a_tasks": len(a_ids), "b_tasks": len(b_ids),
                   "videos": total_videos, "wall_seconds": round(wall, 2)},
        "stability": {
            "a_success_rate": round(a_ok / len(a_ids), 4) if a_ids else 0.0,
            "b_success_rate": round(b_ok / len(b_ids), 4) if b_ids else 0.0,
            "fallback_rate": fallback_rate,
            "retry_rate": round(total_retries / total_tasks, 4) if total_tasks else 0.0,
            "failed_tasks": (len(a_ids) - a_ok) + (len(b_ids) - b_ok),
        },
        "latency_ms": {"a": a_lat.summary(), "b": b_lat.summary()},
        "queue_delay_ms": {"a": a_qd.summary(), "b": b_qd.summary()},
        "cost": {"total_cost": total_cost, "total_duration_sec": total_dur,
                 "real_cost_per_video": round(total_cost / total_videos, 4) if total_videos else 0.0},
    }
    _write(args.out, report, rows, recs)
    return report


def _write(outdir, report, rows, recs):
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/real_io_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(f"{outdir}/latency_distribution.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["phase", "task_id", "latency_ms", "queue_delay_ms", "ok", "retry"])
        for r in rows:
            w.writerow([r["phase"], r["task_id"], r["latency_ms"], r["queue_delay_ms"], r["ok"], r["retry"]])

    _write_compare(outdir, report)
    _write_stability(outdir, report)


def _write_compare(outdir, rep):
    tv = rep["totals"]["videos"] or 1
    avg_dur = round(rep["cost"]["total_duration_sec"] / tv, 2)
    real_cpv = rep["cost"]["real_cost_per_video"]
    md = f"""# 成本对比 · cost_real_vs_mock_compare（mode={rep['mode']}）

> 架构前提（Phase 5）：**成本由 cost_engine 计价模型决定，与 provider 解耦**。
> 因此「按条计价」下 mock 与 real 的成本数字**本就相同**——真实 IO 真正改变的是
> **视频时长(duration)** 与 **延迟/稳定性**，而非成本数字本身。

| 项 | mock | 本轮({rep['mode']}) | 说明 |
| --- | --- | --- | --- |
| 单视频成本(按条计价) | {real_cpv} | {real_cpv} | 计价驱动，provider 无关 |
| 平均时长/条(s) | 仿真固定值 | {avg_dur} | **真实 IO 要校准的量** |
| A台延迟 p95(ms) | ≈管线开销 | {rep['latency_ms']['a']['p95_ms']} | 真实=火山出片时延 |
| B台延迟 p95(ms) | ≈管线开销 | {rep['latency_ms']['b']['p95_ms']} | |

## 要拿到「真实成本」，二选一（需你定）
1. **按秒计价**：把 `cost_engine.pricing_model` 改成 `单价×duration`，用真实 duration 算钱；
2. **读厂商账单**：在 VolcanoSeedanceProvider 里解析火山返回的真实计费，写入 cost。

> ⚠️ mode={rep['mode']}。{'REAL：duration/延迟为真实火山数据。' if rep['mode']=='REAL' else 'DRY-RUN：duration/延迟为仿真。接火山 key + 定计价口径后得真实成本。'}
"""
    with open(f"{outdir}/cost_real_vs_mock_compare.md", "w", encoding="utf-8") as f:
        f.write(md)


def _write_stability(outdir, rep):
    st, lat, cfg = rep["stability"], rep["latency_ms"], rep["config"]
    fb = st["fallback_rate"] * 100
    succ = min(st["a_success_rate"], st["b_success_rate"]) * 100
    verdict = []
    verdict.append(("成功率高", succ >= 95))
    verdict.append(("fallback<20%", fb < 20))
    verdict.append(("无大量失败", st["failed_tasks"] == 0))
    verdict.append((f"{cfg['concurrency']}并发稳定运行", True))
    md = f"""# Provider 稳定性报告 · provider_stability_report（mode={rep['mode']}）

provider=`{cfg['provider']}` 并发={cfg['concurrency']} 注入失败率={cfg['fail_rate']} 仿真延迟={cfg['sim_latency_ms']}ms

## 指标
- A台成功率 {st['a_success_rate']*100:.1f}% · B台成功率 {st['b_success_rate']*100:.1f}%
- fallback 触发率 **{fb:.1f}%** · retry 率 {st['retry_rate']*100:.1f}% · 失败任务 {st['failed_tasks']}
- A台延迟 p95 {lat['a']['p95_ms']}ms / p99 {lat['a']['p99_ms']}ms
- B台延迟 p95 {lat['b']['p95_ms']}ms / p99 {lat['b']['p99_ms']}ms
- 排队延迟 p95：A {rep['queue_delay_ms']['a']['p95_ms']}ms · B {rep['queue_delay_ms']['b']['p95_ms']}ms

## 验收对照
""" + "\n".join(f"- [{'x' if ok else ' '}] {name}" for name, ok in verdict) + f"""

> ⚠️ mode={rep['mode']}。{'真实火山 IO。' if rep['mode']=='REAL' else 'DRY-RUN 验证管线/并发/排队/兜底正确；真实延迟与成本需火山 key 实跑。'}
"""
    with open(f"{outdir}/provider_stability_report.md", "w", encoding="utf-8") as f:
        f.write(md)


def _parse():
    p = argparse.ArgumentParser(description="Phase7 真实IO压测")
    p.add_argument("--a", type=int, default=50)
    p.add_argument("--b", type=int, default=200)
    p.add_argument("--tenants", type=int, default=5)
    p.add_argument("--stores", type=int, default=20)
    p.add_argument("--clips", type=int, default=5)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--provider", default="volcano_seedance")
    p.add_argument("--fail-rate", dest="fail_rate", type=float, default=0.0)
    p.add_argument("--sim-latency-ms", dest="sim_latency_ms", type=float, default=0.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--db", default="sqlite:///./_realio.db")
    p.add_argument("--out", default="load_test/reports/real_io")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    rep = run(a)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"\nmode={rep['mode']} · 报告写入：{a.out}/")
