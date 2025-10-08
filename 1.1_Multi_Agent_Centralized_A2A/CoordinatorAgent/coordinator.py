import json
import logging
import os
from typing import Any, Dict, List, TypedDict

import httpx
from uuid import uuid4
from langgraph.graph import StateGraph, START, END

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import InvalidParamsError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from a2a.client import A2AClient
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import MessageSendParams, SendMessageRequest, Role, Message, Part, TextPart
import time

# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------
# Includes date and time automatically via %(asctime)s; level is controlled
# by LOG_LEVEL env (default INFO). Example format:
# 2025-10-06 15:45:01,234 INFO [coordinator_a2a] ...
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("coordinator_a2a")

# -----------------------------------------------------------------------------
# Environment configuration (A2A agent endpoints)
# -----------------------------------------------------------------------------
RETRIEVER_URL = os.getenv("RETRIEVER_URL", "http://localhost:10001/")
WRITER_URL    = os.getenv("WRITER_URL",    "http://localhost:10002/")
VERIFIER_URL  = os.getenv("VERIFIER_URL",  "http://localhost:10003/")

# -----------------------------------------------------------------------------
# A2A helpers
# -----------------------------------------------------------------------------
async def _a2a_client_for(base_url: str) -> A2AClient:
    """
    Create an A2A client by resolving the agent card from the given base URL.

    NOTE: This function creates an httpx.AsyncClient which is kept by the A2AClient.
    Ensure your process lifetime is appropriate (or add a shutdown hook to close).
    """
    logger.debug(f"Resolving A2A card for base_url={base_url!r}")
    httpx_client = httpx.AsyncClient(verify=False)
    resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
    card = await resolver.get_agent_card()
    logger.info(f"Resolved agent card for {base_url}")
    return A2AClient(httpx_client=httpx_client, agent_card=card)

async def _send_json(client: A2AClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a JSON payload to an A2A agent and return the parsed JSON response
    from the first 'text' part.

    Raises:
        RuntimeError: if the response does not include a 'text' part.
    """
    request_id = str(payload.get("request_id") or uuid4())
    # Keep payloads in DEBUG to avoid noisy logs at INFO level.
    logger.debug(f"[{request_id}] Sending payload to A2A: keys={list(payload.keys())}, size={len(json.dumps(payload, ensure_ascii=False))} bytes")

    message_payload = Message(
        role=Role.user,
        message_id=request_id,
        parts=[Part(root=TextPart(text=json.dumps(payload, ensure_ascii=False)))],
    )

    req = SendMessageRequest(id=str(uuid4()), params=MessageSendParams(message=message_payload))

    t0 = time.perf_counter()
    resp = await client.send_message(req)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    body = resp.model_dump()
    logger.info(f"[{request_id}] A2A call completed in {dt_ms:.1f} ms")
    logger.debug(f"[{request_id}] Full response body keys={list(body.keys())}")

    parts = body.get("result", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        logger.error(f"[{request_id}] Unexpected response format: missing 'text' in parts")
        raise RuntimeError("Unexpected response format: missing 'text' in parts")

    text = parts[0].get("text") if parts else "{}"
    logger.debug(f"[{request_id}] Response text size={len(text or '')} bytes")
    try:
        parsed = json.loads(text or "{}")
    except Exception as e:
        logger.exception(f"[{request_id}] Failed to parse response text as JSON")
        raise

    return parsed

# -----------------------------------------------------------------------------
# LangGraph state
# -----------------------------------------------------------------------------
class State(TypedDict, total=False):
    request_id: str
    question: str
    max_results: int
    max_retries: int
    attempts: int
    results: List[Dict[str, Any]]
    answer: str
    citations: List[str]
    score: int
    feedback: str

# -----------------------------------------------------------------------------
# Node: Retriever
# -----------------------------------------------------------------------------
async def _retrieve(state: State) -> Dict[str, Any]:
    """
    Call the Retriever agent with {request_id, question, max_results}
    and return {"results": contexts}.
    """
    rid = state.get('request_id', 'unknown')
    logger.info(f"[{rid}] Calling Retriever …")
    client = await _a2a_client_for(RETRIEVER_URL)

    req = {
        "request_id": state.get("request_id"),
        "question": state.get("question"),
        "max_results": state.get("max_results"),
    }

    out = await _send_json(client, req)
    results = out.get("results", [])
    logger.info(f"[{rid}] Retriever returned {len(results)} contexts")
    # Extract Contexts (pass through)
    return {"results": results}

# -----------------------------------------------------------------------------
# Node: Writer
# -----------------------------------------------------------------------------
async def _write(state: State) -> Dict[str, Any]:
    """
    Call the Writer agent with {request_id, question, contexts, feedback}
    and return {"answer", "citations", "attempts"}.

    'feedback' is the reviewer feedback from a previous iteration (if any).
    """
    rid = state.get('request_id', 'unknown')
    logger.info(f"[{rid}] Calling Writer …")
    client = await _a2a_client_for(WRITER_URL)

    req = {
        "request_id": state.get("request_id"),
        "question": state.get("question"),
        "contexts": state.get("results", []),
        "feedback": state.get("feedback"),
    }

    out = await _send_json(client, req)
    answer = out.get("answer", "") or ""
    citations = out.get("citations", []) or []
    prev_attempts = int(state.get("attempts", 0))
    attempts = prev_attempts + 1

    logger.info(f"[{rid}] Writer produced answer (words={len(answer.split())}), citations={len(citations)}, attempts={attempts}")
    return {
        "answer": answer,
        "citations": citations,
        "attempts": attempts,
    }

# -----------------------------------------------------------------------------
# Node: Verifier
# -----------------------------------------------------------------------------
async def _verify(state: State) -> Dict[str, Any]:
    """
    Call the Verifier agent with {request_id, question, answer}
    and return {"score", "feedback"}.
    """
    rid = state.get('request_id', 'unknown')
    logger.info(f"[{rid}] Calling Verifier …")
    client = await _a2a_client_for(VERIFIER_URL)

    req = {
        "request_id": state.get("request_id"),
        "question": state.get("question"),
        "answer": state.get("answer"),
    }

    out = await _send_json(client, req)
    score = int(out.get("score", 0))
    feedback = out.get("feedback", "") or ""
    logger.info(f"[{rid}] Verifier score={score}; feedback_len={len(feedback)}")
    logger.debug(f"[{rid}] Verifier feedback: {feedback}")
    return {"score": score, "feedback": feedback}

# -----------------------------------------------------------------------------
# Router: decide whether to loop back to writer or end
# -----------------------------------------------------------------------------
def _route(state: State) -> str:
    """
    If score < 7 and attempts < max_retries → loop back to writer.
    Otherwise → END.
    """
    rid = state.get('request_id', 'unknown')
    score = int(state.get("score", 0))
    attempts = int(state.get("attempts", 0))
    max_retries = int(state.get("max_retries", 2))

    if score < 7 and attempts < max_retries:
        logger.info(f"[{rid}] Routing: loop to writer (attempt={attempts}, score={score} < 7, max_retries={max_retries})")
        return "write"

    logger.info(f"[{rid}] Routing: END (attempt={attempts}, score={score}, max_retries={max_retries})")
    return END

# -----------------------------------------------------------------------------
# Coordinator Executor
# -----------------------------------------------------------------------------
class CoordinatorExecutor(AgentExecutor):
    """
    Orchestrates a mini LangGraph pipeline:
      START → retrieve → write → verify → (route: write | END)

    Expects user input JSON:
      {
        "request_id": "...",
        "question": "...",
        "max_results": 5,
        "max_retries": 2
      }

    Emits a final JSON payload with:
      {
        "request_id",
        "final_answer",
        "citations",
        "score",
        "verifier_feedback",
        "attempts"
      }
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Parse and validate inputs
        try:
            body = json.loads(context.get_user_input())
            request_id = str(body.get("request_id") or "unknown")
            question = str(body.get("question"))
            max_results = int(body.get("max_results", 5))
            max_retries = int(body.get("max_retries", 2))
        except Exception as e:
            logger.exception("Invalid input received by Coordinator")
            raise ServerError(error=InvalidParamsError(message=f"Invalid input: {e}"))

        logger.info(f"[{request_id}] Coordinator start (max_results={max_results}, max_retries={max_retries})")

        # Initial state for the graph
        initial: State = {
            "request_id": request_id,
            "question": question,
            "max_results": max_results,
            "max_retries": max_retries,
            "attempts": 0,
        }

        # Build the graph
        graph = StateGraph(State)
        graph.add_node("retrieve", _retrieve)
        graph.add_node("write", _write)
        graph.add_node("verify", _verify)

        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "write")
        graph.add_edge("write", "verify")
        graph.add_conditional_edges("verify", _route, {"write": "write", END: END})

        compiled = graph.compile()

        # Execute the graph to completion
        t0 = time.perf_counter()
        final: State = await compiled.ainvoke(initial)
        dt_ms = (time.perf_counter() - t0) * 1000.0

        # Construct final payload
        payload = {
            "request_id": final.get("request_id"),
            "final_answer": final.get("answer", ""),
            "citations": final.get("citations", []),
            "score": final.get("score", 0),
            "verifier_feedback": final.get("feedback", ""),
            "attempts": final.get("attempts", 0),
        }

        logger.info(f"[{request_id}] Coordinator done in {dt_ms:.1f} ms | score={payload.get('score')} attempts={payload.get('attempts')}")
        logger.debug(f"[{request_id}] Final payload size={len(json.dumps(payload, ensure_ascii=False))} bytes")

        # Emit final event to the queue
        await event_queue.enqueue_event(new_agent_text_message(json.dumps(payload, ensure_ascii=False)))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Nothing special to cancel in this simple flow; included for interface completeness.
        logger.info("Coordinator cancel called")
        return