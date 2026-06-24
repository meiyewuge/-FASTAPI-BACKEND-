"""Intent Layer（业务理解层）：自然语言 → 结构化任务。轻量、规则驱动、零外部依赖。"""

from .intent_parser import Intent, parse_intent

__all__ = ["Intent", "parse_intent"]
