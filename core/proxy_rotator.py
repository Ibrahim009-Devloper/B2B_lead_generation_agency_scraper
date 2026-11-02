import os
import time
import logging
import threading
from typing import List, Dict, Optional, Any
from pathlib import Path
from curl_cffi import requests

logger = logging.getLogger("ProxyRotator")

# Fallback default pool provided by user
DEFAULT_PROXIES = [
    "45.38.107.97:6014:ndmcilxj:itztvi7o8gz9",
    "64.137.96.74:6641:ndmcilxj:itztvi7o8gz9",
    "198.23.243.226:6361:ndmcilxj:itztvi7o8gz9",
    "38.154.185.97:6370:ndmcilxj:itztvi7o8gz9",
    "84.247.60.125:6095:ndmcilxj:itztvi7o8gz9",
    "191.96.254.138:6185:ndmcilxj:itztvi7o8gz9",
    "198.46.161.42:5092:ndmcilxj:itztvi7o8gz9",
    "64.137.10.153:5803:ndmcilxj:itztvi7o8gz9",
    "104.164.49.38:7693:ndmcilxj:itztvi7o8gz9",
    "23.26.71.145:5628:ndmcilxj:itztvi7o8gz9",
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
        """Returns the next authenticated proxy URL in round-robin order."""
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

            # If all are in cooldown, pick the one expiring soonest
            if self.cooldowns:
                soonest = min(self.cooldowns.keys(), key=lambda p: self.cooldowns[p])
                return soonest

            return self.proxies[self.index % total]

    def get_proxies_dict(self) -> Optional[Dict[str, str]]:
        """Returns {'http': proxy_url, 'https': proxy_url} for requests / curl_cffi."""
        proxy_url = self.get_next_proxy()
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    def report_failure(self, proxy_url: Optional[str], status_code: Optional[int] = None, reason: str = ""):
        """Puts a blocked or failed proxy into a temporary cooldown if repeated or hard network error."""
        if not proxy_url:
            return
        with self.lock:
            count = self.failure_counts.get(proxy_url, 0) + 1
            self.failure_counts[proxy_url] = count
            # Hard connection errors (curl error, timeout) cool down immediately
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
        If a proxy suffers network/connection timeout, immediately rotates to the next proxy!
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
                self.report_success(proxy_url)
                return resp
            except Exception as e:
                last_exception = e
                self.report_failure(proxy_url, reason=str(e)[:60])
                continue

        if last_exception:
            raise last_exception
        raise RuntimeError(f"All {retries} proxy attempts failed for URL: {url}")

# Global Singleton Instance
proxy_rotator = ProxyRotator()
