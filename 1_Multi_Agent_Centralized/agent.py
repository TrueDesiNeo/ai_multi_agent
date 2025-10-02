from langchain_openai import ChatOpenAI
from config import settings
from typing import Any, Optional

def get_chat_openai(
    temperature: float,
    model_name: str,
    model_kwargs_dict: Optional[dict[str, Any]] = None
) -> ChatOpenAI:
    """
    Returns a ChatOpenAI instance with the specified temperature.

    Args:
        temperature (float): The temperature setting for the model.
        model_name (str): The name of the model to use.
        model_kwargs_dict (Optional[dict[str, Any]]): Optional keyword arguments for the model.

    Returns:
        ChatOpenAI: Configured ChatOpenAI object.
    """
    if model_kwargs_dict:
        return ChatOpenAI(
            base_url=settings.model_url,
            model=model_name,
            temperature=temperature,
            model_kwargs=model_kwargs_dict,
        )
    else:
        return ChatOpenAI(
            base_url=settings.model_url,
            model=model_name,
            temperature=temperature,
        )