import json
import logging
import os
import time
from typing import Any, Dict, List

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import InvalidParamsError
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from openai import OpenAI
from dotenv import load_dotenv

# NOTE: These imports were unused in the provided snippet.
# If you don't use them elsewhere, you can remove them.
# from langchain_core.prompts import ChatPromptTemplate
# from agent import get_chat_openai

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

# Include automatic date & time in every log line via %(asctime)s.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("writer_a2a")

MODEL_URL = os.getenv("MODEL_URL", "https://api.openai.com/v1")
# Use a harmless default to avoid accidentally leaking real secrets.
MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")
WRITER_MODEL = os.getenv("WRITER_MODEL_NAME", "llama-3-1-8b-instruct")

SYSTEM_PROMPT = """\
You are a careful, concise assistant. Follow these rules:
- Write a short, direct answer (5-12 sentences) unless the question requires more.
- Prefer clarity, structure, and actionability.
- Use [^n] markers and a 'References:' section with URLs in order.
- If feedback is provided, incorporate it judiciously.
- If uncertain, state uncertainty + next steps.
- If uncertain, state assumptions briefly.
- Cite sources inline using markdown links only if provided in `search_snippets`.
- Maintain a professional, neutral, and inclusive tone.
- Do not include private, harmful, or disallowed content.
- Avoid making legal, medical, or financial claims beyond publicly available information.
"""

REWRITE_INSTRUCTIONS = """\
Revise the draft using the Verifier feedback below. Keep it safe, concise, and precise.
Do NOT pad with fluff. Improve tone, safety, and policy adherence as requested.
"""

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _format_contexts(contexts: List[Dict[str, Any]]) -> str:
    """
    Render search contexts into a readable block for the model.

    Each context is expected to include keys: title, snippet, url.
    Missing keys are handled gracefully.
    """
    if not contexts:
        return "No web results."

    lines: List[str] = []
    for i, c in enumerate(contexts, start=1):
        title = str(c.get("title", "")).strip()
        snippet = str(c.get("snippet", "")).strip()
        url = str(c.get("url", "")).strip()
        lines.append(f"[{i}] {title}\n{snippet}\nURL: {url}\n")
    return "\n".join(lines)

def _parse_citations(text: str) -> List[str]:
    """
    Extract URLs from the 'References' section at the end of the answer.

    The Writer prompt asks for:
      - 'References:' section with raw URLs (one per line).
    This function is tolerant to bullets like -, *, or •.
    """
    cites: List[str] = []
    if not text:
        return cites

    # Find the 'References:' section if present.
    lower = text.lower()
    if "references" not in lower:
        return cites

    # Split once on 'References' (case-insensitive), then parse lines.
    try:
        _, refs_block = text.split("References", 1)  # preserve original casing
    except ValueError:
        return cites

    for line in refs_block.splitlines():
        clean = line.strip().lstrip("-*• ").strip()
        if clean.startswith(("http://", "https://")):
            cites.append(clean)
    return cites

# -----------------------------------------------------------------------------
# Writer Agent
# -----------------------------------------------------------------------------
class WriterExecutor(AgentExecutor):
    """Expects text JSON:
    {
      "request_id": "...",
      "question": "...",
      "contexts": [{"title","url","snippet"}, ...],
      "feedback": "..." | null
    }

    Behavior:
      - Builds a concise answer with [^n] footnote markers.
      - Emits a 'References:' section with URLs if contexts have links.
      - Incorporates verifier feedback when provided.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1) Parse and validate input ----------------------------------------------------------------
        try:
            body = json.loads(context.get_user_input())
            request_id = str(body.get("request_id") or "unknown")
            question = str(body.get("question", "")).strip()
            contexts = list(body.get("contexts", []))
            feedback = (body.get("feedback") or "").strip()
        except Exception as e:
            logger.exception("Failed to parse Writer input JSON.")
            raise ServerError(error=InvalidParamsError(message=f"Invalid input: {e}"))

        if not question:
            logger.error(f"[{request_id}] Missing 'question' in Writer input.")
            raise ServerError(error=InvalidParamsError(message="Writer requires 'question' in message."))

        # Log summary (keep details at DEBUG to avoid noisy logs at INFO)
        logger.info(f"[{request_id}] Writer received: contexts={len(contexts)} | feedback={'yes' if feedback else 'no'}")
        logger.debug(
            f"[{request_id}] Question chars={len(question)} | "
            f"First context title/snippet preview: "
            f"{(contexts[0].get('title','')[:80] if contexts else '')!r} / "
            f"{(contexts[0].get('snippet','')[:120] if contexts else '')!r}"
        )

        # 2) Compose model input ---------------------------------------------------------------------
        ctx_block = _format_contexts(contexts)
        fb_line = f"Verifier Feedback: {feedback}" if feedback else "No prior feedback."

        user_prompt = (
            f"Question:\n{question}\n\n"
            f"Contexts:\n{ctx_block}\n\n"
            f"{fb_line}\n\n"
            "Return: 1) Answer with [^n] markers, 2) 'References:' with URLs."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug(
            f"[{request_id}] Prepared messages: "
            f"system_len={len(SYSTEM_PROMPT)}, user_len={len(user_prompt)}"
        )
        logger.info(
            f"[{request_id}] Using model={WRITER_MODEL!r} at base_url={MODEL_URL!r}"
        )

        # 3) Call the model --------------------------------------------------------------------------
        try:
            client = OpenAI(base_url=MODEL_URL, api_key=MODEL_API_KEY)
            t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=WRITER_MODEL,
                messages=messages,
                temperature=0.3,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(f"[{request_id}] Writer LLM call completed in {latency_ms:.1f} ms")

            answer = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.exception(f"[{request_id}] Writer LLM call failed")
            raise ServerError(error=InvalidParamsError(message=f"Writer LLM call failed: {e}"))

        if not answer:
            logger.warning(f"[{request_id}] Writer produced an empty answer.")
        else:
            logger.debug(f"[{request_id}] Answer preview: {answer[:240]!r}... (len={len(answer)})")

        citations = _parse_citations(answer)
        logger.info(f"[{request_id}] Parsed citations: {len(citations)}")

        # 4) Emit result as an A2A event --------------------------------------------------------------
        payload = {"request_id": request_id, "answer": answer, "citations": citations}
        try:
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(payload, ensure_ascii=False))
            )
            logger.info(f"[{request_id}] Writer result enqueued (answer_len={len(answer)}, citations={len(citations)})")
        except Exception:
            logger.exception(f"[{request_id}] Failed to enqueue Writer result")
            # Re-raise as server error so caller sees an error
            raise ServerError(error=InvalidParamsError(message="Failed to enqueue Writer result"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Nothing to cancel in this simple executor; included for completeness.
        logger.info("Writer cancel requested")
        return