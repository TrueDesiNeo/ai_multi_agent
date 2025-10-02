import logging
import sys

def setup_logging(level: int = logging.INFO) -> None:
    """
    Initialize structured logging for the application.
    """
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers in REPL/notebooks
    if not root.handlers:
        root.addHandler(handler)
    else:
        # Replace handlers in case of multiple initializations
        root.handlers = [handler]