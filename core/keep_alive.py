import os
import time
import logging
import threading
from typing import Optional, List, Dict, Any
from curl_cffi import requests

logger = logging.getLogger("KeepAliveEngine")

class KeepAliveEngine:
    """
    Autonomous Anti-Sleep Heartbeat Daemon.
    Engineered to prevent Render Free Tier from spinning down (sleeping) during active scraping campaigns.
    
    Render Free Tier spins down containers after 15 minutes of zero inbound HTTP traffic.
    This daemon pings the server's public endpoint every 4 minutes during an active campaign
    (and every 10 minutes when idle) to guarantee the container never sleeps mid-harvest.
    """
    def __init__(self):
        # Auto-detect Render external URL from environment variables
        self._public_url: Optional[str] = (
            os.getenv("RENDER_EXTERNAL_URL")
            or os.getenv("PUBLIC_URL")
            or os.getenv("SELF_URL")
        )
        if self._public_url:
            self._public_url = self._public_url.rstrip("/")

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.active_interval_seconds: int = int(os.getenv("KEEP_ALIVE_ACTIVE_INTERVAL", "240"))  # 4 mins during campaign
        self.idle_interval_seconds: int = int(os.getenv("KEEP_ALIVE_IDLE_INTERVAL", "600"))      # 10 mins when idle
        self.port: int = int(os.getenv("PORT", "8000"))
        self._last_ping_time: Optional[float] = None
        self._last_ping_status: Optional[str] = None
        self._ping_count: int = 0

    def set_public_url(self, url: str):
        """Dynamically captures and updates the public URL from incoming requests (e.g. from Render edge proxy)."""
        if not url:
            return
        cleaned = url.strip().rstrip("/")
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            # Don't overwrite public URL with localhost or 127.0.0.1
            if "localhost" not in cleaned and "127.0.0.1" not in cleaned:
                if self._public_url != cleaned:
                    self._public_url = cleaned
                    logger.info(f"[KeepAlive] Registered public server URL: {self._public_url}")

    def get_public_url(self) -> Optional[str]:
        return self._public_url

    def _get_target_urls(self) -> List[str]:
        targets = []
        if self._public_url:
            # Pinging the public URL routes through Render's reverse proxy, resetting the 15-minute idle counter
            targets.append(f"{self._public_url}/api/v1/muse/campaigns/status")
            targets.append(f"{self._public_url}/api/status")
        # Localhost fallback if port is accessible
        targets.append(f"http://127.0.0.1:{self.port}/api/status")
        return targets

    def ping_now(self) -> bool:
        """Sends an immediate keep-alive heartbeat ping."""
        targets = self._get_target_urls()
        headers = {
            "User-Agent": "LeadGen-AntiSleep-Heartbeat/2.0 (Anti-Sleep Protection)",
            "Accept": "application/json"
        }
        success = False
        for url in targets:
            try:
                resp = requests.get(url, headers=headers, timeout=12.0, impersonate="safari15_5")
                if resp.status_code in (200, 204):
                    self._last_ping_time = time.time()
                    self._last_ping_status = f"HTTP {resp.status_code} ({url})"
                    self._ping_count += 1
                    logger.info(f"[KeepAlive] Ping #{self._ping_count} succeeded: {url} (HTTP {resp.status_code}). Render sleep prevented.")
                    success = True
                    break
            except Exception as e:
                logger.debug(f"[KeepAlive] Ping attempt to {url} notice: {e}")
                continue
        return success

    def _loop(self):
        logger.info("[KeepAlive] Daemon heartbeat loop started.")
        # Initial 10-second grace delay to let FastAPI finish binding
        time.sleep(10)

        while not self._stop_event.is_set():
            try:
                from api.state import SCRAPING_STATE
                is_running = SCRAPING_STATE.get("is_running", False)

                # Active campaign: ping every 4 mins (240s) to easily beat Render's 15-min idle spin-down
                # Idle: ping every 10 mins (600s) to keep container responsive
                interval = self.active_interval_seconds if is_running else self.idle_interval_seconds

                self.ping_now()

                # Sleep in small increments for graceful termination
                elapsed = 0
                while elapsed < interval and not self._stop_event.is_set():
                    time.sleep(5)
                    elapsed += 5
            except Exception as e:
                logger.debug(f"[KeepAlive] Loop exception: {e}")
                time.sleep(10)

    def start(self):
        """Starts the background keep-alive daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="KeepAliveDaemon", daemon=True)
        self._thread.start()
        logger.info(f"[KeepAlive] Heartbeat daemon active (campaign interval: {self.active_interval_seconds}s, idle interval: {self.idle_interval_seconds}s).")

    def stop(self):
        """Stops the daemon gracefully."""
        self._stop_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Returns the current heartbeat telemetry."""
        is_active = self._thread is not None and self._thread.is_alive()
        now_str = None
        if self._last_ping_time:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._last_ping_time))
        return {
            "daemon_running": is_active,
            "public_url": self._public_url or "Auto-detecting on first incoming request",
            "last_ping_time": now_str,
            "last_ping_status": self._last_ping_status,
            "total_pings_sent": self._ping_count,
            "campaign_interval_seconds": self.active_interval_seconds,
            "idle_interval_seconds": self.idle_interval_seconds,
            "anti_sleep_active": True
        }

keep_alive_engine = KeepAliveEngine()

