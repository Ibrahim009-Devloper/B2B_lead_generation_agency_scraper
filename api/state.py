import logging
import threading
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import setup_logging, SCRAPER_LOG_PATH, ERRORS_LOG_PATH, UI_LOG_BUFFER
from core.orchestrator import master_orchestrator
from core.memory_guard import get_memory_stats, force_garbage_collection

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

def _restore_last_state_from_db():
    """Restores last completed/active campaign ID from persistent SQLite so data survives container restarts."""
    try:
        from core.database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT campaign_id FROM leads WHERE campaign_id IS NOT NULL AND campaign_id != '' ORDER BY collected_at DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            SCRAPING_STATE["last_campaign_id"] = row[0]
            logging.getLogger("State").info(f"Restored last campaign ID from SQLite database: {row[0]}")
    except Exception as e:
        logging.getLogger("State").debug(f"Could not restore last campaign ID: {e}")

_restore_last_state_from_db()

def log_agent_activity(agent: str, message: str, level: str = "INFO"):
    """Logs activity to live UI buffer and rotating log files."""
    now_str = datetime.now().strftime("%H:%M:%S")
    SCRAPING_STATE["current_agent"] = agent
    SCRAPING_STATE["last_event_time"] = now_str
    
    # Broadcast to Python logger so it lands in scraper.log and errors.log
    mod_logger = logging.getLogger(agent)
    log_func = getattr(mod_logger, level.lower(), mod_logger.info)
    log_func(message)

def _dispatch_webhook(webhook_url: str, campaign_result: Dict[str, Any]):
    """Automatically sends full leads payload to MUSE AI webhook URL upon campaign completion."""
    import httpx
    from api.exporter import lead_exporter
    try:
        leads_list = campaign_result.get("leads", [])
        formatted = []
        for l in leads_list:
            row = lead_exporter._lead_to_row(l)
            row["lead_id"] = str(l.lead_id)
            formatted.append(row)
            
        payload = {
            "event": "campaign.completed",
            "campaign_id": campaign_result.get("campaign_id"),
            "status": "completed",
            "total_qualified_leads": len(formatted),
            "leads": formatted,
            "metrics": campaign_result.get("metrics", {})
        }
        headers = {"Content-Type": "application/json", "User-Agent": "LeadGen-Webhook-Dispatcher/2.0"}
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(webhook_url, json=payload, headers=headers)
            log_agent_activity("Webhook Dispatcher", f"Delivered {len(formatted)} leads to MUSE AI webhook: {webhook_url} (HTTP {resp.status_code})")
    except Exception as e:
        log_agent_activity("Webhook Dispatcher", f"Failed to dispatch webhook to {webhook_url}: {e}", level="ERROR")

def _background_scraper_worker(prompt: str, target: int, webhook_url: Optional[str] = None):
    SCRAPING_STATE["is_running"] = True
    SCRAPING_STATE["prompt"] = prompt
    SCRAPING_STATE["target_count"] = target
    SCRAPING_STATE["last_campaign_leads"] = []
    log_agent_activity("Master Orchestrator", f"Started scraping swarm targeting {target} hot leads for: '{prompt}'")
    try:
        result = master_orchestrator.run_campaign(prompt, target_count=target, on_event=log_agent_activity)
        SCRAPING_STATE["last_campaign_id"] = result["campaign_id"]
        SCRAPING_STATE["last_campaign_leads"] = result["leads"]
        # Keep bounded to prevent keeping hundreds of heavy LeadRecord objects in global state
        SCRAPING_STATE["last_campaign_all_records"] = (result.get("all_records") or result.get("leads") or [])[:30]
        SCRAPING_STATE["last_campaign_total_discovered"] = result.get("total_discovered", len(result["leads"]))
        log_agent_activity("Master Orchestrator", f"Scraping campaign finished: {len(result['leads'])} verified leads with emails collected.")
        
        # Zero-Token Muse AI Webhook Callback Delivery
        if webhook_url:
            log_agent_activity("Webhook Dispatcher", f"Dispatching completed leads to callback URL: {webhook_url}")
            _dispatch_webhook(webhook_url, result)
    except Exception as e:
        err_trace = traceback.format_exc()
        log_agent_activity("Master Orchestrator", f"Campaign encountered error: {e}", level="ERROR")
        logging.getLogger("MasterOrchestrator").error(f"Full traceback:\n{err_trace}")
    finally:
        SCRAPING_STATE["is_running"] = False
        SCRAPING_STATE["current_agent"] = "Idle"
        force_garbage_collection()

def start_background_campaign(prompt: str, target_count: int = 25, webhook_url: Optional[str] = None) -> Dict[str, Any]:
    """Launches an asynchronous scraping campaign thread with optional webhook notification."""
    if SCRAPING_STATE["is_running"]:
        return {
            "status": "already_running",
            "message": "Scraper is currently running a campaign.",
            "prompt": SCRAPING_STATE["prompt"],
            "target_count": SCRAPING_STATE["target_count"]
        }
    
    t = threading.Thread(target=_background_scraper_worker, args=(prompt, target_count, webhook_url), daemon=True)
    t.start()
    
    # Trigger an immediate anti-sleep heartbeat ping so Render's idle counter is reset right away
    try:
        from core.keep_alive import keep_alive_engine
        threading.Thread(target=keep_alive_engine.ping_now, daemon=True).start()
    except Exception:
        pass

    return {
        "status": "started",
        "message": f"Scraping swarm launched targeting {target_count} hot leads." + (f" Webhook will be called at {webhook_url} when done." if webhook_url else ""),
        "prompt": prompt,
        "target_count": target_count,
        "webhook_url": webhook_url
    }

def stop_background_campaign() -> Dict[str, Any]:
    """Signals orchestrator and running threads to halt immediately."""
    master_orchestrator.stop_campaign()
    SCRAPING_STATE["is_running"] = False
    SCRAPING_STATE["current_agent"] = "Stopped"
    log_agent_activity("Master Orchestrator", "Scraper stopped by user or remote AI agent.")
    return {"status": "stopped", "message": "Scraper campaign successfully stopped."}

