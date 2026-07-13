"""测试 12 一级维度 + 77 二级标签（从 V0.1.3 迁移）。"""

from search_router.industry.industry_taxonomy import (
    INDUSTRY_DIMENSIONS,
    INDUSTRY_SUB_TAGS,
    all_sub_tags_count,
    get_dimension,
    validate_sub_tag,
    validate_sub_tags,
)


class TestIndustryDimensions:
    """12 一级维度。"""

    def test_12_dimensions(self):
        assert len(INDUSTRY_DIMENSIONS) == 12

    def test_dimensions_non_empty(self):
        for d in INDUSTRY_DIMENSIONS:
            assert d, f"空维度名: {d}"

    def test_dimensions_unique(self):
        assert len(INDUSTRY_DIMENSIONS) == len(set(INDUSTRY_DIMENSIONS))

    def test_expected_dimensions(self):
        expected = [
            "研发技术", "原材料与成分", "包装与包材", "生产制造",
            "品牌与产品", "门店与服务项目", "渠道与供应链",
            "消费者与用户趋势", "内容与营销打法", "数字化与AI工具",
            "政策法规与合规", "投融资并购与产业动态",
        ]
        assert INDUSTRY_DIMENSIONS == expected


class TestIndustrySubTags:
    """77 二级标签。"""

    def test_77_sub_tags(self):
        assert all_sub_tags_count() == 77

    def test_each_dimension_has_sub_tags(self):
        for d in INDUSTRY_DIMENSIONS:
            assert len(get_dimension(d)) > 0, f"维度无标签: {d}"

    def test_sub_tags_count_per_dimension(self):
        """每个维度 6~7 个标签。"""
        for d in INDUSTRY_DIMENSIONS:
            count = len(get_dimension(d))
            assert 6 <= count <= 7, f"维度 {d} 标签数 {count} 不在 6~7 范围"

    def test_sub_tags_unique_within_dimension(self):
        """同一维度内标签不重复。"""
        for d in INDUSTRY_DIMENSIONS:
            tags = get_dimension(d)
            assert len(tags) == len(set(tags)), f"维度 {d} 有重复标签"

    def test_validate_sub_tag_valid(self):
        assert validate_sub_tag("研发技术", "配方研发") is True

    def test_validate_sub_tag_invalid(self):
        assert validate_sub_tag("研发技术", "不存在标签") is False

    def test_validate_sub_tag_wrong_dimension(self):
        assert validate_sub_tag("原材料与成分", "配方研发") is False

    def test_validate_sub_tags_all_valid(self):
        assert validate_sub_tags("研发技术", ["配方研发", "功效成分研究"]) is True

    def test_validate_sub_tags_partial_invalid(self):
        assert validate_sub_tags("研发技术", ["配方研发", "不存在"]) is False
