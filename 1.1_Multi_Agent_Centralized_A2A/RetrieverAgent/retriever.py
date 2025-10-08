import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import InvalidParamsError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError

from dotenv import load_dotenv
import requests

from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("retriever_a2a")

# Tavily configuration
tavily_api_key: Optional[str] = os.getenv("TAVILY_API_KEY")
tavily_api_url: Optional[str] = os.getenv("TAVILY_API_URL")  # e.g., "https://api.tavily.com"
retriever_top_k: int = int(os.getenv("RETRIEVER_TOP_K", "5"))
retriever_search_depth: str = os.getenv("RETRIEVER_SEARCH_DEPTH", "basic")  # "basic" | "advanced"
tavily_include_answer: bool = os.getenv("TAVILY_INCLUDE_ANSWER", "false").lower() in ("1", "true", "yes")
tavily_include_raw: bool = os.getenv("TAVILY_INCLUDE_RAW_CONTENT", "false").lower() in ("1", "true", "yes")
tavily_include_images: bool = os.getenv("TAVILY_INCLUDE_IMAGES", "false").lower() in ("1", "true", "yes")

SNIPPET_MAX_CHARS = int(os.getenv("RETRIEVER_SNIPPET_MAX_CHARS", "600"))  # Truncate long blobs

# -----------------------------------------------------------------------------
# Tavily wrapper that allows verify=False (INTENTIONALLY INSECURE)
# -----------------------------------------------------------------------------
class InsecureTavilyAPIWrapper(TavilySearchAPIWrapper):
    """
    A thin subclass that calls Tavily with cert verification disabled.
    WARNING: This is insecure and should only be used in trusted environments.
    """

    def raw_results(
        self,
        query: str,
        max_results: Optional[int] = 5,
        search_depth: Optional[str] = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        include_answer: Optional[bool] = False,
        include_raw_content: Optional[bool] = False,
        include_images: Optional[bool] = False,
    ) -> Dict:
        if include_domains is None:
            include_domains = []
        if exclude_domains is None:
            exclude_domains = []

        # LangChain may store the key as SecretStr or str-support both.
        key = (
            self.tavily_api_key.get_secret_value()
            if hasattr(self.tavily_api_key, "get_secret_value")
            else self.tavily_api_key
        )

        if not key:
            raise ValueError("Tavily API key is missing.")

        if not tavily_api_url:
            raise ValueError("TAVILY_API_URL is not set.")

        params = {
            "api_key": key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
        }

        # Log at DEBUG to avoid noisy payload logs at INFO.
        logger.debug(f"Tavily raw_results params: "
                     f"query_len={len(query)}, max_results={max_results}, depth={search_depth}, "
                     f"include_answer={include_answer}, include_raw={include_raw_content}, include_images={include_images}")

        # INTENTIONALLY insecure TLS. Log a warning so this is obvious.
        logger.warning("Using insecure HTTP (verify=False) for Tavily request-NOT for production use.")

        t0 = time.perf_counter()
        try:
            resp = requests.post(f"{tavily_api_url}/search", json=params, verify=False, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            dt = (time.perf_counter() - t0) * 1000.0
            logger.exception(f"Tavily request failed after {dt:.1f} ms")
            raise
        dt = (time.perf_counter() - t0) * 1000.0
        logger.info(f"Tavily search completed in {dt:.1f} ms")
        return resp.json()

# -----------------------------------------------------------------------------
# Search helper (wraps the tool)
# -----------------------------------------------------------------------------
async def _tavily_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """
    Execute a Tavily search and return a normalized list of snippets:
    [{title, url, snippet}, ...]
    """
    if not tavily_api_key:
        raise ServerError(error=InvalidParamsError(message="TAVILY_API_KEY not set"))
    if not tavily_api_url:
        raise ServerError(error=InvalidParamsError(message="TAVILY_API_URL not set"))

    # Respect the request's max_results but cap to retriever_top_k for safety.
    k = max(1, min(max_results, retriever_top_k))

    tool = TavilySearchResults(
        api_wrapper=InsecureTavilyAPIWrapper(tavily_api_key=tavily_api_key),
        max_results=k
    )

    logger.debug(f"Tavily tool prepared with k={k}, depth={retriever_search_depth}")
    # Tavily tool is synchronous under the hood; fine to call in async context for now.
    t0 = time.perf_counter()
    try:
        results = tool.invoke({
            "query": query,
            # Depending on the community tool version, you may pass extra kwargs;
            # the custom wrapper already uses module-level defaults.
        })
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        logger.exception(f"Tavily tool invocation failed after {dt:.1f} ms")
        raise ServerError(error=InvalidParamsError(message=f"Tavily error: {e}"))
    dt = (time.perf_counter() - t0) * 1000.0
    logger.info(f"Tavily tool returned {len(results)} result(s) in {dt:.1f} ms")

    # Normalize and truncate snippets for downstream payload size control.
    snippets: List[Dict[str, Any]] = []
    for idx, r in enumerate(results, start=1):
        title = (r.get("title") or "Untitled").strip()
        url = (r.get("url") or "http://example.com/").strip()
        raw = (r.get("content") or r.get("snippet") or "").strip()
        snippet = (raw[:SNIPPET_MAX_CHARS] + "…") if len(raw) > SNIPPET_MAX_CHARS else raw

        snippets.append({
            "title": title,
            "url": url,
            "snippet": snippet
        })

    # DEBUG preview to help triage issues without dumping entire payloads at INFO.
    if snippets:
        logger.debug(
            "First result preview: "
            f"title={snippets[0]['title']!r}, "
            f"url={snippets[0]['url']!r}, "
            f"snippet_len={len(snippets[0]['snippet'])}"
        )

    return snippets

# -----------------------------------------------------------------------------
# A2A Retriever Executor
# -----------------------------------------------------------------------------
class RetrieverExecutor(AgentExecutor):
    """A2A AgentExecutor; expects text message with JSON:
    {
      "request_id": "...",
      "question": "...",
      "max_results": 5
    }

    Returns an event with JSON:
    {
      "request_id": "...",
      "results": [{ "title": str, "url": str, "snippet": str }, ...]
    }
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Parse and validate input ---------------------------------------------------------------
        try:
            body = json.loads(context.get_user_input())
            request_id = str(body.get("request_id") or "unknown")
            question = str(body["question"]).strip()
            max_results = int(body.get("max_results", 5))
        except Exception as e:
            logger.exception("Invalid retriever input")
            raise ServerError(error=InvalidParamsError(message=f"Invalid input: {e}"))

        if not question:
            raise ServerError(error=InvalidParamsError(message="Retriever requires non-empty 'question'."))

        logger.info(f"[{request_id}] Retriever: '{question[:120]}' (max={max_results})")

        # Execute search -------------------------------------------------------------------------
        results = await _tavily_search(question, max_results)

        payload = {"request_id": request_id, "results": results}
        try:
            await event_queue.enqueue_event(new_agent_text_message(json.dumps(payload, ensure_ascii=False)))
            logger.info(f"[{request_id}] Enqueued {len(results)} result(s)")
        except Exception:
            logger.exception(f"[{request_id}] Failed to enqueue retriever results")
            raise ServerError(error=InvalidParamsError(message="Failed to enqueue retriever results"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # No long-running operations to cancel in this simple executor.
        logger.info("Retriever cancel requested")
        return
    