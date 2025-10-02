import logging
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, HumanMessage
from state import AppState

# Configure logger
logger = logging.getLogger(__name__)

class GraphState(TypedDict, total=False):
    """
    Shared state between agents in the graph.
    This acts as the central contract for the data
    exchanged across nodes in the orchestration pipeline.
    """
    # Conversation messages across nodes
    messages: Annotated[list[AnyMessage], add_messages]

    # Core working fields
    query: str                     # User query text
    search_snippets: str           # Aggregated text from Retriever
    draft: str                     # Draft response from Writer
    verification: dict             # Verification output { 'rating': int, 'feedback': str, 'safe': bool }
    attempts: int                  # Number of rewrite attempts performed so far


def coordinator_node(state: AppState) -> AppState:
    """
    Coordinator node: lightweight bookkeeping and logging.
    Its job is to:
      - Record the current state (search, draft, verification, attempts).
      - Ensure the query is injected as a HumanMessage if missing.
      - Return only the delta of new messages (never mutate existing state directly).
    """

    # Log current state details for debugging
    logger.info(
        "Coordinator received state | "
        f"query={state.get('query')!r}, "
        f"has_search={bool(state.get('search_snippets'))}, "
        f"has_draft={bool(state.get('draft'))}, "
        f"has_verification={bool(state.get('verification'))}, "
        f"attempts={state.get('attempts', 0)}"
    )

    # Prepare new messages (delta) instead of modifying the existing list
    msgs = []

    # If we have a query but no HumanMessage yet, add one
    if "query" in state and not any(m.type == "human" for m in state.get("messages", [])):
        logger.debug("Injecting HumanMessage for query: %s", state["query"])
        msgs = [HumanMessage(content=state["query"])]

    # Return only delta updates (important: do not overwrite state unnecessarily)
    if msgs:
        logger.debug("Coordinator returning new messages: %s", msgs)
        return {"messages": msgs}
    else:
        logger.debug("Coordinator returning empty delta (no new messages).")
        return {}


def route_from_coordinator(state: AppState) -> str:
    """
    Router used by the graph to choose the next node.
    Decision flow:
      1) If no search results yet -> go to retriever
      2) If no draft yet -> go to writer
      3) If no verification yet -> go to verifier
      4) If rating > 4 -> end
      5) Else -> retry writer if attempts < max_attempts, otherwise end
    """

    # Extract key state values
    has_search = bool(state.get("search_snippets"))
    has_draft = bool(state.get("draft"))
    verification = state.get("verification")
    attempts = int(state.get("attempts", 0))
    max_attempts = int(state.get("max_attempts", 3))

    logger.info(
        "Routing decision | "
        f"has_search={has_search}, has_draft={has_draft}, "
        f"verification={verification}, attempts={attempts}/{max_attempts}"
    )

    # Step 1: If no search results yet → go to retriever
    if not has_search:
        logger.debug("Routing to retriever (missing search_snippets).")
        return "retriever"

    # Step 2: If no draft yet → go to writer
    if not has_draft:
        logger.debug("Routing to writer (missing draft).")
        return "writer"

    # Step 3: Stop retrying if attempts exceeded max
    if attempts >= max_attempts:
        logger.warning("Max attempts reached (%d). Ending flow.", max_attempts)
        return "__end__"

    # Step 4: If no verification yet → go to verifier
    if not verification:
        logger.debug("Routing to verifier (no verification yet).")
        return "verifier"

    # Step 5: Check verification rating
    rating = verification.get("rating", 0)
    if rating > 4:
        logger.info("Verification rating (%d) is acceptable. Ending flow.", rating)
        return "__end__"
    else:
        logger.info("Verification rating (%d) too low. Re-routing to writer.", rating)
        return "writer"
