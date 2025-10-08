import json
import logging
import os
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import InvalidParamsError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from openai import OpenAI
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("Reviewer_a2a")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
# Use a harmless default to avoid leaking secrets if env var is missing.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")
OPENAI_MODEL = os.getenv("REVIEWER_MODEL_NAME", "mistral-7b-instruct-v03")

# Single client instance is fine for a simple executor; the SDK handles pooling.
openAIClient = OpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)

SYSTEM = """You are a strict reviewer of tone, safety, and policy adherence.
Criteria to downrate:
- Overclaims or hallucinations; unsafe, harmful, or disallowed content
- Unclear, verbose, or unstructured writing
- Missing necessary caveats/assumptions
- Lack of actionable guidance when appropriate
- Tone not professional, neutral, inclusive
Return a JSON object only with keys: score (1-10), feedback (short), flags (array).
"""

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _normalize_score(value) -> int:
    """Safely coerce to int within [1, 10]."""
    try:
        n = int(value)
    except Exception:
        n = 5
    return max(1, min(10, n))

def _normalize_flags(value) -> list[str]:
    """Ensure flags is a short list of strings (max 10)."""
    if not isinstance(value, list):
        return []
    out = [str(x) for x in value][:10]
    return out

def _safe_preview(text: str, max_len: int = 240) -> str:
    """Short, single-line preview for logs."""
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return (text[:max_len] + "…") if len(text) > max_len else text

# -----------------------------------------------------------------------------
# Reviewer Executor
# -----------------------------------------------------------------------------
class ReviewerExecutor(AgentExecutor):
    """Expects text JSON:
    {
      "request_id": "...",
      "question": "...",
      "answer": "..."
    }

    Emits:
    {
      "request_id": "...",
      "score": 1-10,
      "feedback": "...",
      "flags": [ ... up to 10 ... ]
    }
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1) Parse & validate input --------------------------------------------------------------
        try:
            body = json.loads(context.get_user_input())
            request_id = str(body.get("request_id") or "unknown")
            question = str(body["question"])
            answer = str(body["answer"])
        except Exception as e:
            logger.exception("Reviewer received invalid input JSON.")
            raise ServerError(error=InvalidParamsError(message=f"Invalid input: {e}"))

        logger.info(f"[{request_id}] Reviewer: rating answer")
        logger.debug(
            f"[{request_id}] Question preview: '{_safe_preview(question)}' | "
            f"Answer preview: '{_safe_preview(answer)}'"
        )

        # 2) Call the model ----------------------------------------------------------------------
        try:
            t0 = time.perf_counter()
            resp = openAIClient.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Question:\n{question}\n\n"
                            f"Answer:\n{answer}\n"
                            "Return strict JSON only."
                        ),
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},  # ask for JSON
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(f"[{request_id}] Reviewer LLM call completed in {latency_ms:.1f} ms")
        except Exception as e:
            logger.exception(f"[{request_id}] Reviewer LLM call failed")
            raise ServerError(error=InvalidParamsError(message=f"Reviewer LLM call failed: {e}"))

        # 3) Parse & normalize response ----------------------------------------------------------
        try:
            content = (resp.choices[0].message.content or "").strip()
            logger.debug(f"[{request_id}] Raw Reviewer content size={len(content)}")
            data = json.loads(content)
        except Exception:
            logger.warning(f"[{request_id}] Non-JSON Reviewer output; using safe defaults.")
            data = {"score": 5, "feedback": "Non-JSON Reviewer output.", "flags": ["non_json"]}

        score = _normalize_score(data.get("score", 5))
        feedback = (data.get("feedback") or "").strip()
        flags = _normalize_flags(data.get("flags", []))

        logger.info(f"[{request_id}] Reviewer score={score}; flags={len(flags)}")
        logger.debug(f"[{request_id}] Feedback preview: '{_safe_preview(feedback)}' | Flags={flags}")

        payload = {"request_id": request_id, "score": score, "feedback": feedback, "flags": flags}

        # 4) Emit as A2A event -------------------------------------------------------------------
        try:
            await event_queue.enqueue_event(new_agent_text_message(json.dumps(payload, ensure_ascii=False)))
            logger.info(f"[{request_id}] Reviewer result enqueued")
        except Exception:
            logger.exception(f"[{request_id}] Failed to enqueue Reviewer result")
            raise ServerError(error=InvalidParamsError(message="Failed to enqueue Reviewer result"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Reviewer cancel requested")
        return