import uuid
import json
import os
import logging
import httpx
import argparse
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    TextPart
)
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
logger = logging.getLogger("coordinator_client")

CARD_PATH = os.getenv("PUBLIC_AGENT_CARD_PATH", "/.well-known/agent.json")
CORRD_BASE_URL = os.getenv("COORDINATOR_URL", "http://localhost:10000")


def _extract_text_part(a2a_response) -> str:
    """Extracts the text content from the A2A response object."""
    d = a2a_response.model_dump()
    parts = d.get("result", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise RuntimeError("Unexpected response format: missing 'text' in parts")
    return parts[0]["text"]


# -----------------------------------------------------------------------------
# Main async function
# -----------------------------------------------------------------------------
async def main(question: str, max_results: int, max_retries: int) -> None:
    request_id = str(uuid.uuid4())

    async with httpx.AsyncClient(verify=False, timeout=60.0) as httpx_client:
        logger.info(f"[{request_id}] Fetching agent card from {CORRD_BASE_URL}{CARD_PATH}")

        # Resolve agent card
        try:
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=CORRD_BASE_URL)
            agent_card: AgentCard = await resolver.get_agent_card()
            logger.info(f"[{request_id}] Agent card fetched successfully")
        except Exception as e:
            logger.exception(f"[{request_id}] Failed to fetch agent card")
            raise RuntimeError("Failed to fetch public agent card") from e

        # Initialize A2A client
        client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
        logger.info(f"[{request_id}] A2AClient initialized")

        # Build payload
        payload = {
            "request_id": request_id,
            "question": question,
            "max_results": max_results,
            "max_retries": max_retries,
        }

        # Create message
        message_payload = Message(
            role=Role.user,
            message_id=str(uuid.uuid4()),
            parts=[Part(root=TextPart(text=json.dumps(payload, ensure_ascii=False)))],
        )
        request = SendMessageRequest(
            id=str(uuid.uuid4()),
            params=MessageSendParams(message=message_payload),
        )

        # Send message
        logger.info(f"[{request_id}] Sending message to Coordinator agent")
        try:
            response = await client.send_message(request)
            logger.info(f"[{request_id}] Response received from Coordinator agent")
            logger.debug(f"[{request_id}] Full response:\n{response.model_dump_json(indent=2)}")
        except Exception as e:
            logger.exception(f"[{request_id}] Failed to send message or receive response")
            raise

        # Extract contexts
        try:
            response_text = _extract_text_part(response)
            response_data = json.loads(response_text)
            final_answer = response_data.get("final_answer", [])
        except Exception as e:
            print(f"Error parsing retriever response: {e}")
            raise RuntimeError("Failed to extract contexts from retriever response")

        # Print final output
        print("\n================ FINAL RESPONSE ================")
        print(final_answer)
        print("===============================================")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    parser = argparse.ArgumentParser(description="Send question to Coordinator agent via A2AClient")
    
    parser.add_argument(
        "--question",
        type=str,
        default="What is impact of sports in growth of kids?",
        help="Question to send to the Coordinator agent"
    )
    parser.add_argument(
        "--max_results",
        type=int,
        default=5,
        help="Maximum number of results to request (default: 5)"
    )
    parser.add_argument(
        "--max_retries",
        type=int,
        default=3,
        help="Maximum number of retries allowed (default: 3)"
    )

    args = parser.parse_args()

    asyncio.run(main(args.question, args.max_results, args.max_retries))
