"""测试 12 knowledge_type 枚举 + 映射逻辑。"""

from search_router.industry.risk_classifier import KnowledgeType, KNOWLEDGE_TYPES
from search_router.industry.knowledge_type_mapper import (
    map_task_to_knowledge_type,
    infer_knowledge_type,
)
from search_router.models.search_request import TaskType


class TestKnowledgeTypes:
    """12 knowledge_type。"""

    def test_12_types(self):
        assert len(KNOWLEDGE_TYPES) == 12

    def test_expected_types(self):
        expected = {
            "trend", "tech", "ingredient", "packaging",
            "brand", "product", "store_case", "marketing",
            "compliance", "ai_tool", "supply_chain", "policy",
        }
        assert set(KNOWLEDGE_TYPES) == expected

    def test_snake_case(self):
        for kt in KNOWLEDGE_TYPES:
            assert kt == kt.lower(), f"非小写: {kt}"

    def test_no_camelcase(self):
        forbidden = ["storeCase", "aiTool", "supplyChain"]
        for f in forbidden:
            assert f not in KNOWLEDGE_TYPES


class TestTaskToKnowledge:
    """任务类型 → knowledge_type 映射。"""

    def test_chinese_industry_news(self):
        assert map_task_to_knowledge_type(TaskType.CHINESE_INDUSTRY_NEWS.value) == "store_case"

    def test_global_ai_tools(self):
        assert map_task_to_knowledge_type(TaskType.GLOBAL_AI_TOOLS.value) == "ai_tool"

    def test_official_docs(self):
        assert map_task_to_knowledge_type(TaskType.OFFICIAL_DOCS.value) == "compliance"

    def test_technical_research(self):
        assert map_task_to_knowledge_type(TaskType.TECHNICAL_RESEARCH.value) == "tech"

    def test_fallback(self):
        assert map_task_to_knowledge_type(TaskType.FALLBACK_LIGHT_SEARCH.value) == "trend"

    def test_unknown_defaults_trend(self):
        assert map_task_to_knowledge_type("unknown_type") == "trend"


class TestInferKnowledgeType:
    """关键词推断 knowledge_type。"""

    def test_ingredient(self):
        assert infer_knowledge_type("烟酰胺成分分析") == "ingredient"

    def test_packaging(self):
        assert infer_knowledge_type("包装设计趋势") == "packaging"

    def test_brand(self):
        assert infer_knowledge_type("新锐品牌定位") == "brand"

    def test_marketing(self):
        assert infer_knowledge_type("短视频营销策略") == "marketing"

    def test_ai_tool(self):
        assert infer_knowledge_type("AI视频生成工具") == "ai_tool"

    def test_tech(self):
        assert infer_knowledge_type("配方研发技术") == "tech"

    def test_trend(self):
        assert infer_knowledge_type("美业市场趋势报告") == "trend"

    def test_fallback_to_task_type(self):
        assert infer_knowledge_type("", "global_ai_tools") == "ai_tool"
