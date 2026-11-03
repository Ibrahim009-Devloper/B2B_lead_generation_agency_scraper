import os
import time
import logging
import threading
from typing import List, Dict, Optional, Any
from pathlib import Path
from curl_cffi import requests

logger = logging.getLogger("ProxyRotator")

# Fallback default pool provided by user across multiple Webshare accounts
DEFAULT_PROXIES = [
    # Account 1 (Active)
    "45.38.107.97:6014:tlluyofr:je6skwlg7rke",
    "64.137.96.74:6641:tlluyofr:je6skwlg7rke",
    "198.23.243.226:6361:tlluyofr:je6skwlg7rke",
    "38.154.185.97:6370:tlluyofr:je6skwlg7rke",
    "84.247.60.125:6095:tlluyofr:je6skwlg7rke",
    "191.96.254.138:6185:tlluyofr:je6skwlg7rke",
    "198.46.161.42:5092:tlluyofr:je6skwlg7rke",
    "64.137.10.153:5803:tlluyofr:je6skwlg7rke",
    "104.164.49.38:7693:tlluyofr:je6skwlg7rke",
    "23.26.71.145:5628:tlluyofr:je6skwlg7rke",
    # Account 2 (Auto Bandwidth Backup & Overflow)
    "45.38.107.97:6014:lzmcudhj:6zomfebz4ox4",
    "64.137.96.74:6641:lzmcudhj:6zomfebz4ox4",
    "198.23.243.226:6361:lzmcudhj:6zomfebz4ox4",
    "38.154.185.97:6370:lzmcudhj:6zomfebz4ox4",
    "84.247.60.125:6095:lzmcudhj:6zomfebz4ox4",
    "191.96.254.138:6185:lzmcudhj:6zomfebz4ox4",
    "198.46.161.42:5092:lzmcudhj:6zomfebz4ox4",
    "64.137.10.153:5803:lzmcudhj:6zomfebz4ox4",
    "104.164.49.38:7693:lzmcudhj:6zomfebz4ox4",
    "23.26.71.145:5628:lzmcudhj:6zomfebz4ox4",
]

class ProxyRotator:
    """
    High-Performance Multi-Source Proxy Manager with:
    - Thread-safe Round-Robin rotation (every request gets a different IP)
    - Automatic Authentication (http://user:pass@ip:port)
    - Dynamic Block / Cooldown Detection (403, 429, timeouts)
    - Auto-Failover to the next healthy proxy
    - Support for Render environment variables (WEBSHARE_PROXIES) and local proxies.txt
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.index = 0
        self.proxies: List[str] = []
        self.cooldowns: Dict[str, float] = {}  # proxy_url -> cooldown_until_timestamp
        self.failure_counts: Dict[str, int] = {}
        self._load_proxies()

    def _format_proxy_url(self, raw: str) -> Optional[str]:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return None
        if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("socks5://"):
            return raw

        parts = raw.split(":")
        if len(parts) == 4:
            ip, port, user, pwd = parts
            return f"http://{user}:{pwd}@{ip}:{port}"
        elif len(parts) == 2:
            ip, port = parts
            return f"http://{ip}:{port}"
        return None

    def _load_proxies(self):
        loaded = []

        # 1. Check environment variable (Critical for Render deployment)
        env_proxies = os.environ.get("WEBSHARE_PROXIES", "").strip()
        if env_proxies:
            for item in env_proxies.replace(";", "\n").replace(",", "\n").splitlines():
                formatted = self._format_proxy_url(item)
                if formatted and formatted not in loaded:
                    loaded.append(formatted)

        # 2. Check local proxies.txt or config/proxies.txt
        for p in [Path("proxies.txt"), Path("config/proxies.txt")]:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            formatted = self._format_proxy_url(line)
                            if formatted and formatted not in loaded:
                                loaded.append(formatted)
                except Exception as e:
                    logger.debug(f"Error reading {p}: {e}")

        # 3. Fallback to hardcoded default pool
        if not loaded:
            for item in DEFAULT_PROXIES:
                formatted = self._format_proxy_url(item)
                if formatted and formatted not in loaded:
                    loaded.append(formatted)

        self.proxies = loaded
        logger.info(f"ProxyRotator initialized with {len(self.proxies)} authenticated rotating proxies.")

    def get_next_proxy(self) -> Optional[str]:
        """Returns the next authenticated proxy URL in round-robin order, or None if pool is exhausted/empty."""
        if not self.proxies:
            return None

        with self.lock:
            now = time.time()
            # Clean expired cooldowns
            self.cooldowns = {p: exp for p, exp in self.cooldowns.items() if exp > now}

            # Find next healthy proxy starting from current index
            total = len(self.proxies)
            for _ in range(total):
                proxy = self.proxies[self.index % total]
                self.index = (self.index + 1) % total
                if proxy not in self.cooldowns:
                    return proxy

            # If all configured proxies are dead or in cooldown, return None to trigger direct fallback!
            return None

    def get_proxies_dict(self) -> Optional[Dict[str, str]]:
        """Returns {'http': proxy_url, 'https': proxy_url} for requests / curl_cffi."""
        proxy_url = self.get_next_proxy()
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    def report_failure(self, proxy_url: Optional[str], status_code: Optional[int] = None, reason: str = ""):
        """Puts a blocked or failed proxy into a temporary cooldown if repeated or hard network error.
        If an account hits 402 Payment Required (Bandwidth Limit), cools down the entire account for 1 hour."""
        if not proxy_url:
            return
        with self.lock:
            count = self.failure_counts.get(proxy_url, 0) + 1
            self.failure_counts[proxy_url] = count

            # Bandwidth limit detection (HTTP 402 or 'response 402')
            is_bandwidth_exhausted = status_code == 402 or "402" in reason
            if is_bandwidth_exhausted:
                # If bandwidth is exhausted on this proxy's credentials, cool down for 1 hour
                self.cooldowns[proxy_url] = time.time() + 3600.0
                ip_masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
                logger.warning(
                    f"Proxy [{ip_masked}] bandwidth limit reached (HTTP 402). Auto-switching account (1-hr cooldown). "
                    f"Active healthy pool: {max(0, len(self.proxies) - len(self.cooldowns))}/{len(self.proxies)}"
                )
                return

            # Hard connection errors (curl error, timeout) cool down immediately for 45s
            # HTTP 403/429 only cool down if repeated
            is_network_err = status_code is None or status_code >= 500
            if is_network_err or count >= 2:
                self.cooldowns[proxy_url] = time.time() + 45.0
                ip_masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
                logger.warning(
                    f"Proxy [{ip_masked}] cooled down for 45s (status={status_code}, reason={reason}). "
                    f"Active healthy pool: {max(0, len(self.proxies) - len(self.cooldowns))}/{len(self.proxies)}"
                )

    def report_success(self, proxy_url: Optional[str]):
        if not proxy_url:
            return
        with self.lock:
            self.failure_counts.pop(proxy_url, None)

    def execute_request(self, url: str, method: str = "GET", retries: int = 3, **kwargs) -> Any:
        """
        Executes an HTTP request with automatic proxy rotation and failover.
        If proxies fail or expire (e.g. 402 Payment Required), automatically falls back to direct connection!
        """
        last_exception = None
        impersonate = kwargs.pop("impersonate", "safari15_5")
        timeout = kwargs.pop("timeout", 12.0)

        for attempt in range(retries):
            proxy_url = self.get_next_proxy()
            proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    impersonate=impersonate,
                    proxies=proxies,
                    timeout=timeout,
                    **kwargs
                )
                if proxy_url:
                    self.report_success(proxy_url)
                return resp
            except Exception as e:
                last_exception = e
                if proxy_url:
                    self.report_failure(proxy_url, reason=str(e)[:60])
                continue

        # Automatic Direct Fallback: If all proxy attempts failed, try direct connection
        try:
            logger.info(f"All proxies failed. Attempting direct fallback connection for: {url}")
            resp = requests.request(
                method=method,
                url=url,
                impersonate=impersonate,
                proxies=None,
                timeout=timeout,
                **kwargs
            )
            return resp
        except Exception as direct_err:
            logger.warning(f"Direct connection attempt failed for {url}: {direct_err}")

        if last_exception:
            raise last_exception
        raise RuntimeError(f"All {retries} proxy attempts failed for URL: {url}")

# Global Singleton Instance
proxy_rotator = ProxyRotator()
