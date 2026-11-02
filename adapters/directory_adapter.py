import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Any, Dict, Set
from curl_cffi import requests
from bs4 import BeautifulSoup

from adapters.base import SourceAdapter, RawLeadCandidate
from pipeline.normalizer import normalize_domain, is_valid_agency_domain
from core.database import LeadRepository

logger = logging.getLogger("DirectoryAdapter")
logger.setLevel(logging.INFO)

# High-converting B2B Outbound / Lead Gen Clutch Slugs
CLUTCH_TARGET_SLUGS = [
    "cleverly", "belkins", "martal-group", "cience", "callbox",
    "revboss", "salesroads", "operatix", "sopro", "grow-leads",
    "memory-growth", "lead-generation-lab", "lead-cookie", "sales-bread"
]

class DirectoryAdapter(SourceAdapter):
    """
    STRICT ICP LOCK: Dedicated B2B Lead Generation & Outbound Sales Agency Harvester.
    Exclusively targets:
    - B2B Lead Generation Agencies
    - Cold Email & Outreach Agencies
    - Sales Prospecting & Appointment Setting Firms
    - BPO Telemarketing & Outbound Sales Providers
    (Zero General Marketing, Zero Local SEO, Zero Web Design)
    
    Includes Persistent Pagination State (crawl_state) to eliminate duplicate crawling.
    """

    def __init__(self):
        super().__init__(name="b2b_directories", source_type="directory")
        self.session = requests.Session(impersonate="safari15_5")
        self.clutch_blocked = False
        self.themanifest_blocked = False
        self.repo = LeadRepository()

    def _strip_utm(self, url: str) -> str:
        """Removes tracking query parameters from website URLs."""
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        cleaned_qs = {k: v for k, v in qs.items() if not k.startswith("utm_") and k not in ("ref", "source")}
        new_query = urllib.parse.urlencode(cleaned_qs, doseq=True)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))

    # =========================================================================
    # 1. DesignRush B2B Lead Generation Harvester (safari15_5 cURL Friendly)
    # =========================================================================
    def scrape_designrush(self, query: str = "", limit: int = 40, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains: Set[str] = set()

        categories = [
            ("designrush_lead_gen", "https://www.designrush.com/agency/digital-marketing/lead-generation"),
            ("designrush_telemarketing", "https://www.designrush.com/agency/call-centers/telemarketing"),
            ("designrush_b2b", "https://www.designrush.com/agency/digital-marketing/b2b")
        ]

        for cat_key, base_url in categories:
            if len(candidates) >= limit:
                break

            start_page = self.repo.get_crawl_page(cat_key)
            if start_page > 12:
                start_page = 1
            current_page = start_page

            pages_to_crawl = min(15, max(6, limit // 15))
            for page_offset in range(pages_to_crawl):
                if len(candidates) >= limit:
                    break
                p = current_page + page_offset
                page_url = f"{base_url}?page={p}" if p > 1 else base_url

                try:
                    resp = self.session.get(page_url, timeout=4.0)
                    if resp.status_code == 404:
                        self.repo.set_crawl_page(cat_key, 1)
                        break
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_found = 0

                    for a in soup.find_all("a", href=True):
                        h = a["href"]
                        if not h.startswith("http"):
                            continue
                        netloc = urllib.parse.urlparse(h).netloc.lower()
                        if any(x in netloc for x in ["designrush.com", "google.com", "facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "instagram.com"]):
                            continue

                        dom = normalize_domain(h)
                        if not dom or dom in seen_domains or not is_valid_agency_domain(dom):
                            continue
                        if self.repo.is_domain_scraped_before(dom):
                            continue

                        seen_domains.add(dom)
                        name = a.get_text(strip=True)
                        if not name or len(name) < 2 or any(w in name.lower() for w in ["visit", "website", "profile", "read more"]):
                            name = dom.split(".")[0].replace("-", " ").title()

                        clean_url = self._strip_utm(h)
                        candidates.append(RawLeadCandidate(
                            business_name=name,
                            website=dom,
                            phone=None,
                            source_name="designrush_directory",
                            source_url=clean_url,
                            snippet=f"DesignRush verified B2B Lead Gen agency: {name} ({dom})",
                            raw_data={"source": "designrush", "page": p, "website": clean_url}
                        ))
                        page_found += 1
                        if len(candidates) >= limit:
                            break

                    next_p = 1 if (p + 1) >= 12 else (p + 1)
                    self.repo.set_crawl_page(cat_key, next_p)
                    if page_found > 0:
                        if on_event:
                            on_event("Recon & Source Agent", f"DesignRush: Harvested {page_found} fresh B2B lead gen agencies (Page {p}).")

                except Exception as e:
                    logger.debug(f"DesignRush error on {page_url}: {e}")
                    continue

        return candidates

    # =========================================================================
    # 2. The Manifest B2B Lead Gen Harvester (Direct Redirect Parameter)
    # =========================================================================
    def scrape_themanifest(self, query: str = "", limit: int = 40, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        if self.themanifest_blocked:
            return []
        candidates: List[RawLeadCandidate] = []
        seen_domains: Set[str] = set()

        categories = [
            ("themanifest_lead_gen", "https://themanifest.com/lead-generation/companies"),
            ("themanifest_sales_outsourcing", "https://themanifest.com/sales-outsourcing/companies"),
            ("themanifest_call_centers_outbound", "https://themanifest.com/call-centers/outbound/companies"),
            ("themanifest_bpo_telemarketing", "https://themanifest.com/bpo/telemarketing/companies"),
            ("themanifest_lead_gen_agencies", "https://themanifest.com/lead-generation/agencies"),
            ("themanifest_sales_outsourcing_agencies", "https://themanifest.com/sales-outsourcing/agencies"),
            ("themanifest_appointment_setting", "https://themanifest.com/appointment-setting/companies"),
            ("themanifest_inbound_call_center", "https://themanifest.com/inbound-call-center/companies")
        ]

        headers = {"Referer": "https://www.google.com/"}

        for cat_key, base_url in categories:
            if self.themanifest_blocked or len(candidates) >= limit:
                break

            start_page = self.repo.get_crawl_page(cat_key)
            if start_page >= 15:
                start_page = 0
            current_page = start_page

            pages_to_crawl = min(15, max(6, limit // 15))
            for page_offset in range(pages_to_crawl):
                if len(candidates) >= limit:
                    break
                p = current_page + page_offset
                page_url = f"{base_url}?page={p}" if p > 0 else base_url

                try:
                    resp = self.session.get(page_url, headers=headers, timeout=4.0)
                    if resp.status_code in (403, 429):
                        logger.debug(f"The Manifest returned {resp.status_code}. Skipping {cat_key}.")
                        break
                    if resp.status_code == 404:
                        self.repo.set_crawl_page(cat_key, 0)
                        break
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_found = 0

                    for a in soup.find_all("a", href=True):
                        h = a["href"]
                        if "themanifest.com/redirect" in h and "u=" in h:
                            qs = urllib.parse.parse_qs(urllib.parse.urlparse(h).query)
                            target_u = qs.get("u", [""])[0]
                            if not target_u:
                                continue

                            dom = normalize_domain(target_u)
                            if not dom or dom in seen_domains or not is_valid_agency_domain(dom):
                                continue
                            if self.repo.is_domain_scraped_before(dom):
                                continue

                            seen_domains.add(dom)

                            # Find agency name from card ancestor headers
                            name = ""
                            cur = a
                            for _ in range(5):
                                cur = cur.parent
                                if not cur:
                                    break
                                h_tags = cur.find_all(["h2", "h3", "h4"])
                                if h_tags:
                                    first_h = h_tags[0].get_text(strip=True)
                                    if len(first_h) > 2 and not any(w in first_h.lower() for w in ["visit", "profile", "review"]):
                                        name = first_h
                                        break

                            if not name:
                                name = dom.split(".")[0].replace("-", " ").title()

                            clean_url = self._strip_utm(target_u)
                            candidates.append(RawLeadCandidate(
                                business_name=name,
                                website=dom,
                                phone=None,
                                source_name="themanifest_directory",
                                source_url=clean_url,
                                snippet=f"The Manifest verified B2B Lead Gen agency: {name} ({dom})",
                                raw_data={"source": "themanifest", "url": clean_url}
                            ))
                            page_found += 1
                            if len(candidates) >= limit:
                                break

                    # Profile Fallback for pages where &u= is not embedded directly in card
                    profile_slugs = []
                    for a in soup.find_all("a", href=True):
                        h = a["href"]
                        if h.startswith("/company/") and len(h.split("/")) == 3 and h not in profile_slugs:
                            profile_slugs.append(h)

                    if profile_slugs and len(candidates) < limit:
                        def _fetch_tm_profile(slug: str) -> Optional[RawLeadCandidate]:
                            try:
                                p_resp = requests.get(f"https://themanifest.com{slug}", impersonate="safari15_5", timeout=3.5)
                                if p_resp.status_code != 200:
                                    return None
                                p_soup = BeautifulSoup(p_resp.text, "html.parser")
                                h1 = p_soup.find("h1")
                                biz_name = h1.get_text(strip=True) if h1 else slug.replace("/company/", "").replace("-", " ").title()

                                for pa in p_soup.find_all("a", href=True):
                                    if "redirect" in pa["href"] and "u=" in pa["href"]:
                                        u = urllib.parse.parse_qs(urllib.parse.urlparse(pa["href"]).query).get("u", [""])[0]
                                        if u:
                                            dom = normalize_domain(u)
                                            if not dom or not is_valid_agency_domain(dom):
                                                continue
                                            if self.repo.is_domain_scraped_before(dom):
                                                continue
                                            clean_u = self._strip_utm(u)
                                            return RawLeadCandidate(
                                                business_name=biz_name,
                                                website=dom,
                                                phone=None,
                                                source_name="themanifest_directory",
                                                source_url=clean_u,
                                                snippet=f"The Manifest verified B2B Lead Gen agency: {biz_name} ({dom})",
                                                raw_data={"source": "themanifest", "url": clean_u}
                                            )
                            except Exception:
                                return None
                            return None

                        with ThreadPoolExecutor(max_workers=10) as tm_exec:
                            futures = [tm_exec.submit(_fetch_tm_profile, sl) for sl in profile_slugs]
                            for f in as_completed(futures):
                                res_cand = f.result()
                                if res_cand and res_cand.website not in seen_domains:
                                    seen_domains.add(res_cand.website)
                                    candidates.append(res_cand)
                                    page_found += 1
                                    if len(candidates) >= limit:
                                        break

                    next_p = 1 if (p + 1) >= 12 else (p + 1)
                    self.repo.set_crawl_page(cat_key, next_p)
                    if page_found > 0:
                        if on_event:
                            on_event("Recon & Source Agent", f"The Manifest: Harvested {page_found} B2B lead gen agencies (Page {p}).")

                except Exception as e:
                    logger.debug(f"The Manifest error on {page_url}: {e}")
                    continue

        return candidates

    # =========================================================================
    # 3. GoodFirms B2B Lead Gen & Telemarketing Directory
    # =========================================================================
    def fetch_goodfirms_agencies(self, query: str = "", limit: int = 25, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains: Set[str] = set()

        categories = [
            ("goodfirms_lead_gen", "https://www.goodfirms.co/bpo-services/lead-generation"),
            ("goodfirms_lead_gen_usa", "https://www.goodfirms.co/bpo-services/lead-generation/usa"),
            ("goodfirms_lead_gen_uk", "https://www.goodfirms.co/bpo-services/lead-generation/uk"),
            ("goodfirms_telemarketing", "https://www.goodfirms.co/bpo-services/telemarketing"),
            ("goodfirms_telemarketing_usa", "https://www.goodfirms.co/bpo-services/telemarketing/usa"),
            ("goodfirms_telemarketing_uk", "https://www.goodfirms.co/bpo-services/telemarketing/uk"),
            ("goodfirms_lead_gen_canada", "https://www.goodfirms.co/bpo-services/lead-generation/canada"),
            ("goodfirms_lead_gen_australia", "https://www.goodfirms.co/bpo-services/lead-generation/australia")
        ]

        for cat_key, base_url in categories:
            if len(candidates) >= limit:
                break

            start_page = self.repo.get_crawl_page(cat_key)
            if start_page >= 10:
                start_page = 1
            current_page = start_page

            pages_to_crawl = min(10, max(4, limit // 20))
            consecutive_zero = 0
            for page_offset in range(pages_to_crawl):
                if len(candidates) >= limit:
                    break
                p = current_page + page_offset
                page_url = f"{base_url}?page={p}" if p > 1 else base_url

                try:
                    resp = self.session.get(page_url, timeout=8)
                    if resp.status_code == 404:
                        self.repo.set_crawl_page(cat_key, 1)
                        break
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    company_links = []
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if href.startswith("/company/") and "#" not in href and href not in company_links:
                            company_links.append(href)

                    def _fetch_gf_profile(comp_rel: str) -> Optional[RawLeadCandidate]:
                        full_profile_url = f"https://www.goodfirms.co{comp_rel}"
                        try:
                            p_resp = requests.get(full_profile_url, impersonate="safari15_5", timeout=3.5)
                            if p_resp.status_code != 200:
                                return None
                            p_soup = BeautifulSoup(p_resp.text, "html.parser")
                            h1 = p_soup.find("h1")
                            biz_name = h1.get_text(strip=True) if h1 else comp_rel.split("/")[-1].replace("-", " ").title()

                            external_website = None
                            for a in p_soup.find_all("a", href=True):
                                h = a["href"]
                                if (h.startswith("http://") or h.startswith("https://")) and not any(
                                    exc in h for exc in [
                                        "goodfirms.co", "linkedin.com", "twitter.com", "x.com",
                                        "facebook.com", "youtube.com", "instagram.com"
                                    ]
                                ):
                                    external_website = h
                                    break

                            if not external_website:
                                return None

                            clean_dom = normalize_domain(external_website)
                            if not clean_dom or clean_dom in seen_domains or not is_valid_agency_domain(clean_dom):
                                return None
                            if self.repo.is_domain_scraped_before(clean_dom):
                                return None

                            clean_url = self._strip_utm(external_website)
                            return RawLeadCandidate(
                                business_name=biz_name,
                                website=clean_dom,
                                phone=None,
                                source_name="goodfirms_directory",
                                source_url=clean_url,
                                snippet=f"GoodFirms verified B2B Lead Gen agency: {biz_name} ({clean_dom})",
                                raw_data={"profile": full_profile_url, "website": clean_url}
                            )
                        except Exception:
                            return None

                    page_found = 0
                    if company_links:
                        with ThreadPoolExecutor(max_workers=10) as executor:
                            futures = [executor.submit(_fetch_gf_profile, rel) for rel in company_links]
                            for fut in as_completed(futures):
                                cand = fut.result()
                                if cand and cand.website not in seen_domains:
                                    seen_domains.add(cand.website)
                                    candidates.append(cand)
                                    page_found += 1
                                    if len(candidates) >= limit:
                                        break

                    next_p = 1 if (p + 1) >= 10 else (p + 1)
                    self.repo.set_crawl_page(cat_key, next_p)
                    if page_found > 0:
                        consecutive_zero = 0
                        if on_event:
                            on_event("Recon & Source Agent", f"GoodFirms: Harvested {page_found} B2B lead gen agencies (Page {p}).")
                    else:
                        consecutive_zero += 1
                        if consecutive_zero >= 2:
                            break

                except Exception as e:
                    logger.debug(f"GoodFirms error: {e}")
                    continue

        return candidates

    # =========================================================================
    # 4. Sortlist B2B Lead Gen & Prospecting Directory
    # =========================================================================
    def scrape_sortlist(self, query: str = "", limit: int = 20, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        candidates: List[RawLeadCandidate] = []
        seen_domains: Set[str] = set()

        categories = [
            ("sortlist_lead_gen", "https://www.sortlist.com/lead-generation"),
            ("sortlist_prospecting", "https://www.sortlist.com/prospecting"),
            ("sortlist_lead_gen_us", "https://www.sortlist.com/s/lead-generation/united-states-us"),
            ("sortlist_lead_gen_gb", "https://www.sortlist.com/s/lead-generation/united-kingdom-gb"),
            ("sortlist_lead_gen_ca", "https://www.sortlist.com/s/lead-generation/canada-ca"),
            ("sortlist_lead_gen_au", "https://www.sortlist.com/s/lead-generation/australia-au"),
            ("sortlist_prospecting_us", "https://www.sortlist.com/s/prospecting/united-states-us"),
            ("sortlist_prospecting_gb", "https://www.sortlist.com/s/prospecting/united-kingdom-gb")
        ]

        for cat_key, base_url in categories:
            if len(candidates) >= limit:
                break

            start_page = self.repo.get_crawl_page(cat_key)
            if start_page >= 10:
                start_page = 1
            current_page = start_page

            pages_to_crawl = min(10, max(4, limit // 20))
            consecutive_zero = 0
            for page_offset in range(pages_to_crawl):
                if len(candidates) >= limit:
                    break
                p = current_page + page_offset
                cat_url = f"{base_url}?page={p}" if p > 1 else base_url

                try:
                    resp = self.session.get(cat_url, timeout=8)
                    if resp.status_code == 404:
                        self.repo.set_crawl_page(cat_key, 1)
                        break
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    agency_slugs = []
                    for a in soup.find_all("a", href=True):
                        h = a["href"]
                        if h.startswith("/agency/") and h not in agency_slugs:
                            agency_slugs.append(h)

                    def _fetch_sortlist_profile(slug: str) -> Optional[RawLeadCandidate]:
                        try:
                            p_resp = requests.get(f"https://www.sortlist.com{slug}", impersonate="safari15_5", timeout=3.5)
                            if p_resp.status_code != 200:
                                return None
                            p_soup = BeautifulSoup(p_resp.text, "html.parser")
                            h1 = p_soup.find("h1")
                            biz_name = h1.get_text(strip=True) if h1 else slug.replace("/agency/", "").replace("-", " ").title()

                            ext_site = None
                            for a in p_soup.find_all("a", href=True):
                                h = a["href"]
                                if h.startswith("http") and not any(x in h for x in ["sortlist.com", "google.com", "linkedin.com", "facebook.com", "instagram.com"]):
                                    ext_site = h
                                    break

                            if not ext_site:
                                return None

                            dom = normalize_domain(ext_site)
                            if not dom or dom in seen_domains or not is_valid_agency_domain(dom):
                                return None
                            if self.repo.is_domain_scraped_before(dom):
                                return None

                            clean_url = self._strip_utm(ext_site)
                            return RawLeadCandidate(
                                business_name=biz_name,
                                website=dom,
                                source_name="sortlist_directory",
                                source_url=clean_url,
                                snippet=f"Sortlist verified B2B Lead Gen agency: {biz_name} ({dom})",
                                raw_data={"source": "sortlist", "website": clean_url}
                            )
                        except Exception:
                            return None

                    page_found = 0
                    if agency_slugs:
                        with ThreadPoolExecutor(max_workers=10) as executor:
                            futures = [executor.submit(_fetch_sortlist_profile, slug) for slug in agency_slugs]
                            for fut in as_completed(futures):
                                cand = fut.result()
                                if cand and cand.website not in seen_domains:
                                    seen_domains.add(cand.website)
                                    candidates.append(cand)
                                    page_found += 1
                                    if len(candidates) >= limit:
                                        break

                    next_p = 1 if (p + 1) >= 10 else (p + 1)
                    self.repo.set_crawl_page(cat_key, next_p)
                    if page_found > 0:
                        consecutive_zero = 0
                        if on_event:
                            on_event("Recon & Source Agent", f"Sortlist: Harvested {page_found} B2B lead gen agencies (Page {p}).")
                    else:
                        consecutive_zero += 1
                        if consecutive_zero >= 2:
                            break

                except Exception as e:
                    logger.debug(f"Sortlist error on {cat_url}: {e}")
                    continue

        return candidates


    # =========================================================================
    # Clutch Single Profile Fetcher (with auto-failover)
    # =========================================================================
    def fetch_clutch_profile(self, slug_or_url: str) -> Optional[RawLeadCandidate]:
        if self.clutch_blocked:
            return None

        url = slug_or_url if slug_or_url.startswith("http") else f"https://clutch.co/profile/{slug_or_url}"
        try:
            resp = self.session.get(url, timeout=6)
            if resp.status_code in (403, 429):
                logger.warning(f"Clutch blocked with HTTP {resp.status_code}. Setting clutch_blocked=True.")
                self.clutch_blocked = True
                return None
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            h1 = soup.find("h1")
            biz_name = h1.get_text(strip=True) if h1 else None
            if not biz_name:
                return None

            website = None
            redirect_link = soup.find("a", href=re.compile(r"clutch\.co/redirect\?"))
            if redirect_link:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_link["href"]).query)
                website = qs.get("u", [None])[0] or qs.get("provider_website", [None])[0]
                if website:
                    website = website.split("?")[0].rstrip("/")

            if not website:
                return None

            dom = normalize_domain(website)
            if not dom:
                return None

            return RawLeadCandidate(
                business_name=biz_name,
                website=dom,
                phone=None,
                source_name="clutch_directory",
                source_url=website,
                snippet=f"Clutch profile for {biz_name}",
                raw_data={"slug": slug_or_url, "url": website}
            )
        except Exception:
            return None

    # =========================================================================
    # MASTER MULTI-DIRECTORY SEARCH (EXCLUSIVELY B2B LEAD GEN & OUTBOUND)
    # =========================================================================
    def search(self, query: str, limit: int = 25, on_event: Optional[Any] = None) -> List[RawLeadCandidate]:
        """
        Multi-source B2B Lead Gen directory harvester with persistent pagination:
        1. DesignRush (B2B Lead Generation)
        2. The Manifest (Lead Generation & Sales Outsourcing Companies)
        3. GoodFirms (B2B Lead Generation & Outbound)
        4. Sortlist (B2B Lead Generation)
        5. crt.sh (Certificate Transparency fallback)
        (Expertise.com and generic marketing directories strictly disabled)
        """
        candidates: List[RawLeadCandidate] = []
        seen_domains: Set[str] = set()

        def add_batch(new_candidates: List[RawLeadCandidate]):
            for c in new_candidates:
                if len(candidates) >= limit:
                    break
                d = normalize_domain(c.website or "")
                if d and d not in seen_domains:
                    seen_domains.add(d)
                    candidates.append(c)

        # 1. DesignRush B2B Lead Generation
        if len(candidates) < limit:
            if on_event:
                on_event("Recon & Source Agent", f"Scanning DesignRush for B2B Lead Gen agencies...")
            dr_batch = self.scrape_designrush(query=query, limit=(limit - len(candidates)), on_event=on_event)
            add_batch(dr_batch)

        # 2. The Manifest B2B Lead Gen Companies
        if len(candidates) < limit:
            if on_event:
                on_event("Recon & Source Agent", f"Scanning The Manifest for B2B Lead Gen companies...")
            tm_batch = self.scrape_themanifest(query=query, limit=(limit - len(candidates)), on_event=on_event)
            add_batch(tm_batch)

        # 3. Sortlist B2B Lead Gen Directory
        if len(candidates) < limit:
            if on_event:
                on_event("Recon & Source Agent", f"Scanning Sortlist for B2B Lead Gen agencies...")
            sort_batch = self.scrape_sortlist(query=query, limit=(limit - len(candidates)), on_event=on_event)
            add_batch(sort_batch)

        # 4. GoodFirms B2B Lead Gen Directory
        if len(candidates) < limit:
            if on_event:
                on_event("Recon & Source Agent", f"Scanning GoodFirms for B2B Lead Gen agencies...")
            gf_batch = self.fetch_goodfirms_agencies(query=query, limit=(limit - len(candidates)), on_event=on_event)
            add_batch(gf_batch)

        logger.info(f"DirectoryAdapter harvested total {len(candidates)} unique B2B Lead Gen candidates.")
        return candidates
