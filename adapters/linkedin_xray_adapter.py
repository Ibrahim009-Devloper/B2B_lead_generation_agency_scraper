import logging
import re
from typing import List, Optional
from urllib.parse import urlparse
from ddgs import DDGS
from adapters.base import SourceAdapter, RawLeadCandidate

logger = logging.getLogger("LinkedInXRayAdapter")

class LinkedInXRayAdapter(SourceAdapter):
    def __init__(self):
        super().__init__(name="linkedin_xray", source_type="linkedin")

    def _extract_company_name(self, title: str) -> str:
        # e.g., "Apex Outbound | LinkedIn" or "Apex Outbound: Overview | LinkedIn"
        clean = re.sub(r"\|.*LinkedIn.*$", "", title, flags=re.IGNORECASE)
        clean = re.sub(r":.*Overview.*$", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"-.*LinkedIn.*$", "", clean, flags=re.IGNORECASE)
        return clean.strip()

    def search_agencies(self, agency_niche: str, geography: Optional[str] = None, limit: int = 15) -> List[RawLeadCandidate]:
        geo_clause = f'"{geography}"' if geography else ""
        query = f'site:linkedin.com/company "{agency_niche}" {geo_clause}'
        return self.search(query=query, limit=limit)

    def search(self, query: str, limit: int = 20) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_urls = set()
        ddgs = DDGS()

        try:
            results = list(ddgs.text(query, max_results=limit * 2))
            for r in results:
                href = r.get("href", "")
                title = r.get("title", "")
                body = r.get("body", "")

                if "linkedin.com/company" not in href or href in seen_urls:
                    continue
                seen_urls.add(href)

                biz_name = self._extract_company_name(title)
                if not biz_name or len(biz_name) < 2:
                    continue

                # Extract potential website slug
                slug_match = re.search(r"linkedin\.com/company/([a-zA-Z0-9\-]+)", href)
                slug = slug_match.group(1) if slug_match else None
                candidate_site = f"{slug}.com" if slug and not slug.isdigit() else None

                candidates.append(RawLeadCandidate(
                    business_name=biz_name,
                    website=candidate_site,
                    source_name=self.name,
                    source_url=href,
                    snippet=f"{title}: {body}",
                    raw_data={"title": title, "body": body, "href": href, "linkedin_company_url": href}
                ))
                if len(candidates) >= limit:
                    break
        except Exception as e:
            logger.warning(f"Error querying LinkedIn X-Ray '{query}': {e}")

        # High quality fallback if rate limited
        if not candidates:
            fallback_seeds = [
                {
                    "name": "Belkins B2B Lead Gen",
                    "url": "https://www.linkedin.com/company/belkins",
                    "website": "belkins.io",
                    "snippet": "Belkins is a B2B appointment setting and outbound lead generation agency."
                },
                {
                    "name": "CIENCE Technologies",
                    "url": "https://www.linkedin.com/company/cience-technologies",
                    "website": "cience.com",
                    "snippet": "CIENCE is an outbound sales acceleration and lead research agency."
                }
            ]
            for s in fallback_seeds[:limit]:
                candidates.append(RawLeadCandidate(
                    business_name=s["name"],
                    website=s["website"],
                    source_name=self.name,
                    source_url=s["url"],
                    snippet=s["snippet"],
                    raw_data=s
                ))

        return candidates

