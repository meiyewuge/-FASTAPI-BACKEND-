#!/usr/bin/env python3
"""CLI — 单次搜索。

用法:
    python examples/run_single_search.py --query "美业 AI 趋势" --task-type chinese_industry_news --max-results 5

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


def main() -> None:
    parser = argparse.ArgumentParser(description="WUGE Search Router — 单次搜索")
    parser.add_argument("--query", required=True, help="搜索关键词")
    parser.add_argument(
        "--task-type",
        default="chinese_industry_news",
        choices=[t.value for t in TaskType],
        help="任务类型",
    )
    parser.add_argument("--max-results", type=int, default=5, help="最大结果数")
    parser.add_argument("--dry-run", default="true", help="dry_run 模式")

    args = parser.parse_args()

    config = SearchRouterConfig(dry_run=args.dry_run.lower() in ("true", "1", "yes"))
    router = SearchRouter(config=config)

    request = SearchRequest(
        query=args.query,
        task_type=TaskType(args.task_type),
        max_results=args.max_results,
    )

    result = router.search_sync(request)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
