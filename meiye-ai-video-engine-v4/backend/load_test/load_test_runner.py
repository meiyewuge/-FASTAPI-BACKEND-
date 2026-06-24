"""Phase 6 压测执行器（生产级，非 demo）。

驱动现有公开链路（orchestrator → task runner → provider → cost_engine），
采集产能/稳定性/性能/成本指标，输出报告。**不修改主系统逻辑。**

用法：
  cd backend
  python -m load_test.load_test_runner --a 100 --b 500 --tenants 10 --stores 50 \
      --clips 5 --provider loadtest_flaky --fail-rate 0.15 --out load_test/reports

火山真实/ mock 切换：--provider volcano_seedance（需 .env 配 key） | mock | loadtest_flaky
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

# —— 必须在导入 config/db 前设好环境 ——
_DEF_DB = "sqlite:///./_loadtest.db"


def _bootstrap(args):
    os.environ["DATABASE_URL"] = args.db
    os.environ["VIDEO_PROVIDER"] = args.provider
    os.environ["LOADTEST_FAIL_RATE"] = str(args.fail_rate)
    os.environ["PROVIDER_RETRIES"] = str(args.retries)


def run(args) -> dict:
    _bootstrap(args)

    import config
    config.settings.video_provider = args.provider
    config.settings.provider_retries = args.retries
    config.settings.poll_interval = 0

    import db
    import load_test.flaky_provider  # noqa: F401  注册 flaky provider
    from cost_engine import ledger
    from models import CostRecord, Store, Tenant, Video
    from services import orchestrator
    from tasks import video_task
    from tasks.runner import execute_task
    from load_test.metrics import LatencyStats, Timer

    # 干净库
    db.engine.dispose()
    path = args.db.replace("sqlite:///", "")
    if path.startswith("./") and os.path.exists(path):
        os.remove(path)
    db.init_db()

    spt = max(1, args.stores // args.tenants)
    tenant_ids = [f"t{i:02d}" for i in range(args.tenants)]

    # 租户（大配额，避免熔断干扰压测）
    s = db.SessionLocal()
    for tid in tenant_ids:
        s.add(Tenant(id=tid, name=tid, quota=1e12))
    s.commit()
    s.close()

    a_lat, b_lat = LatencyStats(), LatencyStats()
    a_ok = a_total = 0
    b_ok = b_total = 0

    wall0 = time.perf_counter()

    # ---------- A台压测 ----------
    a_passes = math.ceil(args.a / (args.tenants * spt))
    for _ in range(a_passes):
        for tid in tenant_ids:
            if a_total >= args.a:
                break
            db_s = db.SessionLocal()
            plan = orchestrator.plan_from_intent(db_s, tid, f"做{spt}个广州美容院抗衰视频")
            task_ids = [t.id for t in plan["_tasks"]]
            db_s.close()
            for task_id in task_ids:
                if a_total >= args.a:
                    break
                a_total += 1
                with Timer() as tm:
                    execute_task(task_id)
                a_lat.add(tm.ms)
                ss = db.SessionLocal()
                t = video_task.get_task_any(ss, task_id)
                ok = t is not None and t.status == "done"
                ss.close()
                a_ok += 1 if ok else 0

    # 收集每租户母视频
    ss = db.SessionLocal()
    mothers = defaultdict(list)
    for v in ss.query(Video).filter(Video.type == "mother").all():
        mothers[v.tenant_id].append(v.id)
    ss.close()

    # ---------- B台压测 ----------
    ti = 0
    for _ in range(args.b):
        b_total += 1
        tid = tenant_ids[ti % len(tenant_ids)]
        ti += 1
        if not mothers.get(tid):
            continue
        mid = random.choice(mothers[tid])
        db_s = db.SessionLocal()
        task = orchestrator.submit_b(db_s, tid, mid, args.clips, strategy="mix")
        tbid = task.id
        db_s.close()
        with Timer() as tm:
            execute_task(tbid)
        b_lat.add(tm.ms)
        ss = db.SessionLocal()
        t = video_task.get_task_any(ss, tbid)
        ok = t is not None and t.status == "done"
        ss.close()
        b_ok += 1 if ok else 0

    wall = time.perf_counter() - wall0

    # ---------- 聚合 ----------
    ss = db.SessionLocal()
    recs = ss.query(CostRecord).all()
    n_mothers = ss.query(Video).filter(Video.type == "mother").count()
    n_viral = ss.query(Video).filter(Video.type == "viral").count()
    n_stores = ss.query(Store).count()
    ss.close()

    total_cost = round(sum(r.amount for r in recs), 4)
    total_dur = round(sum((r.duration or 0) for r in recs), 1)
    by_provider = defaultdict(lambda: {"count": 0, "cost": 0.0})
    for r in recs:
        by_provider[r.provider]["count"] += 1
        by_provider[r.provider]["cost"] = round(by_provider[r.provider]["cost"] + r.amount, 4)
    fallback_n = sum(1 for r in recs if r.provider == "mock")
    fallback_rate = round(fallback_n / len(recs), 4) if recs else 0.0

    total_videos = n_mothers + n_viral
    pipeline_vps = round(total_videos / wall, 2) if wall else 0.0

    # 真实 provider 受限产能估算（示例：每条 T 秒、并发 C）
    T_real, C = args.assume_seconds, args.assume_concurrency
    real_videos_per_day = int(C / T_real * 86400) if T_real else 0

    report = {
        "config": {
            "provider": args.provider, "fail_rate": args.fail_rate, "retries": args.retries,
            "a_tasks_target": args.a, "b_tasks_target": args.b,
            "tenants": args.tenants, "stores": n_stores, "clips_per_b": args.clips,
        },
        "totals": {
            "a_tasks": a_total, "b_tasks": b_total,
            "mother_videos": n_mothers, "viral_videos": n_viral, "total_videos": total_videos,
            "wall_seconds": round(wall, 2),
        },
        "stability": {
            "a_success_rate": round(a_ok / a_total, 4) if a_total else 0.0,
            "b_success_rate": round(b_ok / b_total, 4) if b_total else 0.0,
            "fallback_rate": fallback_rate,
        },
        "latency": {"a_台ms": a_lat.summary(), "b_台ms": b_lat.summary()},
        "throughput": {
            "a_tasks_per_sec": round(a_total / wall, 2) if wall else 0.0,
            "b_tasks_per_sec": round(b_total / wall, 2) if wall else 0.0,
            "pipeline_videos_per_sec": pipeline_vps,
            "est_videos_per_day_pipeline": int(pipeline_vps * 86400),
            "provider_bound_estimate": {
                "assume_seconds_per_video": T_real, "assume_concurrency": C,
                "est_videos_per_day": real_videos_per_day,
                "note": "mock 下延迟≈管线开销；真实产能受 provider 出片时延约束，按假设并发估算",
            },
        },
        "cost": {
            "total_cost": total_cost,
            "total_duration_sec": total_dur,
            "per_video_avg": round(total_cost / total_videos, 4) if total_videos else 0.0,
            "per_store_avg": round(total_cost / n_stores, 4) if n_stores else 0.0,
            "per_tenant_avg": round(total_cost / args.tenants, 4) if args.tenants else 0.0,
            "by_provider": dict(by_provider),
        },
    }

    _write_outputs(args.out, report, recs)
    return report


def _write_outputs(outdir: str, report: dict, recs) -> None:
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(outdir, "metrics_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # cost_analysis.csv：按 (tenant, store, provider, api) 聚合
    agg = defaultdict(lambda: {"count": 0, "units": 0.0, "duration": 0.0, "cost": 0.0})
    for r in recs:
        k = (r.tenant_id, r.store_id, r.provider, r.api_name)
        agg[k]["count"] += 1
        agg[k]["units"] += r.units
        agg[k]["duration"] += (r.duration or 0)
        agg[k]["cost"] = round(agg[k]["cost"] + r.amount, 4)
    with open(os.path.join(outdir, "cost_analysis.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tenant_id", "store_id", "provider", "api_name", "count", "units", "duration_sec", "total_cost"])
        for (tid, sid, prov, api), v in sorted(agg.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
            w.writerow([tid, sid, prov, api, v["count"], v["units"], round(v["duration"], 1), v["cost"]])

    with open(os.path.join(outdir, "load_test_summary.md"), "w", encoding="utf-8") as f:
        f.write(_summary_md(report))


def _summary_md(r: dict) -> str:
    c, t, st, lat, th, co = (r["config"], r["totals"], r["stability"],
                             r["latency"], r["throughput"], r["cost"])
    pb = th["provider_bound_estimate"]
    return f"""# 压测/产能报告 · load_test_summary

> Phase 6 · AI视频工厂压测与产能验证。provider=`{c['provider']}` fail_rate={c['fail_rate']}

## 1. 产能
- A台任务：**{t['a_tasks']}** · B台任务：**{t['b_tasks']}**（每条裂变 {c['clips_per_b']} 条）
- 产出视频：母视频 {t['mother_videos']} + 裂变 {t['viral_videos']} = **{t['total_videos']}**
- 墙钟耗时：{t['wall_seconds']}s
- 管线吞吐：**{th['pipeline_videos_per_sec']} 视频/秒** → 理论 **{th['est_videos_per_day_pipeline']:,} 视频/天**（管线上限，mock）
- 真实 provider 受限估算（假设 {pb['assume_seconds_per_video']}s/条 × 并发 {pb['assume_concurrency']}）：**{pb['est_videos_per_day']:,} 视频/天**

## 2. 稳定性
- A台成功率：**{st['a_success_rate']*100:.1f}%** · B台成功率：**{st['b_success_rate']*100:.1f}%**
- fallback 触发率：**{st['fallback_rate']*100:.1f}%**（主 provider 失败回退 mock 的占比，成功率仍由兜底保住）

## 3. 性能（延迟，毫秒）
| 链路 | avg | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- |
| A台 | {lat['a_台ms']['avg_ms']} | {lat['a_台ms']['p50_ms']} | {lat['a_台ms']['p95_ms']} | {lat['a_台ms']['p99_ms']} | {lat['a_台ms']['max_ms']} |
| B台 | {lat['b_台ms']['avg_ms']} | {lat['b_台ms']['p50_ms']} | {lat['b_台ms']['p95_ms']} | {lat['b_台ms']['p99_ms']} | {lat['b_台ms']['max_ms']} |

> mock 下延迟≈系统管线开销；真实延迟由火山出片时延决定。

## 4. 成本（cost_engine）
- 总成本：**{co['total_cost']}** · 总时长：{co['total_duration_sec']}s
- 单视频均成本：**{co['per_video_avg']}** · 单门店均成本：**{co['per_store_avg']}** · 单租户均成本：**{co['per_tenant_avg']}**
- 按 provider：{co['by_provider']}

## 5. 扩展能力
- 本轮 {c['tenants']} 租户 / {c['stores']} 门店。SQLite 为开发库，高并发写有锁瓶颈；
  生产用 PostgreSQL，真实并发受 provider 时延约束（IO 型，可横向扩 worker）。

明细见 `metrics_report.json` 与 `cost_analysis.csv`。
"""


def _parse():
    p = argparse.ArgumentParser(description="AI视频工厂压测")
    p.add_argument("--a", type=int, default=100, help="A台任务数")
    p.add_argument("--b", type=int, default=500, help="B台任务数")
    p.add_argument("--tenants", type=int, default=10)
    p.add_argument("--stores", type=int, default=50)
    p.add_argument("--clips", type=int, default=5, help="每个B台任务裂变条数")
    p.add_argument("--provider", default="loadtest_flaky", help="mock | loadtest_flaky | volcano_seedance")
    p.add_argument("--fail-rate", dest="fail_rate", type=float, default=0.15)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--assume-seconds", dest="assume_seconds", type=float, default=60.0)
    p.add_argument("--assume-concurrency", dest="assume_concurrency", type=int, default=20)
    p.add_argument("--db", default=_DEF_DB)
    p.add_argument("--out", default="load_test/reports")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse()
    rep = run(args)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"\n报告已写入：{args.out}/ (metrics_report.json, load_test_summary.md, cost_analysis.csv)")
