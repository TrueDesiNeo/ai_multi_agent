import logging
from typing import TypedDict
from langchain_core.prompts import ChatPromptTemplate
from agent import get_chat_openai
from config import settings
from state import AppState

logger = logging.getLogger(__name__)

class WriterState(TypedDict, total=False):
    query: str
    search_snippets: str
    draft: str
    attempts: int
    verification: dict   # optional, may carry feedback for rewrite

# Base system prompt for the Writer node (sets tone and rules for responses)
SYSTEM_PROMPT = """\
You are a careful, concise assistant. Follow these rules:
- Write a short, direct answer (5-12 sentences) unless the question requires more.
- Prefer clarity, structure, and actionability.
- If uncertain, state assumptions briefly.
- Cite sources inline using markdown links only if provided in `search_snippets`.
- Maintain a professional, neutral, and inclusive tone.
- Do not include private, harmful, or disallowed content.
- Avoid making legal, medical, or financial claims beyond publicly available information.
"""

# Instructions applied if the Writer is rewriting a draft based on verifier feedback
REWRITE_INSTRUCTIONS = """\
Revise the draft using the Verifier feedback below. Keep it safe, concise, and precise. 
Do NOT pad with fluff. Improve tone, safety, and policy adherence as requested.
"""

def writer_node(state: AppState) -> AppState:
    """
    Writer node: Drafts (or rewrites) a concise answer from search snippets and user query.
    This node has two modes:
      1. Initial draft generation (query + snippets only)
      2. Rewrite mode (query + snippets + previous draft + verifier feedback)
    """

    query = state.get("query", "").strip()
    snippets = state.get("search_snippets", "").strip()
    attempts = int(state.get("attempts", 0))
    feedback = (state.get("verification") or {}).get("feedback")

    # Validate inputs early
    if not query:
        raise ValueError("Writer requires 'query' in state.")
    if not snippets:
        raise ValueError("Writer requires 'search_snippets' in state.")

    logger.info("Writer composing draft (attempt %d)", attempts + 1)
    logger.debug("Writer input query: %s", query)
    logger.debug("Writer input snippets length: %d", len(snippets))
    if feedback:
        logger.debug("Writer has verifier feedback, switching to rewrite mode")

    # Initialize LLM with configured model and safe temperature
    llm = get_chat_openai(temperature=0.3, model_name=settings.writer_model_name)

    # --- Case 1: Rewrite mode (Verifier provided feedback) ---
    if feedback:
        user_template = """\
User Query:
{query}

Search Snippets:
{snippets}

Previous Draft:
{draft}

Verifier Feedback:
{feedback}

Task:
{rewrite_instructions}
"""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                ("user", user_template),
            ]
        )
        input_vars = {
            "query": query,
            "snippets": snippets,
            "draft": state.get("draft", ""),
            "feedback": feedback,
            "rewrite_instructions": REWRITE_INSTRUCTIONS,
        }
        logger.debug("Writer prompt prepared with rewrite instructions")

    # --- Case 2: Initial draft mode ---
    else:
        user_template = """\
User Query:
{query}

Search Snippets:
{snippets}

Task:
Write a concise, safe, and helpful draft answer for the user.
"""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                ("user", user_template),
            ]
        )
        input_vars = {
            "query": query,
            "snippets": snippets,
        }
        logger.debug("Writer prompt prepared for initial draft")

    # Call the LLM with prompt and inputs
    draft = (prompt | llm).invoke(input_vars).content.strip()
    logger.info("Writer produced draft (chars=%d)", len(draft))
    logger.debug("Writer draft preview (first 200 chars): %s", draft[:200])

    # Update state with new draft, increment attempts, clear verification for fresh check
    state["draft"] = draft
    state["attempts"] = attempts + 1
    state["verification"] = {}  # always reset feedback after producing a new draft

    logger.info("Writer state updated (attempts=%d)", state["attempts"])

    # Return delta state (important for state graph consistency)
    return {
        "draft": draft,
        "attempts": attempts + 1,
        "verification": {},  # clear verification to force fresh check in next turn
    }
