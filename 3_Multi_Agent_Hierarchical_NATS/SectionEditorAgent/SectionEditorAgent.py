# =============================================================================
# File: SectionEditorAgent.py
# Description:
#     Agent class responsible for planning article structure by generating
#     SEO-friendly sections from a given topic using an LLM backend.
#     Delegates to `break_into_sections` from `llm_openai` and logs the
#     start and completion of section planning.
#
# Key Features:
#     - Encapsulates section planning logic for a given topic
#     - Uses structured logging for observability
#     - Designed for integration into agent-based workflows
#
# Usage:
#     agent = SectionEditorAgent()
#     sections = agent.plan("Edge AI in Healthcare", max_sections=6)
#
# Dependencies:
#     - Python 3.10+
#     - llm_openai.break_into_sections
#     - logging_init.logger
#
# =============================================================================

from __future__ import annotations
from typing import List
from llm_openai import break_into_sections
from logging_init import logger

class SectionEditorAgent:
    def plan(self, topic: str, max_sections: int) -> List[str]:
        logger.info(f"section.plan.start topic={topic}, max_sections={max_sections}")
        sections = break_into_sections(topic, max_sections)
        logger.info(f"section.plan.ok sections={len(sections)}")
        return sections