import os
import logging
import re
import base64
import urllib.parse
from typing import List, Optional, Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from curl_cffi import requests
from ddgs import DDGS
from adapters.base import SourceAdapter, RawLeadCandidate
from core.proxy_rotator import proxy_rotator

logger = logging.getLogger("SearchApiAdapter")

def _clean_stale_proxies():
    """Bypasses stale local proxies (127.0.0.1 / localhost) that cause ConnectError."""
    for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        val = os.environ.get(k, "")
        if "127.0.0.1" in val or "localhost" in val:
            os.environ.pop(k, None)

def _decode_bing_u(href: str) -> str:
    """Decodes Bing click-tracking redirects (u=a1<base64>...) directly to real target URL."""
    if "bing.com/ck/a" in href and "u=" in href:
        try:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            u_param = qs.get("u", [""])[0]
            if u_param.startswith("a1"):
                raw_b64 = u_param[2:]
                raw_b64 += "=" * ((4 - len(raw_b64) % 4) % 4)
                return base64.b64decode(raw_b64).decode("utf-8", errors="ignore")
        except Exception:
            pass
    return href

class SearchApiAdapter(SourceAdapter):
    def __init__(self):
        super().__init__(name="search_footprints", source_type="search")
        self.session = requests.Session(impersonate="safari15_5")

    def _clean_domain(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            # Exclude aggregator, directory, tech giant, and SaaS blog domains from direct agency websites
            excluded = [
                "bing.com", "google.com", "duckduckgo.com", "linkedin.com", "facebook.com",
                "twitter.com", "x.com", "youtube.com", "reddit.com", "medium.com", "wikipedia.org",
                "upwork.com", "fiverr.com", "clutch.co", "goodfirms.co", "techbehemoths.com",
                "themanifest.com", "designrush.com", "sortlist.com", "sortlist.co.uk",
                "trustanalytica.org", "g2.com", "capterra.com", "softwareadvice.com",
                "trustpilot.com", "zoominfo.com", "apollo.io", "builtwith.com", "crunchbase.com",
                "glassdoor.com", "indeed.com", "karobardirectory.com", "shorturl.at",
                "openai.com", "chatgpt.com", "investopedia.com", "xero.com", "shopify.com",
                "microsoft.com", "apple.com", "hubspot.com", "salesforce.com", "semrush.com",
                "ahrefs.com", "forbes.com", "entrepreneur.com", "inc.com", "businessinsider.com",
                "saleshandy.com", "sequenzy.com", "salesbread.com", "emailanalytics.com",
                "stackoverflow.com", "github.com", "gitlab.com", "quora.com", "kaskus.co.id"
            ]
            for exc in excluded:
                if exc in netloc:
                    return None
            return netloc
        except Exception:
            return None

    def _extract_name_from_title(self, title: str) -> str:
        parts = re.split(r"[-|:–—]", title)
        candidate = parts[0].strip()
        if 2 < len(candidate) < 40 and not any(w in candidate.lower() for w in ["best", "top", "list of", "compare", "home", "services"]):
            return candidate
        return parts[-1].strip() if len(parts) > 1 and len(parts[-1].strip()) < 40 else candidate

    def _search_bing(self, query: str, limit: int = 25) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains = set()

        # Search multiple result pages (&first=1, &first=11, &first=21)
        pages = [1, 11, 21]
        for start_idx in pages:
            if len(candidates) >= limit:
                break
            try:
                encoded_q = urllib.parse.quote(query)
                bing_url = f"https://www.bing.com/search?q={encoded_q}&setlang=en-US&first={start_idx}"
                proxies = proxy_rotator.get_proxies_dict()
                resp = self.session.get(bing_url, proxies=proxies, timeout=6.0)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                # Exclusively organic search items
                for li in soup.find_all("li", class_=re.compile(r"b_algo")):
                    h2 = li.find("h2")
                    if not h2:
                        continue
                    a = h2.find("a")
                    if not a or not a.get("href"):
                        continue

                    raw_href = a["href"]
                    real_href = _decode_bing_u(raw_href)
                    dom = self._clean_domain(real_href)
                    if not dom or dom in seen_domains:
                        continue
                    seen_domains.add(dom)

                    title = h2.get_text(strip=True)
                    snippet_elem = li.find("p") or li.find("div", class_="b_caption")
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else f"Found via Bing search for {query}"
                    biz_name = self._extract_name_from_title(title)

                    candidates.append(RawLeadCandidate(
                        business_name=biz_name,
                        website=dom,
                        source_name=self.name,
                        source_url=real_href,
                        snippet=f"{title}: {snippet}",
                        raw_data={"engine": "bing", "title": title, "url": real_href}
                    ))
                    if len(candidates) >= limit:
                        break
            except Exception as e:
                logger.debug(f"Bing search notice for query '{query}': {e}")
                break

        return candidates

    def search(self, query: str, limit: int = 20, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains = set()

        _clean_stale_proxies()

        clean_q = query.replace('"', '').strip()
        if not clean_q:
            clean_q = "b2b lead generation agency"

        # 1. Primary High-Speed Engine: Bing HTML Search with Base64 Decoding
        bing_results = self._search_bing(clean_q, limit=limit)
        for c in bing_results:
            if c.website and c.website not in seen_domains:
                seen_domains.add(c.website)
                candidates.append(c)
                if len(candidates) >= limit:
                    return candidates

        # 2. Secondary Engine: DuckDuckGo Fallback
        if len(candidates) < limit:
            try:
                ddgs = DDGS(proxy=None, timeout=3.5)
                ddg_results = list(ddgs.text(clean_q, max_results=min(15, limit - len(candidates))))
                for r in ddg_results:
                    href = r.get("href", "")
                    title = r.get("title", "")
                    body = r.get("body", "")

                    dom = self._clean_domain(href)
                    if not dom or dom in seen_domains:
                        continue
                    seen_domains.add(dom)

                    biz_name = self._extract_name_from_title(title)
                    candidates.append(RawLeadCandidate(
                        business_name=biz_name,
                        website=dom,
                        source_name=self.name,
                        source_url=href,
                        snippet=f"{title}: {body}",
                        raw_data={"engine": "ddg", "title": title, "body": body, "href": href}
                    ))
                    if len(candidates) >= limit:
                        break
            except Exception as e:
                logger.debug(f"DDGS fallback notice: {e}")

        return candidates
