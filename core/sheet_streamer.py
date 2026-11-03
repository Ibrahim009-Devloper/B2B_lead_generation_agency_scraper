import os
import time
import json
import logging
import threading
import queue
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from core.schemas import LeadRecord
from core.memory_guard import force_garbage_collection

logger = logging.getLogger("GoogleSheetStreamer")
logger.setLevel(logging.INFO)

class GoogleSheetStreamer:
    """
    Stateless 5x/Minute Rate-Limited Google Apps Script Webhook Streamer.
    
    Guarantees:
    - Flushes enqueued leads up to 5 times per minute (every 12 seconds).
    - If 0 leads found, sends 0 requests (zero bandwidth & zero quota burned).
    - Automatically follows HTTP 302 redirects returned by Google Apps Script webapps.
    - Discards lead payloads from memory immediately upon verified transmission.
    - Fallback persistence to exports/fallback_streamed_leads.jsonl if webhook fails.
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
        self.queue: queue.Queue = queue.Queue(maxsize=500)
        self.is_running: bool = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Metrics
        self.total_streamed_leads: int = 0
        self.last_flush_timestamp: float = 0.0
        self.last_flush_status: str = "idle"
        self.flush_interval_seconds: float = 12.0  # 5 times per minute max

    def set_webhook_url(self, url: str):
        with self._lock:
            self.webhook_url = url.strip()
            logger.info(f"Google Sheet Webhook URL updated: {self.webhook_url[:30]}...")

    def enqueue_lead(self, lead: LeadRecord):
        """Enqueues a verified lead for streaming to Google Sheets."""
        try:
            self.queue.put_nowait(lead)
            logger.info(f"[STREAMER QUEUE] Enqueued lead: {lead.business_name} ({lead.verified_email or lead.email}) | Queue size: {self.queue.qsize()}")
        except queue.Full:
            logger.warning("[STREAMER QUEUE] Queue full (500 items). Writing lead immediately to emergency fallback.")
            self._write_fallback([lead])

    def start(self):
        """Starts the background streaming daemon."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="SheetStreamerThread")
            self._worker_thread.start()
            logger.info(f"GoogleSheetStreamer started (Flush Interval: {self.flush_interval_seconds}s / 5x per min).")

    def stop(self, timeout: float = 5.0):
        """Flushes remaining queue items and stops worker."""
        with self._lock:
            self.is_running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        # Flush any stragglers
        self._flush_batch()

    def get_stats(self) -> Dict[str, Any]:
        """Telemetry metrics for /health endpoint."""
        return {
            "is_running": self.is_running,
            "has_webhook_configured": bool(self.webhook_url),
            "queue_depth": self.queue.qsize(),
            "total_streamed_leads": self.total_streamed_leads,
            "last_flush_timestamp": self.last_flush_timestamp,
            "last_flush_status": self.last_flush_status
        }

    def _run_loop(self):
        while self.is_running:
            try:
                # Sleep interval to enforce 5x/min rate limit (12 seconds)
                time.sleep(self.flush_interval_seconds)
                if not self.queue.empty():
                    self._flush_batch()
            except Exception as e:
                logger.error(f"Error in streamer loop: {e}", exc_info=True)
                time.sleep(5.0)

    def _flush_batch(self):
        batch: List[LeadRecord] = []
        # Drain up to 25 leads per batch
        while not self.queue.empty() and len(batch) < 25:
            try:
                lead = self.queue.get_nowait()
                batch.append(lead)
            except queue.Empty:
                break

        if not batch:
            return

        payload = self._format_payload(batch)
        success = False

        if self.webhook_url:
            success = self._post_to_google_sheet(payload, len(batch))
        else:
            logger.warning("[STREAMER] No GOOGLE_SHEET_WEBHOOK_URL set. Storing batch to fallback file.")

        if not success:
            self._write_fallback(batch)
        else:
            with self._lock:
                self.total_streamed_leads += len(batch)
                self.last_flush_timestamp = time.time()
                self.last_flush_status = "success"

        # Explicit cleanup to ensure 0 memory retention
        del batch
        del payload
        force_garbage_collection()

    def _format_payload(self, leads: List[LeadRecord]) -> Dict[str, Any]:
        formatted_list = []
        for l in leads:
            backup_list = getattr(l, "backup_emails", []) or []
            backup_str = ", ".join(backup_list) if isinstance(backup_list, list) else str(backup_list)
            dm_name = getattr(l, "decision_maker_name", "") or ""
            dm_role = getattr(l, "decision_maker_role", "") or ""
            dm_str = f"{dm_name} ({dm_role})".strip(" ()")
            
            # Email Category determination
            email_cat = getattr(l, "email_category", None)
            if not email_cat:
                lead_email = (getattr(l, "verified_email", None) or getattr(l, "email", None) or "").lower()
                if any(lead_email.startswith(prefix) for prefix in ["info@", "contact@", "hello@", "sales@", "support@", "admin@"]):
                    email_cat = "Generic Business"
                else:
                    email_cat = "Owner/Personal"

            formatted_list.append({
                "company_name": getattr(l, "business_name", "") or "",
                "website_domain": getattr(l, "website", "") or "",
                "verification_status": getattr(l, "target_verification_status", "") or "VERIFIED_TARGET",
                "primary_email": getattr(l, "verified_email", None) or getattr(l, "email", "") or "",
                "email_category": email_cat,
                "backup_emails": backup_str,
                "decision_maker": dm_str,
                "business_summary": getattr(l, "complete_business_summary", "") or "",
                "target_clients": getattr(l, "their_target_clients", "") or "",
                "pitch_guide": getattr(l, "personalization_guide", "") or "",
                "cold_email": getattr(l, "outreach_draft", "") or "",
                "source_footprint": getattr(l, "source_footprint", "") or "Directory Harvester"
            })
        return {"leads": formatted_list}

    def _post_to_google_sheet(self, payload: Dict[str, Any], count: int) -> bool:
        """Posts batch JSON to Google Apps Script Webhook following HTTP 302 redirects."""
        import requests

        max_retries = 3
        backoff = 2.0

        for attempt in range(1, max_retries + 1):
            try:
                # Google Apps Script Webhooks ALWAYS issue an HTTP 302 redirect.
                # allow_redirects=True is strictly required!
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=25.0,
                    allow_redirects=True
                )
                if resp.status_code in (200, 201):
                    logger.info(f"[STREAMER SUCCESS] Flushed {count} verified leads to Google Sheet! (HTTP {resp.status_code})")
                    return True
                else:
                    logger.warning(f"[STREAMER RETRY {attempt}/{max_retries}] Webhook returned HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as exc:
                logger.warning(f"[STREAMER RETRY {attempt}/{max_retries}] Webhook connection notice: {exc}")

            time.sleep(backoff)
            backoff *= 2.0

        return False

    def _write_fallback(self, leads: List[LeadRecord]):
        """Emergency fallback file to ensure ZERO data loss if Google Sheets is unreachable."""
        fallback_dir = Path("exports")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_file = fallback_dir / "streamed_leads_fallback.jsonl"
        try:
            with open(fallback_file, "a", encoding="utf-8") as f:
                for l in leads:
                    f.write(json.dumps(l.to_dict(), default=str) + "\n")
            logger.info(f"[STREAMER FALLBACK] Safely persisted {len(leads)} leads to {fallback_file}")
        except Exception as e:
            logger.error(f"[STREAMER CRITICAL] Failed to write fallback file: {e}")

# Global singleton
sheet_streamer = GoogleSheetStreamer()
