from dataclasses import dataclass
import os
from dotenv import load_dotenv
import logging

# -----------------------------
# Setup Logging Configuration
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv(override=True)

@dataclass(frozen=True)
class Settings:
    """
    Application configuration loaded from environment variables.
    """
    
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    writer_model_name: str = os.getenv("WRITER_MODEL_NAME", "MY_WRITER_MODEL")
    reviewer_model_name: str = os.getenv("REVIEWER_MODEL_NAME", "MY_REVIEWER_MODEL")
    model_url: str = os.getenv("MODEL_URL", "API_URL")
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY")
    tavily_api_url: str | None = os.getenv("TAVILY_API_URL")    
    retriever_top_k: int = int(os.getenv("RETRIEVER_TOP_K", "5"))
    max_rewrite_attempts: int = int(os.getenv("MAX_REWRITE_ATTEMPTS", "3"))

# -----------------------------
# Instantiate and Log Settings
# -----------------------------
settings = Settings()

logger.info(
    "Loaded settings from environment variables:\n"
    f"OPENAI_API_KEY: {settings.openai_api_key}\n"
    f"WRITET_MODEL_NAME: {settings.writer_model_name}\n"
    f"REVIEWER_MODEL_NAME: {settings.reviewer_model_name}\n"
    f"MODEL_URL: {settings.model_url}\n"
    f"TAVILY_API_KEY: {settings.tavily_api_key}\n"
    f"TAVILY_API_URL: {settings.tavily_api_url}\n"
    f"RETRIEVER_TOP_K: {settings.retriever_top_k}\n"
    f"MAX_REWRITE_ATTEMPTS: {settings.max_rewrite_attempts}"
)