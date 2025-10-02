# workflow.py
import logging
from langgraph.graph import StateGraph, END
from state import AppState

from agents.coordinator import coordinator_node, route_from_coordinator
from agents.retriever import retriever_node
from agents.writer import writer_node
from agents.verifier import verifier_node

logger = logging.getLogger(__name__)

def build_graph():
    graph = StateGraph(AppState)
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("writer", writer_node)
    graph.add_node("verifier", verifier_node)

    graph.set_entry_point("coordinator")
    graph.add_conditional_edges(
        "coordinator",
        route_from_coordinator,
        {
            "retriever": "retriever",
            "writer": "writer",
            "verifier": "verifier",
            "__end__": END,
        },
    )
    graph.add_edge("retriever", "coordinator")
    graph.add_edge("writer", "coordinator")
    graph.add_edge("verifier", "coordinator")
    return graph.compile()

def prepare_initial_state(query: str) -> AppState:
    return {"query": query.strip(), "messages": [], "attempts": 0, "max_attempts": 3}