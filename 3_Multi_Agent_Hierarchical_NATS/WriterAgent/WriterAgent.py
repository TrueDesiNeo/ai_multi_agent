# =============================================================================
# File: WriterAgent.py
# Description:
#     Agent class responsible for generating well-structured article sections
#     using an LLM backend. Delegates to `draft_section` from `llm_openai`
#     and logs the start and completion of the drafting process.
#
# Key Features:
#     - Encapsulates section drafting logic for a given topic and section
#     - Supports optional reviewer feedback and source injection
#     - Uses structured logging for observability
#
# Usage:
#     agent = WriterAgent()
#     text = agent.draft(
#         topic="Edge AI in Healthcare",
#         section="Benefits and Use Cases",
#         style="neutral, SEO-optimized, concise but informative",
#         sources=["WHO report", "FDA guidance"],
#         feedback="Add a real-world example"
#     )
#
# Dependencies:
#     - Python 3.10+
#     - llm_openai.draft_section
#     - logging_init.logger
# =============================================================================

from __future__ import annotations
from typing import List, Optional
from llm_openai import draft_section
from logging_init import logger

class WriterAgent:
    def draft(self, topic: str, section: str, style: str, sources: List[str], feedback: Optional[str]) -> str:
        logger.info(f"writer.draft.start topic={topic}, section={section}, has_feedback={bool(feedback)}")
        text = draft_section(topic, section, style, sources, feedback)
        logger.info(f"writer.draft.ok words={len(text.split())}")
        return text
    