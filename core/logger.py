import os
import sys
import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SCRAPER_LOG_PATH = LOGS_DIR / "scraper.log"
ERRORS_LOG_PATH = LOGS_DIR / "errors.log"

# Minimal transient in-memory ring-buffer (max 50 lines) to prevent memory leakage
MAX_MEMORY_LOGS = 50
UI_LOG_BUFFER: deque = deque(maxlen=MAX_MEMORY_LOGS)

class UIStreamHandler(logging.Handler):
    """Broadcasts Python logging records into lightweight deque buffer for dashboard streaming."""
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
            UI_LOG_BUFFER.append(entry)
        except Exception:
            self.handleError(record)

_LOGGING_INITIALIZED = False

def clear_all_logs():
    """Wipes in-memory log buffer and truncates disk log files to zero bytes."""
    UI_LOG_BUFFER.clear()
    for p in (SCRAPER_LOG_PATH, ERRORS_LOG_PATH):
        try:
            if p.exists():
                with open(p, "w", encoding="utf-8") as f:
                    f.truncate(0)
        except Exception:
            pass

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configures centralized logging to console and ultra-compact rotating files."""
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

    # 1. Console Stream Handler (captured by Render Web UI stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. Compact Scraper Log File (Max 1MB, 1 backup only)
    file_handler = RotatingFileHandler(
        SCRAPER_LOG_PATH,
        maxBytes=1 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 3. Compact Error Log File (Max 500KB)
    error_handler = RotatingFileHandler(
        ERRORS_LOG_PATH,
        maxBytes=500 * 1024,
        backupCount=1,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # 4. Lightweight UI Handler
    ui_handler = UIStreamHandler()
    ui_handler.setLevel(logging.INFO)
    ui_handler.setFormatter(formatter)
    root_logger.addHandler(ui_handler)

    # Silence noisy 3rd-party library internal logs
    for noisy in ["primp", "httpx", "httpcore", "urllib3", "curl_cffi", "asyncio", "charset_normalizer", "ddgs", "ddgs.ddgs"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

    _LOGGING_INITIALIZED = True
    root_logger.info("Stateless logging system initialized (bounded 50-line memory ring-buffer).")
    return root_logger

# Initialize immediately on module import
app_logger = setup_logging()
