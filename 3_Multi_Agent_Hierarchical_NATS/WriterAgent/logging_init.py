# =============================================================================
# File: logging_init.py
# Description:
#     Environment variable utilities and centralized logging configuration
#     for the Chief Editor AI system. Supports parsing of boolean and float
#     values from environment, and sets up UTC-based structured logging.
#
# Key Features:
#     - `_env`: safely fetches environment variables with defaults
#     - `_parse_bool`: interprets common truthy strings
#     - `_parse_float`: parses float values with fallback
#     - `logger`: preconfigured logger with UTC timestamps and structured format
#
# Usage:
#     from logging_init import _env, _parse_bool, _parse_float, logger
#
# Environment Variables:
#     - LOG_LEVEL: sets logging verbosity (default: INFO)
#
# Dependencies:
#     - Python 3.10+
#     - python-dotenv
#     - logging
#
# =============================================================================

from dotenv import load_dotenv
import os
from typing import Optional
import logging

# -----------------------------------------------------------------------------
# Environment & Logging
# -----------------------------------------------------------------------------
load_dotenv()

def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _parse_float(value: Optional[str], default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)

# -----------------------------------------------------------------------------
# Logger Configuration
# -----------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s.%(msecs)03dZ | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Configure logging (UTC timestamps)
logLevel = _env("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=logLevel,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    force=True,  # ensure this overrides any prior handlers (Python 3.8+)
)
logger = logging.getLogger("Writer")