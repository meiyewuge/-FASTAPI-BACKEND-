#!/usr/bin/env python3
"""CLI — 每日情报。

用法:
    python examples/run_daily_intel.py --date 20260627 --dimensions "数字化与AI工具,品牌与产品"

输出 JSON 到 stdout。
dry_run=true 默认，不联网、不接真实 Key。
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from search_router.config import SearchRouterConfig
from search_router.models.search_request import SearchRequest, TaskType
from search_router.router import SearchRouter


# 维度 → 默认 query + task_type
_DIMENSION_QUERIES: dict[str, dict] = {
    "数字化与AI工具": {
        "query": "美业 AI 工具 数字化 趋势",
        "task_type": TaskType.GLOBAL_AI_TOOLS,
    },
    "品牌与产品": {
        "query": "美业 品牌 产品 新锐 趋势",
        "task_type": TaskType.CHINESE_INDUSTRY_NEWS,
    },
    "门店与服务项目": {
        "query": "美业 门店 服务项目 趋势",
        "task_type": TaskType.CHINESE_INDUSTRY_NEWS,
    },
    "内容与营销打法": {
        "query": "美业 营销 短视频 种草",
        "task_type": TaskType.FALLBACK_LIGHT_SEARCH,
    },
    "研发技术": {
        "query": "美业 研发 技术 配方",
        "task_type": TaskType.TECHNICAL_RESEARCH,
    },
    "政策法规与合规": {
        "query": "美业 政策 法规 合规 NMPA",
        "task_type": TaskType.OFFICIAL_DOCS,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="WUGE Search Router — 每日情报")
    parser.add_argument("--date", required=True, help="日期 YYYYMMDD")
    parser.add_argument("--dimensions", default="", help="维度列表（逗号分隔）")
    parser.add_argument("--max-results", type=int, default=5, help="每维度最大结果数")
    parser.add_argument("--dry-run", default="true", help="dry_run 模式")

    args = parser.parse_args()

    config = SearchRouterConfig.from_env()
    router = SearchRouter(config=config)

    # 解析维度
    if args.dimensions:
        dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    else:
        dimensions = list(_DIMENSION_QUERIES.keys())

    all_results: list[dict] = []
    for dim in dimensions:
        query_info = _DIMENSION_QUERIES.get(dim, {
            "query": f"美业 {dim} 趋势",
            "task_type": TaskType.FALLBACK_LIGHT_SEARCH,
        })

        request = SearchRequest(
            query=query_info["query"],
            task_type=query_info["task_type"],
            max_results=args.max_results,
        )

        result = router.search_sync(request)
        all_results.append({
            "dimension": dim,
            "result": result.to_dict(),
        })

    output = {
        "date": args.date,
        "dry_run": config.dry_run,
        "dimensions_searched": len(dimensions),
        "results": all_results,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
