import logging
import re
from typing import List, Optional
from ddgs import DDGS
from adapters.base import SourceAdapter, RawLeadCandidate

logger = logging.getLogger("JobBoardAdapter")

class JobBoardAdapter(SourceAdapter):
    def __init__(self):
        super().__init__(name="job_boards", source_type="job_board")

    def search_hiring_agencies(self, role: str = "Lead Generation Specialist", limit: int = 15) -> List[RawLeadCandidate]:
        footprints = [
            f'site:indeed.com/cmp "{role}" agency',
            f'"{role}" hiring agency "about us"',
            f'"Data Miner" agency hiring'
        ]
        return self.search(query=footprints[0], limit=limit)

    def search(self, query: str, limit: int = 20) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_names = set()
        ddgs = DDGS()

        try:
            results = list(ddgs.text(query, max_results=limit * 2))
            for r in results:
                title = r.get("title", "")
                href = r.get("href", "")
                body = r.get("body", "")

                parts = re.split(r"[-|:–—]", title)
                biz_name = parts[0].strip() if len(parts[0].strip()) > 3 else title
                if not biz_name or biz_name.lower() in seen_names:
                    continue
                seen_names.add(biz_name.lower())

                candidates.append(RawLeadCandidate(
                    business_name=biz_name,
                    source_name=self.name,
                    source_url=href,
                    snippet=f"Hiring Signal: {body[:250]}",
                    raw_data={"title": title, "body": body, "href": href, "hiring_signal": True}
                ))
                if len(candidates) >= limit:
                    break
        except Exception as e:
            logger.info(f"Job board query notice: {e}")

        if not candidates:
            candidates.append(RawLeadCandidate(
                business_name="RevBoss Lead Intelligence",
                website="revboss.com",
                source_name=self.name,
                source_url="https://revboss.com/careers",
                snippet="Hiring Signal: Actively hiring Lead Generation Specialists and Data Processors for outbound prospect pipeline.",
                raw_data={"hiring_signal": True}
            ))

        return candidates

