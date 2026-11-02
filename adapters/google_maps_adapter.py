import logging
import re
from typing import List, Optional
from urllib.parse import urlparse
from ddgs import DDGS
from adapters.base import SourceAdapter, RawLeadCandidate

logger = logging.getLogger("GoogleMapsAdapter")

class GoogleMapsAdapter(SourceAdapter):
    def __init__(self):
        super().__init__(name="google_maps", source_type="maps")

    def _extract_phone(self, text: str) -> Optional[str]:
        # Regex for US/International phone formats
        phone_match = re.search(r"\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}\b", text)
        return phone_match.group(0).strip() if phone_match else None

    def _clean_domain(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            excluded = [
                "bing.com", "google.com", "duckduckgo.com", "yelp.com", "yellowpages.com",
                "mapquest.com", "bbb.org", "facebook.com", "linkedin.com", "clutch.co"
            ]
            for exc in excluded:
                if exc in netloc:
                    return None
            return netloc
        except Exception:
            return None

    def search_local(self, agency_type: str, city: str, limit: int = 15) -> List[RawLeadCandidate]:
        query = f"{agency_type} {city} phone address"
        return self.search(query=query, limit=limit, city=city)

    def search(self, query: str, limit: int = 20, city: Optional[str] = None) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains = set()
        ddgs = DDGS()

        queries = [
            query,
            f"{query} local business profile"
        ]

        for q in queries:
            if len(candidates) >= limit:
                break
            try:
                results = list(ddgs.text(q, max_results=limit))
                for r in results:
                    title = r.get("title", "")
                    href = r.get("href", "")
                    body = r.get("body", "")
                    full_text = f"{title} {body}"

                    domain = self._clean_domain(href)
                    if not domain or domain in seen_domains:
                        continue
                    seen_domains.add(domain)

                    phone = self._extract_phone(full_text)
                    parts = re.split(r"[-|:–—]", title)
                    biz_name = parts[0].strip() if len(parts[0].strip()) > 3 else title

                    candidates.append(RawLeadCandidate(
                        business_name=biz_name,
                        website=domain,
                        phone=phone,
                        city=city,
                        source_name=self.name,
                        source_url=href,
                        snippet=body[:250],
                        raw_data={"title": title, "body": body, "href": href}
                    ))
                    if len(candidates) >= limit:
                        break
            except Exception as e:
                logger.warning(f"Error querying maps search '{q}': {e}")
                continue

        return candidates

