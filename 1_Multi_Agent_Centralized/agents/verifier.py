# agents/verifier.py
import logging
import json
import re
from typing import TypedDict, Optional
from pydantic import BaseModel, Field, ValidationError

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from config import settings
from agent import get_chat_openai

# Configure logger specifically for this agent
logger = logging.getLogger("agents.verifier")
logger.setLevel(logging.DEBUG)  # default verbosity for this module


class VerifierState(TypedDict, total=False):
    draft: str
    verification: dict


class VerificationResult(BaseModel):
    """
    Structured output schema enforced for verification results.
    """
    rating: int = Field(description="Rating from 1 (poor) to 10 (excellent)")
    safe: Optional[bool] = Field(description="Whether the content is safe and policy-aligned")
    feedback: Optional[str] = Field(description="Specific, actionable feedback to improve tone, safety, and clarity")


# ---------------- Prompts ----------------

VERIFIER_SYSTEM_PROMPT = """\
You are a strict reviewer of tone, safety, and policy adherence.
Criteria to downrate:
- Overclaims or hallucinations; unsafe, harmful, or disallowed content
- Unclear, verbose, or unstructured writing
- Missing necessary caveats/assumptions
- Lack of actionable guidance when appropriate
- Tone not professional, neutral, inclusive
"""

USER_TEMPLATE = """\
Draft to Review:
{draft}

Evaluate the draft strictly by the criteria.
"""

# ---------------- Helpers: JSON cleanup & repair ----------------


def _balanced_json_object(text: str) -> str | None:
    """
    Extract the first top-level {...} JSON object using brace balancing.
    Handles cases where the model wraps JSON with prose.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _strip_code_fences(text: str) -> str:
    """
    If output is wrapped in ```json ... ``` or ``` ... ```, extract the inside.
    """
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else text


def _json_repair_ish(s: str) -> str:
    """
    Apply minimal safe-ish transformations to make malformed JSON parseable:
    - Replace single quotes with double quotes when they look like JSON keys/strings
    - Convert Python booleans/None to JSON booleans/null
    - Remove trailing commas before } or ]
    """
    # Fix keys: {'key': ...} -> {"key": ...}
    s = re.sub(r"(?P<pre>[{,\s])'(?P<key>[^']+?)'\s*:", r'\g<pre>"\g<key>":', s)
    # Fix values: : 'val' -> : "val"
    s = re.sub(r':\s*\'(?P<val>[^\'\\]*?)\'\s*(?P<post>[,}\]])', r': "\g<val>"\g<post>', s)

    # Python -> JSON compatibility
    s = s.replace(": True", ": true").replace(": False", ": false").replace(": None", ": null")
    s = s.replace(":  True", ": true").replace(":  False", ": false").replace(":  None", ": null")

    # Remove dangling commas
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


def _parse_verifier_json(raw: str) -> dict:
    """
    Robust JSON parsing strategy:
