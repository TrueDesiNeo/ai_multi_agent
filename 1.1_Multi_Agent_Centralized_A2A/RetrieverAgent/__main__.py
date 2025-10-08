import os, uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from retriever import RetrieverExecutor
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10001"))
BASE_URL = f"http://{HOST}:{PORT}/"
PUBLIC_BASEURL = os.getenv("PUBLIC_BASE_URL", f"http://localhost:{PORT}/")

def main():
    skill = AgentSkill(
        id="search_web",
        name="Web Search (Tavily)",
        description="Search the web and return top results.",
        tags=["search", "tavily"],
        examples=["Find latest on RAG evaluation"],
    )

    card = AgentCard(
        name="Retriever Agent",
        description="Performs web search via Tavily.",
        url=PUBLIC_BASEURL,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(),
        skills=[skill],
    )

    app = A2AStarletteApplication(
        agent_card=card,
        http_handler=DefaultRequestHandler(agent_executor=RetrieverExecutor(), task_store=InMemoryTaskStore()),
    )

    uvicorn.run(app.build(), host=HOST, port=PORT)

if __name__ == "__main__":
    main()