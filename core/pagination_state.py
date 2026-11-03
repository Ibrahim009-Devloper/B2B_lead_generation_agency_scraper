import os
import json
import logging
import threading
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("PaginationState")
logger.setLevel(logging.INFO)

STATE_FILE = Path("scraped_pages.json")
FALLBACK_STATE_FILE = Path("crawl_state.json")

class DirectoryPaginationManager:
    """
    Persistent Directory Pagination Tracker (scraped_pages.json).
    
    Guarantees:
    - Maintains exact page cursors across scraping runs (GoodFirms, Clutch, Sortlist, DesignRush).
    - Prevents re-scraping previously harvested directory pages.
    - Uses thread-safe atomic file replacement to prevent JSON corruption during container termination.
    """

    def __init__(self, filepath: Path = STATE_FILE):
        self.filepath = filepath
        self._lock = threading.Lock()
        self._state: Dict[str, int] = {}
        self._load()

    def _load(self):
        with self._lock:
            # First try scraped_pages.json, then fallback to crawl_state.json
            for p in (self.filepath, FALLBACK_STATE_FILE):
                if p.exists():
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, dict):
                                self._state.update(data)
                                break
                    except Exception as e:
                        logger.warning(f"Notice reading pagination file {p}: {e}")

    def get_page(self, directory_key: str, default: int = 1) -> int:
        """Retrieves the next page index to scrape for a given directory/category."""
        with self._lock:
            return self._state.get(directory_key, default)

    def set_page(self, directory_key: str, page: int):
        """Updates and persists the next page index for a given directory/category."""
        with self._lock:
            self._state[directory_key] = page
            self._persist_atomic()

    def advance_page(self, directory_key: str, pages_scraped: int = 1) -> int:
        """Increments page counter after a successful directory page scrape."""
        with self._lock:
            curr = self._state.get(directory_key, 1)
            next_page = curr + pages_scraped
            self._state[directory_key] = next_page
            self._persist_atomic()
            return next_page

    def get_all_state(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._state)

    def _persist_atomic(self):
        """Writes to a temporary file first, then atomically renames to target file."""
        tmp_file = self.filepath.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            # Atomic rename (safe on POSIX and modern Windows)
            tmp_file.replace(self.filepath)
            
            # Sync to crawl_state.json for backwards compatibility
            if self.filepath != FALLBACK_STATE_FILE:
                try:
                    tmp_fallback = FALLBACK_STATE_FILE.with_suffix(".tmp")
                    with open(tmp_fallback, "w", encoding="utf-8") as f:
                        json.dump(self._state, f, indent=2)
                    tmp_fallback.replace(FALLBACK_STATE_FILE)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to persist directory pagination state: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

# Global singleton
pagination_manager = DirectoryPaginationManager()

