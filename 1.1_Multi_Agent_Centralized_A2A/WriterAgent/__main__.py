import os, uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from writer import WriterExecutor

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10001"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}/")

skill = AgentSkill(
    id="write_answer",
    name="Draft a concise answer",
    description="Compose a concise, cited answer from contexts + optional feedback.",
    tags=["compose", "summarize"],
    examples=["Create a concise answer about RAG evaluation."],
)

card = AgentCard(
    name="Writer Agent",
    description="Drafts concise answers with citations.",
    url=BASE_URL, 
    version="1.0.0",
    default_input_modes=["text"], 
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[skill],
)

app = A2AStarletteApplication(
    agent_card=card,
    http_handler=DefaultRequestHandler(agent_executor=WriterExecutor(), task_store=InMemoryTaskStore()),
)

if __name__ == "__main__":
    uvicorn.run(app.build(), host=HOST, port=PORT)