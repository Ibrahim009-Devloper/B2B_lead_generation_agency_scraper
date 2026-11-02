import logging
import threading
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import setup_logging, SCRAPER_LOG_PATH, ERRORS_LOG_PATH, UI_LOG_BUFFER
from core.orchestrator import master_orchestrator

# Global Real-Time Scraping State
SCRAPING_STATE: Dict[str, Any] = {
    "is_running": False,
    "current_agent": "Idle",
    "prompt": "",
    "target_count": 25,
    "last_campaign_id": None,
    "last_campaign_leads": [],
    "last_campaign_all_records": [],
    "last_campaign_total_discovered": 0,
    "last_event_time": "",
    "logs": UI_LOG_BUFFER
}

def log_agent_activity(agent: str, message: str, level: str = "INFO"):
    """Logs activity to live UI buffer and rotating log files."""
    now_str = datetime.now().strftime("%H:%M:%S")
    SCRAPING_STATE["current_agent"] = agent
    SCRAPING_STATE["last_event_time"] = now_str
    
    # Broadcast to Python logger so it lands in scraper.log and errors.log
    mod_logger = logging.getLogger(agent)
    log_func = getattr(mod_logger, level.lower(), mod_logger.info)
    log_func(message)

def _background_scraper_worker(prompt: str, target: int):
    SCRAPING_STATE["is_running"] = True
    SCRAPING_STATE["prompt"] = prompt
    SCRAPING_STATE["target_count"] = target
    SCRAPING_STATE["last_campaign_leads"] = []
    log_agent_activity("Master Orchestrator", f"Started scraping swarm targeting {target} hot leads for: '{prompt}'")
    try:
        result = master_orchestrator.run_campaign(prompt, target_count=target, on_event=log_agent_activity)
        SCRAPING_STATE["last_campaign_id"] = result["campaign_id"]
        SCRAPING_STATE["last_campaign_leads"] = result["leads"]
        SCRAPING_STATE["last_campaign_all_records"] = result.get("all_records", result["leads"])
        SCRAPING_STATE["last_campaign_total_discovered"] = result.get("total_discovered", len(result["leads"]))
        log_agent_activity("Master Orchestrator", f"Scraping campaign finished: {len(result['leads'])} verified leads with emails collected.")
    except Exception as e:
        err_trace = traceback.format_exc()
        log_agent_activity("Master Orchestrator", f"Campaign encountered error: {e}", level="ERROR")
        logging.getLogger("MasterOrchestrator").error(f"Full traceback:\n{err_trace}")
    finally:
        SCRAPING_STATE["is_running"] = False
        SCRAPING_STATE["current_agent"] = "Idle"

def start_background_campaign(prompt: str, target_count: int = 25) -> Dict[str, Any]:
    """Launches an asynchronous scraping campaign thread."""
    if SCRAPING_STATE["is_running"]:
        return {
            "status": "already_running",
            "message": "Scraper is currently running a campaign.",
            "prompt": SCRAPING_STATE["prompt"],
            "target_count": SCRAPING_STATE["target_count"]
        }
    
    t = threading.Thread(target=_background_scraper_worker, args=(prompt, target_count), daemon=True)
    t.start()
    return {
        "status": "started",
        "message": f"Scraping swarm launched targeting {target_count} hot leads.",
        "prompt": prompt,
        "target_count": target_count
    }

def stop_background_campaign() -> Dict[str, Any]:
    """Signals orchestrator and running threads to halt immediately."""
    master_orchestrator.stop_campaign()
    SCRAPING_STATE["is_running"] = False
    SCRAPING_STATE["current_agent"] = "Stopped"
    log_agent_activity("Master Orchestrator", "Scraper stopped by user or remote AI agent.")
    return {"status": "stopped", "message": "Scraper campaign successfully stopped."}

