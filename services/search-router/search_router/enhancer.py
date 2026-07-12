"""GLMEnhancer — 产业字段 LLM 增强。

三锁铁律:
    SEARCH_ROUTER_DRY_RUN=false
    PROVIDER_GLM_SEARCH_ENABLED=true
    GLM_ENHANCER_ENABLED=true
    三者同时满足才允许真实 GLM 调用；否则强制 Mock 增强。

Mock 增强:
    不联网、不调 GLM，使用 industry/ 模块规则推断填充产业字段。
    可填充或修正: country_or_region / industry_dimension / subtags /
    business_relevance / applicable_scenario / risk_category / risk_notes /
    knowledge_type / evidence_excerpt / relevance_score

异常处理:
    JSON 解析失败 → 降级为 Mock 增强
    超时 / 异常 → 标记 enhancement_failed=True，不阻塞主链路
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from search_router.config import SearchRouterConfig
from search_router.industry.industry_mapper import (
    infer_industry_dimension,
    infer_sub_tags,
    infer_risk_category,
    infer_business_relevance,
    infer_applicable_scenario,
    build_risk_notes,
    build_suggested_action,
    is_legal_policy_official_source,
)
from search_router.industry.knowledge_type_mapper import infer_knowledge_type
from search_router.models.intelligence_card import IndustryIntelligenceCard


def should_use_real_enhancer(config: SearchRouterConfig) -> bool:
    """三锁判断: 只有三者同时满足才允许真实 GLM 增强。

    1. SEARCH_ROUTER_DRY_RUN=false
    2. PROVIDER_GLM_SEARCH_ENABLED=true
    3. GLM_ENHANCER_ENABLED=true
    """
    return (
        not config.dry_run
        and config.provider_glm_search_enabled
        and config.glm_enhancer_enabled
    )


@dataclass
class EnhancementResult:
    """增强结果。"""
    card: IndustryIntelligenceCard
    enhanced: bool = False
    enhancement_mode: str = "mock"  # "mock" / "real" / "failed"
    enhancement_failed: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "card": self.card.to_dict(),
            "enhanced": self.enhanced,
            "enhancement_mode": self.enhancement_mode,
            "enhancement_failed": self.enhancement_failed,
            "error": self.error,
        }


class GLMEnhancer:
    """产业字段 LLM 增强器。

    dry_run=true 或三锁不满足时强制 Mock 增强。
    三锁满足时走真实增强路径（通过注入的 adapter 调用，不联网）。
    Mock 增强使用 industry/ 模块规则推断填充产业字段。

    Args:
        config: 配置对象
        glm_adapter: 可选的 GLM adapter（用于真实增强路径）。
                     需实现 async _chat_completion(messages, model, temperature) -> dict。
                     测试时注入 fake adapter；生产环境注入 GLMSearchAdapter。
    """

    def __init__(
        self,
        config: SearchRouterConfig | None = None,
        glm_adapter: Any | None = None,
    ) -> None:
        self._config = config or SearchRouterConfig()
        self._use_real = should_use_real_enhancer(self._config)
        self._glm_adapter = glm_adapter

    @property
    def use_real(self) -> bool:
        """是否使用真实 GLM 增强。"""
        return self._use_real

    async def enhance(self, card: IndustryIntelligenceCard) -> EnhancementResult:
        """增强单条 card。

        三锁满足时走真实 GLM；否则走 Mock 增强。
        异常时不阻塞，标记 enhancement_failed=True。
        """
        if not self._use_real:
            return self._mock_enhance(card)

        try:
            return await self._real_enhance(card)
        except Exception as exc:
            # 异常不阻塞主链路
            return self._mock_enhance(card, failed=True, error=str(exc))

    async def enhance_batch(
        self, cards: list[IndustryIntelligenceCard]
    ) -> list[EnhancementResult]:
        """批量增强。"""
        results: list[EnhancementResult] = []
        for card in cards:
            result = await self.enhance(card)
            results.append(result)
        return results

    # ── Mock 增强 ──────────────────────────────────────

    def _mock_enhance(
        self,
        card: IndustryIntelligenceCard,
        failed: bool = False,
        error: str | None = None,
    ) -> EnhancementResult:
        """Mock 增强: 使用 industry/ 模块规则推断填充产业字段。

        不联网、不调 GLM。
        """
        query = card.original_search_query or card.title or ""
        task_type = card.provider_metadata.get("task_type", "") if card.provider_metadata else ""

        # 推断产业字段
        dimension = card.industry_dimension or infer_industry_dimension(query, task_type)
        knowledge_type = card.knowledge_type or infer_knowledge_type(query, task_type)
        risk_category = card.risk_category or infer_risk_category(query, knowledge_type)
        sub_tags = card.subtags if card.subtags else infer_sub_tags(dimension, query)
        business_relevance = card.business_relevance or infer_business_relevance(dimension, knowledge_type)
        applicable_scenario = card.applicable_scenario or infer_applicable_scenario(risk_category, knowledge_type)

        # legal_policy 非官方来源报警
        if risk_category == "legal_policy" and not is_legal_policy_official_source(card.url):
            risk_notes = "法规政策类内容：建议优先引用官方来源（.gov.cn），当前来源非官方"
        else:
            risk_notes = card.risk_notes or build_risk_notes(risk_category, knowledge_type)

        suggested_action = card.suggested_action or build_suggested_action(risk_category, card.confidence_score)

        # 填充或修正字段
        card.industry_dimension = dimension
        card.subtags = list(sub_tags)
        card.knowledge_type = knowledge_type
        card.risk_category = risk_category
        card.business_relevance = business_relevance
        card.applicable_scenario = applicable_scenario
        card.risk_notes = risk_notes
        card.suggested_action = suggested_action

        # country_or_region 默认中国
        if not card.country_or_region:
            card.country_or_region = "中国"

        # evidence_excerpt 从 summary 截取
        if not card.evidence_excerpt and card.summary:
            card.evidence_excerpt = card.summary[:200]

        # relevance_score 规则推断
        if card.relevance_score == 0.0:
            card.relevance_score = round(card.confidence_score * 0.8, 3)

        mode = "failed" if failed else "mock"
        return EnhancementResult(
            card=card,
            enhanced=True,
            enhancement_mode=mode,
            enhancement_failed=failed,
            error=error,
        )

    # ── 真实 GLM 增强（三锁满足时）────────────────────

    async def _real_enhance(self, card: IndustryIntelligenceCard) -> EnhancementResult:
        """真实 GLM 增强。

        三锁满足时才调用。通过注入的 glm_adapter 调用 _chat_completion()。
        不触发 web_search，不真实联网（测试用 fake adapter）。

        流程:
        1. 检查 adapter 是否注入且实现了 _chat_completion
        2. 构造 prompt
        3. 调用 adapter._chat_completion()
        4. 解析 JSON 响应
        5. 填充 card 产业字段
        6. JSON 解析失败 → 降级 Mock + enhancement_failed=True
        7. adapter 异常/超时 → 降级 Mock + enhancement_failed=True
        """
        # 检查 adapter 是否注入
        if self._glm_adapter is None:
            return self._mock_enhance(
                card, failed=True,
                error="GLM adapter not injected; cannot perform real enhancement"
            )

        # 检查 adapter 是否实现 _chat_completion
        if not hasattr(self._glm_adapter, "_chat_completion"):
            return self._mock_enhance(
                card, failed=True,
                error="GLM adapter does not implement _chat_completion()"
            )

        # 构造增强 prompt
        prompt = self._build_enhance_prompt(card)

        try:
            # 调用注入的 adapter（不联网，测试用 fake adapter）
            response = await self._glm_adapter._chat_completion(
                messages=prompt,
                model="glm-4-flash",
                temperature=0.1,
            )

            # 解析 GLM 响应中的 JSON
            enhanced_fields = self._parse_glm_response(response)

            if enhanced_fields is None:
                # JSON 解析失败 → 降级 Mock
                return self._mock_enhance(
                    card, failed=True,
                    error="JSON parse failed: GLM response is not valid JSON"
                )

            # 填充 card 产业字段
            self._apply_enhanced_fields(card, enhanced_fields)

            return EnhancementResult(
                card=card,
                enhanced=True,
                enhancement_mode="real",
                enhancement_failed=False,
                error=None,
            )

        except json.JSONDecodeError as exc:
            return self._mock_enhance(
                card, failed=True,
                error=f"JSON parse failed: {exc}"
            )
        except TimeoutError as exc:
            return self._mock_enhance(
                card, failed=True,
                error=f"Adapter timeout: {exc}"
            )
        except NotImplementedError as exc:
            return self._mock_enhance(
                card, failed=True,
                error=f"Adapter not implemented: {exc}"
            )
        except Exception as exc:
            return self._mock_enhance(
                card, failed=True,
                error=f"Enhancement exception: {exc}"
            )

    def _parse_glm_response(self, response: dict[str, Any]) -> dict[str, Any] | None:
        """解析 GLM chat completion 响应中的 JSON。

        GLM 响应格式:
        {
            "choices": [
                {
                    "message": {
                        "content": "{...JSON...}"
                    }
                }
            ]
        }

        Returns:
            解析后的字段 dict，或 None（解析失败）
        """
        if not response or not isinstance(response, dict):
            return None

        # 尝试从 choices[0].message.content 提取
        choices = response.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            return None

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content:
            return None

        # 尝试直接解析 JSON
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试从 markdown code block 中提取
        # ```json\n{...}\n```
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # 尝试从 { 到 } 提取
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    def _apply_enhanced_fields(
        self,
        card: IndustryIntelligenceCard,
        fields: dict[str, Any],
    ) -> None:
        """将 GLM 增强的字段写入 card。"""
        if not fields or not isinstance(fields, dict):
            return

        # 安全写入：只写入已知字段，不创建新字段
        field_map: dict[str, str] = {
            "country_or_region": "country_or_region",
            "industry_dimension": "industry_dimension",
            "subtags": "subtags",
            "business_relevance": "business_relevance",
            "applicable_scenario": "applicable_scenario",
            "risk_category": "risk_category",
            "risk_notes": "risk_notes",
            "knowledge_type": "knowledge_type",
            "evidence_excerpt": "evidence_excerpt",
            "relevance_score": "relevance_score",
        }

        for json_key, card_key in field_map.items():
            if json_key in fields:
                value = fields[json_key]
                if value is not None:
                    if card_key == "subtags" and isinstance(value, list):
                        setattr(card, card_key, [str(v) for v in value])
                    elif card_key == "relevance_score":
                        try:
                            setattr(card, card_key, float(value))
                        except (ValueError, TypeError):
                            pass
                    else:
                        setattr(card, card_key, str(value))

    def _build_enhance_prompt(self, card: IndustryIntelligenceCard) -> list[dict[str, str]]:
        """构造增强 prompt。"""
        return [
            {
                "role": "system",
                "content": (
                    "你是美业产业情报分析助手。请分析以下搜索结果，"
                    "填充或修正产业字段。返回 JSON 格式。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "title": card.title,
                    "summary": card.summary,
                    "source": card.source,
                    "url": card.url,
                    "current_dimension": card.industry_dimension,
                    "current_knowledge_type": card.knowledge_type,
                    "current_risk_category": card.risk_category,
                }, ensure_ascii=False),
            },
        ]
