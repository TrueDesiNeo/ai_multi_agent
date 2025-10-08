import os, uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from reviewer import ReviewerExecutor

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10001"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}/")

skill = AgentSkill(
    id="verify_answer",
    name="Verify tone/policy",
    description="Rate answer 1–10 and provide feedback + flags.",
    tags=["verify", "policy", "tone"],
)

card = AgentCard(
    name="Verifier Agent",
    description="Rates answers and provides feedback.",
    url=BASE_URL, version="1.0.0",
    default_input_modes=["text"], default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[skill],
)

app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(agent_executor=ReviewerExecutor(), task_store=InMemoryTaskStore()),
)

if __name__ == "__main__":
    uvicorn.run(app.build(), host=HOST, port=PORT)