# state.py
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

class AppState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    query: str
    search_snippets: str
    draft: str
    verification: dict  # {'rating': int, 'safe': bool, 'feedback': str}
    attempts: int
    max_attempts: int