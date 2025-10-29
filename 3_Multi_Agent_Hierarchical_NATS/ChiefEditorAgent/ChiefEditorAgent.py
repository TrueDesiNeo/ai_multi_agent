# =============================================================================
# File: ChiefEditorAgent.py
# Description:
#     Agent class responsible for generating SEO-friendly blog topics using
#     an LLM backend. Delegates to `list_topics` from `llm_openai` and logs
#     the start and completion of topic generation.
#
# Key Features:
#     - Encapsulates topic generation logic for a given domain area
#     - Uses structured logging for observability
#     - Designed for integration into agent-based workflows
#
# Usage:
#     agent = ChiefEditorAgent()
#     topics = agent.propose("Edge AI", max_topics=5)
#
# Dependencies:
#     - Python 3.10+
#     - llm_openai.list_topics
#     - logging_init.logger
#
# =============================================================================

from __future__ import annotations
from typing import List
from llm_openai import list_topics
from logging_init import logger

class ChiefEditorAgent:
    def propose(self, area: str, max_topics: int) -> List[str]:
        """
        Generate a list of topics for a given area using LLM.
        Logs start and completion of the process.
        """
        logger.info(f"chief.propose.start area={area}, max_topics={max_topics}")
        topics = list_topics(area, max_topics)
        logger.info(f"chief.propose.ok topics={len(topics)}")
        return topics
    