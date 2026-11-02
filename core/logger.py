import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SCRAPER_LOG_PATH = LOGS_DIR / "scraper.log"
ERRORS_LOG_PATH = LOGS_DIR / "errors.log"

# In-memory buffer for real-time UI streaming
MAX_MEMORY_LOGS = 250
UI_LOG_BUFFER: List[Dict[str, Any]] = []

class UIStreamHandler(logging.Handler):
    """Broadcasts Python logging records directly into UI_LOG_BUFFER for dashboard streaming."""
    def emit(self, record):
        try:
            msg = self.format(record)
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "agent": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
                "formatted": msg
            }
            UI_LOG_BUFFER.insert(0, entry)
            if len(UI_LOG_BUFFER) > MAX_MEMORY_LOGS:
                UI_LOG_BUFFER.pop()
        except Exception:
            self.handleError(record)

_LOGGING_INITIALIZED = False

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configures centralized logging to console, scraper.log, and errors.log."""
    global _LOGGING_INITIALIZED
    root_logger = logging.getLogger()
    if _LOGGING_INITIALIZED or any(isinstance(h, (RotatingFileHandler, UIStreamHandler)) for h in root_logger.handlers):
        return root_logger

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Console Stream Handler (clean terminal output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. Complete Scraper Log File (Max 10MB, up to 3 backups)
    file_handler = RotatingFileHandler(
        SCRAPER_LOG_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 3. Dedicated Error Log File (Max 5MB, WARNING and ERROR only)
    error_handler = RotatingFileHandler(
        ERRORS_LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 4. Real-time UI Handler
    ui_handler = UIStreamHandler()
    ui_handler.setLevel(logging.INFO)
    ui_handler.setFormatter(formatter)
    root_logger.addHandler(ui_handler)

    # Silence noisy 3rd-party library internal logs so UI stays clean and focused on agents
    for noisy in ["primp", "httpx", "httpcore", "urllib3", "curl_cffi", "asyncio", "charset_normalizer", "ddgs", "ddgs.ddgs"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

    _LOGGING_INITIALIZED = True
    root_logger.info("Centralized logging system initialized. Writing to logs/scraper.log and logs/errors.log")
    return root_logger

# Initialize immediately on module import
app_logger = setup_logging()

