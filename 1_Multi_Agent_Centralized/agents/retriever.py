import logging
import requests
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from typing import TypedDict
from config import settings
from state import AppState

# Set up module logger
logger = logging.getLogger(__name__)


class RetrieverState(TypedDict, total=False):
    """
    Subset of the state managed by the retriever node.
    """
    query: str                  # User input query text
    search_snippets: str        # Aggregated snippets returned from Tavily


def retriever_node(state: AppState) -> AppState:
    """
    Retriever node:
    - Uses TavilySearchResults to query the web for relevant information.
    - Aggregates search results into plain-text snippets.
    - Returns delta state with `search_snippets` field.
    """

    # --- Step 1: Validate query ---
    query = state.get("query") or ""
    if not query.strip():
        logger.error("Retriever received empty query in state.")
        raise ValueError("Retriever requires a non-empty 'query' in state.")

    # --- Step 2: Validate API key availability ---
    if not settings.tavily_api_key:
        logger.critical("Tavily API key missing. Please configure TAVILY_API_KEY.")
        raise EnvironmentError("TAVILY_API_KEY not found. Please set it in your environment.")

    logger.info("Retriever starting Tavily search | query=%s", query)

    # --- Step 3: Initialize Tavily search tool ---
    try:
        tool = TavilySearchResults(
            max_results=settings.retriever_top_k,
            search_depth="advanced",
            include_answer=True
        )
    except Exception as e:
        logger.exception("Failed to initialize TavilySearchResults tool.")
        raise

    # --- Step 4: Run search query ---
    try:
        results = tool.invoke({"query": query})
        logger.debug("Tavily raw results: %s", results)
    except requests.RequestException as e:
        logger.exception("Network error while invoking TavilySearchResults.")
        raise
    except Exception as e:
        logger.exception("Unexpected error while invoking TavilySearchResults.")
        raise

    # --- Step 5: Parse results into snippets ---
    snippets = []
    for idx, r in enumerate(results, start=1):
        title = r.get("title") or "Untitled"
        content = (r.get("content") or "").strip()
        url = r.get("url") or ""

        # Build snippet with title + content
        if content:
            snippet = f"- {title}: {content}"
        else:
            snippet = f"- {title}"

        snippets.append(snippet)
        logger.debug("Processed snippet #%d: %s", idx, snippet[:200])  # log only first 200 chars

    # --- Step 6: Aggregate snippets into single string ---
    aggregated = "\n".join(snippets) if snippets else "No results found."
    logger.info("Retriever completed | total_snippets=%d", len(snippets))

    # --- Step 7: Update state (delta only) ---
    state["search_snippets"] = aggregated
    return {"search_snippets": aggregated}
