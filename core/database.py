import sqlite3
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from pathlib import Path
from config.settings import settings
from core.schemas import (
    LeadRecord, AgencyType, VerificationStatus, PriorityTier, OutreachStatus,
    LeadClassification, EmailType, compute_domain_hash
)

GENERIC_EMAIL_PREFIXES = {
    'info', 'sales', 'hello', 'support', 'contact', 'hi', 'admin', 'office', 'inquiry', 'inquiries',
    'rfp', 'letschat', 'grow', 'howdy', 'newbiz', 'hireus', 'marketing', 'team', 'friends', 'careers',
    'jobs', 'media', 'pr', 'press', 'billing', 'help', 'service', 'connect', 'welcome', 'dev', 'accounts',
    'general', 'partner', 'partners', 'outreach', 'agency', 'hey', 'mail', 'start', 'work', 'projects',
    'chicago', 'ny', 'london', 'austin', 'usa'
}

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def utc_now_iso() -> str:
    return utc_now().isoformat()

def get_db_path() -> str:
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        path_str = db_url.replace("sqlite:///", "")
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
    return "lead_gen.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -2000;") # Limit page cache to 2MB RAM
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        lead_id TEXT PRIMARY KEY,
        business_name TEXT NOT NULL,
        domain_hash TEXT,
        agency_type TEXT NOT NULL,
        client_industries_served TEXT,
        core_services TEXT,
        data_dependency_signals TEXT,
        scale_signals TEXT,
        website TEXT,
        phone TEXT,
        email TEXT,
        verified_email TEXT,
        email_mx_status TEXT,
        address TEXT,
        city TEXT,
        region TEXT,
        country TEXT,
        decision_maker_name TEXT,
        decision_maker_role TEXT,
        decision_maker_linkedin TEXT,
        source_names TEXT,
        source_urls TEXT,
        evidence TEXT,
        collected_at TEXT,
        last_verified_at TEXT,
        last_scraped_at TEXT,
        duplicate_group_id TEXT,
        business_verification_status TEXT,
        email_verification_status TEXT,
        phone_verification_status TEXT,
        factual_confidence REAL,
        icp_fit_score INTEGER,
        opportunity_score INTEGER,
        data_dependency_score INTEGER,
        score_explanation TEXT,
        overall_priority TEXT,
        recommended_scraping_pitch TEXT,
        custom_outreach_hook TEXT,
        outreach_angle TEXT,
        outreach_draft TEXT,
        outreach_status TEXT,
        rejection_reason TEXT,
        company_size TEXT,
        company_size_score INTEGER DEFAULT 0,
        service_fit_score INTEGER DEFAULT 0,
        scale_automation_score INTEGER DEFAULT 0,
        buying_intent_score INTEGER DEFAULT 0,
        decision_maker_score INTEGER DEFAULT 0,
        contactability_score INTEGER DEFAULT 0,
        total_score INTEGER DEFAULT 0,
        lead_classification TEXT,
        email_type TEXT,
        recommended_outreach_channel TEXT,
        evidence_of_need TEXT,
        evidence_source_urls TEXT,
        backup_emails TEXT,
        complete_business_summary TEXT,
        their_target_clients TEXT,
        personalization_guide TEXT,
        source_footprint TEXT,
        target_verification_status TEXT
    )
    """)

    # Column migration check for backwards compatibility
    cursor.execute("PRAGMA table_info(leads)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    needed_cols = {
        "campaign_id": "TEXT",
        "domain_hash": "TEXT",
        "scale_signals": "TEXT",
        "verified_email": "TEXT",
        "email_mx_status": "TEXT",
        "decision_maker_linkedin": "TEXT",
        "last_scraped_at": "TEXT",
        "data_dependency_score": "INTEGER",
        "custom_outreach_hook": "TEXT",
        "company_size": "TEXT DEFAULT '2-10'",
        "company_size_score": "INTEGER DEFAULT 0",
        "service_fit_score": "INTEGER DEFAULT 0",
        "scale_automation_score": "INTEGER DEFAULT 0",
        "buying_intent_score": "INTEGER DEFAULT 0",
        "decision_maker_score": "INTEGER DEFAULT 0",
        "contactability_score": "INTEGER DEFAULT 0",
        "total_score": "INTEGER DEFAULT 0",
        "lead_classification": "TEXT",
        "email_type": "TEXT",
        "recommended_outreach_channel": "TEXT",
        "evidence_of_need": "TEXT",
        "evidence_source_urls": "TEXT",
        "backup_emails": "TEXT",
        "complete_business_summary": "TEXT",
        "their_target_clients": "TEXT",
        "personalization_guide": "TEXT",
        "source_footprint": "TEXT",
        "target_verification_status": "TEXT"
    }
    for col_name, col_type in needed_cols.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_type}")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_campaign_id ON leads(campaign_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_domain_hash ON leads(domain_hash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(overall_priority)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_opp_score ON leads(opportunity_score)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_verified_email ON leads(verified_email)")

    # 90-Day Persistent Memory Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scraped_domains (
        domain_hash TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        status TEXT NOT NULL,
        last_scraped_at TEXT NOT NULL,
        lead_id TEXT
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scraped_domain ON scraped_domains(domain)")

    # Incremental Crawl State (Directory pagination)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS crawl_state (
        source_name TEXT PRIMARY KEY,
        last_page INTEGER DEFAULT 1,
        last_scraped_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS duplicate_groups (
        group_id TEXT PRIMARY KEY,
        canonical_lead_id TEXT NOT NULL,
        lead_ids TEXT,
        merged_at TEXT,
        notes TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS campaigns (
        campaign_id TEXT PRIMARY KEY,
        raw_prompt TEXT NOT NULL,
        agency_types TEXT,
        target_geography TEXT,
        target_client_niches TEXT,
        lead_quantity INTEGER,
        status TEXT,
        total_collected INTEGER,
        total_qualified INTEGER,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback_memory (
        id TEXT PRIMARY KEY,
        feedback_type TEXT NOT NULL,
        agency_type TEXT,
        trigger_reason TEXT NOT NULL,
        mistake_rule TEXT NOT NULL,
        sample_data TEXT,
        created_at TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS golden_examples (
        id TEXT PRIMARY KEY,
        agency_type TEXT NOT NULL,
        business_name TEXT NOT NULL,
        vertical TEXT,
        scraping_pitch TEXT NOT NULL,
        lead_data TEXT,
        approved_at TEXT
    )
    """)
    conn.commit()
    conn.close()

class LeadRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()

    def _get_conn(self) -> sqlite3.Connection:
        return get_connection()

    # ---------------- 90-Day Cooldown Memory Logic ----------------
    def is_domain_in_cooldown(self, domain: Optional[str], cooldown_days: int = 90) -> bool:
        if not domain:
            return False
        from pipeline.normalizer import normalize_domain
        clean_dom = normalize_domain(domain)
        if not clean_dom:
            return False
        d_hash = compute_domain_hash(clean_dom)
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT last_scraped_at FROM scraped_domains WHERE domain_hash = ? OR LOWER(domain) = ?", (d_hash, clean_dom))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return False

        try:
            last_date = datetime.fromisoformat(row["last_scraped_at"])
            delta = utc_now() - last_date
            return delta.days < cooldown_days
        except Exception:
            return False

    def is_domain_scraped_before(self, domain: Optional[str]) -> bool:
        """
        Permanent SQLite check on root_domain:
        Returns True if domain was ever scraped before (whether accepted or rejected).
        Checks both scraped_domains and leads table.
        """
        if not domain:
            return False
        from pipeline.normalizer import normalize_domain
        clean_dom = normalize_domain(domain)
        if not clean_dom:
            return False
        d_hash = compute_domain_hash(clean_dom)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM scraped_domains WHERE domain_hash = ? OR LOWER(domain) = ? LIMIT 1", (d_hash, clean_dom))
        if cursor.fetchone():
            conn.close()
            return True

        cursor.execute("SELECT 1 FROM leads WHERE domain_hash = ? OR LOWER(website) = ? LIMIT 1", (d_hash, clean_dom))
        row = cursor.fetchone()
        conn.close()
        return row is not None

    def is_email_seen(self, email: Optional[str]) -> bool:
        if not email or "@" not in email:
            return False
        clean_email = email.strip().lower()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM leads WHERE LOWER(email) = ? OR LOWER(verified_email) = ? LIMIT 1", (clean_email, clean_email))
        row = cursor.fetchone()
        conn.close()
        return row is not None

    def record_scraped_domain(self, domain: Optional[str], status: str, lead_id: Optional[str] = None):
        if not domain:
            return
        d_hash = compute_domain_hash(domain)
        now_str = utc_now_iso()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO scraped_domains (domain_hash, domain, status, last_scraped_at, lead_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(domain_hash) DO UPDATE SET
            status=excluded.status,
            last_scraped_at=excluded.last_scraped_at,
            lead_id=excluded.lead_id
        """, (d_hash, domain, status, now_str, lead_id))
        conn.commit()
        conn.close()

    # ---------------- Incremental Crawl State ----------------
    def get_crawl_page(self, source_name: str) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT last_page FROM crawl_state WHERE source_name = ?", (source_name,))
        row = cursor.fetchone()
        conn.close()
        return row["last_page"] if row else 1

    def update_crawl_page(self, source_name: str, next_page: int):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO crawl_state (source_name, last_page, last_scraped_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            last_page=excluded.last_page,
            last_scraped_at=excluded.last_scraped_at
        """, (source_name, next_page, utc_now_iso()))
        conn.commit()
        conn.close()

    def set_crawl_page(self, source_name: str, next_page: int):
        self.update_crawl_page(source_name, next_page)

    # ---------------- Lead Persistence ----------------
    def save_lead(self, lead: LeadRecord) -> LeadRecord:
        conn = self._get_conn()
        cursor = conn.cursor()
        
        from pipeline.normalizer import normalize_domain
        clean_dom = normalize_domain(lead.website) or (lead.website or "").strip().lower()
        domain_hash = compute_domain_hash(clean_dom)
        lead.domain_hash = domain_hash
        lead.website = clean_dom

        # ZERO DUPLICATE GUARANTEE: If this domain was previously saved, reuse that row!
        cursor.execute("SELECT lead_id FROM leads WHERE domain_hash = ? OR LOWER(website) = ? LIMIT 1", (domain_hash, clean_dom))
        existing = cursor.fetchone()
        if existing:
            lead_id = str(existing[0])
            try:
                lead.lead_id = UUID(lead_id)
            except Exception:
                pass
        else:
            lead_id = str(lead.lead_id)

        agency_type = lead.agency_type.value
        client_industries_served = json.dumps(lead.client_industries_served)
        core_services = json.dumps(lead.core_services)
        data_dependency_signals = json.dumps(lead.data_dependency_signals)
        scale_signals = json.dumps(lead.scale_signals)
        source_names = json.dumps(lead.source_names)
        source_urls = json.dumps(lead.source_urls)
        evidence = json.dumps(lead.evidence)
        collected_at = lead.collected_at.isoformat() if lead.collected_at else utc_now_iso()
        last_verified_at = lead.last_verified_at.isoformat() if lead.last_verified_at else None
        last_scraped_at = lead.last_scraped_at.isoformat() if lead.last_scraped_at else utc_now_iso()
        duplicate_group_id = str(lead.duplicate_group_id) if lead.duplicate_group_id else None
        business_verification_status = lead.business_verification_status.value
        email_verification_status = lead.email_verification_status.value
        phone_verification_status = lead.phone_verification_status.value
        email_mx_status = lead.email_mx_status.value
        score_explanation = json.dumps(lead.score_explanation)
        overall_priority = lead.overall_priority.value
        outreach_status = lead.outreach_status.value
        data_dependency_score = lead.data_dependency_score or lead.opportunity_score
        company_size = lead.company_size or "2-10"
        company_size_score = lead.company_size_score
        service_fit_score = lead.service_fit_score
        scale_automation_score = lead.scale_automation_score
        buying_intent_score = lead.buying_intent_score
        decision_maker_score = lead.decision_maker_score
        contactability_score = lead.contactability_score
        total_score = lead.total_score or lead.opportunity_score
        lead_classification = lead.lead_classification.value if hasattr(lead.lead_classification, 'value') else str(lead.lead_classification)
        email_type = lead.email_type.value if hasattr(lead.email_type, 'value') else str(lead.email_type)
        recommended_outreach_channel = lead.recommended_outreach_channel or "email"
        evidence_of_need = lead.evidence_of_need or ""
        evidence_source_urls = json.dumps(lead.evidence_source_urls)
        backup_emails = json.dumps(lead.backup_emails)
        complete_business_summary = lead.complete_business_summary or ""
        their_target_clients = lead.their_target_clients or ""
        personalization_guide = lead.personalization_guide or ""
        source_footprint = lead.source_footprint or (lead.source_names[0] if lead.source_names else "Web Search")
        target_verification_status = lead.target_verification_status or "VERIFIED_TARGET (B2B Agency)"

        cursor.execute("""
        INSERT INTO leads (
            lead_id, campaign_id, business_name, domain_hash, agency_type, client_industries_served, core_services,
            data_dependency_signals, scale_signals, website, phone, email, verified_email, email_mx_status,
            address, city, region, country, decision_maker_name, decision_maker_role, decision_maker_linkedin,
            source_names, source_urls, evidence, collected_at, last_verified_at, last_scraped_at,
            duplicate_group_id, business_verification_status, email_verification_status, phone_verification_status,
            factual_confidence, icp_fit_score, opportunity_score, data_dependency_score, score_explanation,
            overall_priority, recommended_scraping_pitch, custom_outreach_hook, outreach_angle, outreach_draft,
            outreach_status, rejection_reason,
            company_size, company_size_score,
            service_fit_score, scale_automation_score, buying_intent_score, decision_maker_score, contactability_score,
            total_score, lead_classification, email_type, recommended_outreach_channel, evidence_of_need, evidence_source_urls,
            backup_emails, complete_business_summary, their_target_clients, personalization_guide, source_footprint,
            target_verification_status
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(lead_id) DO UPDATE SET
            campaign_id=COALESCE(excluded.campaign_id, leads.campaign_id),
            business_name=excluded.business_name,
            domain_hash=excluded.domain_hash,
            agency_type=excluded.agency_type,
            client_industries_served=excluded.client_industries_served,
            core_services=excluded.core_services,
            data_dependency_signals=excluded.data_dependency_signals,
            scale_signals=excluded.scale_signals,
            website=excluded.website,
            phone=excluded.phone,
            email=excluded.email,
            verified_email=excluded.verified_email,
            email_mx_status=excluded.email_mx_status,
            address=excluded.address,
            city=excluded.city,
            region=excluded.region,
            country=excluded.country,
            decision_maker_name=excluded.decision_maker_name,
            decision_maker_role=excluded.decision_maker_role,
            decision_maker_linkedin=excluded.decision_maker_linkedin,
            source_names=excluded.source_names,
            source_urls=excluded.source_urls,
            evidence=excluded.evidence,
            last_verified_at=excluded.last_verified_at,
            last_scraped_at=excluded.last_scraped_at,
            duplicate_group_id=excluded.duplicate_group_id,
            business_verification_status=excluded.business_verification_status,
            email_verification_status=excluded.email_verification_status,
            phone_verification_status=excluded.phone_verification_status,
            factual_confidence=excluded.factual_confidence,
            icp_fit_score=excluded.icp_fit_score,
            opportunity_score=excluded.opportunity_score,
            data_dependency_score=excluded.data_dependency_score,
            score_explanation=excluded.score_explanation,
            overall_priority=excluded.overall_priority,
            recommended_scraping_pitch=excluded.recommended_scraping_pitch,
            custom_outreach_hook=excluded.custom_outreach_hook,
            outreach_angle=excluded.outreach_angle,
            outreach_draft=excluded.outreach_draft,
            outreach_status=excluded.outreach_status,
            rejection_reason=excluded.rejection_reason,
            company_size=excluded.company_size,
            company_size_score=excluded.company_size_score,
            service_fit_score=excluded.service_fit_score,
            scale_automation_score=excluded.scale_automation_score,
            buying_intent_score=excluded.buying_intent_score,
            decision_maker_score=excluded.decision_maker_score,
            contactability_score=excluded.contactability_score,
            total_score=excluded.total_score,
            lead_classification=excluded.lead_classification,
            email_type=excluded.email_type,
            recommended_outreach_channel=excluded.recommended_outreach_channel,
            evidence_of_need=excluded.evidence_of_need,
            evidence_source_urls=excluded.evidence_source_urls,
            backup_emails=excluded.backup_emails,
            complete_business_summary=excluded.complete_business_summary,
            their_target_clients=excluded.their_target_clients,
            personalization_guide=excluded.personalization_guide,
            source_footprint=excluded.source_footprint,
            target_verification_status=excluded.target_verification_status
        """, (
            lead_id, lead.campaign_id or "", lead.business_name, domain_hash, agency_type, client_industries_served, core_services,
            data_dependency_signals, scale_signals, lead.website, lead.phone, lead.email, lead.verified_email, email_mx_status,
            lead.address, lead.city, lead.region, lead.country, lead.decision_maker_name, lead.decision_maker_role, lead.decision_maker_linkedin,
            source_names, source_urls, evidence, collected_at, last_verified_at, last_scraped_at,
            duplicate_group_id, business_verification_status, email_verification_status, phone_verification_status,
            lead.factual_confidence, lead.icp_fit_score, lead.opportunity_score, data_dependency_score, score_explanation,
            overall_priority, lead.recommended_scraping_pitch, lead.custom_outreach_hook, lead.outreach_angle, lead.outreach_draft,
            outreach_status, lead.rejection_reason,
            company_size, company_size_score,
            service_fit_score, scale_automation_score, buying_intent_score, decision_maker_score, contactability_score,
            total_score, lead_classification, email_type, recommended_outreach_channel, evidence_of_need, evidence_source_urls,
            backup_emails, complete_business_summary, their_target_clients, personalization_guide, source_footprint,
            target_verification_status
        ))
        conn.commit()
        conn.close()

        # Update scraped_domains table
        if lead.website:
            self.record_scraped_domain(lead.website, overall_priority, lead_id)

        return lead

    def get_lead_by_id(self, lead_id: UUID) -> Optional[LeadRecord]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads WHERE lead_id = ?", (str(lead_id),))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_lead(row) if row else None

    def find_by_domain(self, domain: str) -> Optional[LeadRecord]:
        conn = self._get_conn()
        cursor = conn.cursor()
        d_hash = compute_domain_hash(domain)
        cursor.execute("SELECT * FROM leads WHERE domain_hash = ? OR website = ?", (d_hash, domain))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_lead(row) if row else None

    def list_leads(
        self,
        priority: Optional[PriorityTier] = None,
        campaign_id: Optional[str] = None,
        limit: int = 100
    ) -> List[LeadRecord]:
        conn = self._get_conn()
        cursor = conn.cursor()
        conditions = []
        params = []
        if priority:
            conditions.append("overall_priority = ?")
            params.append(priority.value)
        if campaign_id:
            conditions.append("campaign_id = ?")
            params.append(str(campaign_id))
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM leads {where_clause} ORDER BY opportunity_score DESC, data_dependency_score DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_lead(r) for r in rows]

    def get_crawl_page(self, source_name: str) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT last_page FROM crawl_state WHERE source_name = ?", (source_name,))
        row = cursor.fetchone()
        conn.close()
        if row and row["last_page"]:
            return row["last_page"]
        # Fallback to crawl_state.json if available
        try:
            state_file = Path("crawl_state.json")
            if state_file.exists():
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get(source_name, 1)
        except Exception:
            pass
        return 1

    def set_crawl_page(self, source_name: str, page: int):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO crawl_state (source_name, last_page, last_scraped_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            last_page = excluded.last_page,
            last_scraped_at = excluded.last_scraped_at
        """, (source_name, page, utc_now_iso()))
        conn.commit()
        conn.close()
        # Mirror to crawl_state.json for visibility and persistence across runs
        try:
            state_file = Path("crawl_state.json")
            data = {}
            if state_file.exists():
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[source_name] = page
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _row_to_lead(self, row: sqlite3.Row) -> LeadRecord:
        d = dict(row)
        d["lead_id"] = UUID(d["lead_id"])
        d["campaign_id"] = d.get("campaign_id")
        if d.get("duplicate_group_id"):
            d["duplicate_group_id"] = UUID(d["duplicate_group_id"])
        d["agency_type"] = AgencyType(d["agency_type"])
        d["client_industries_served"] = json.loads(d["client_industries_served"] or "[]")
        d["core_services"] = json.loads(d["core_services"] or "[]")
        d["data_dependency_signals"] = json.loads(d["data_dependency_signals"] or "[]")
        d["scale_signals"] = json.loads(d.get("scale_signals") or "[]")
        d["source_names"] = json.loads(d["source_names"] or "[]")
        d["source_urls"] = json.loads(d["source_urls"] or "[]")
        d["evidence"] = json.loads(d["evidence"] or "{}")
        d["score_explanation"] = json.loads(d["score_explanation"] or "[]")
        d["business_verification_status"] = VerificationStatus(d["business_verification_status"])
        d["email_verification_status"] = VerificationStatus(d["email_verification_status"])
        d["phone_verification_status"] = VerificationStatus(d["phone_verification_status"])
        d["email_mx_status"] = VerificationStatus(d.get("email_mx_status") or VerificationStatus.UNKNOWN.value)
        d["overall_priority"] = PriorityTier(d["overall_priority"])
        d["outreach_status"] = OutreachStatus(d["outreach_status"])
        d["collected_at"] = datetime.fromisoformat(d["collected_at"]) if d.get("collected_at") else utc_now()
        d["last_verified_at"] = datetime.fromisoformat(d["last_verified_at"]) if d.get("last_verified_at") else None
        d["last_scraped_at"] = datetime.fromisoformat(d["last_scraped_at"]) if d.get("last_scraped_at") else utc_now()
        d["data_dependency_score"] = d.get("data_dependency_score") if d.get("data_dependency_score") is not None else (d.get("opportunity_score") or 0)
        d["opportunity_score"] = d.get("opportunity_score") or 0
        d["icp_fit_score"] = d.get("icp_fit_score") or 0
        d["factual_confidence"] = d.get("factual_confidence") or 0.0

        # Master Prompt 100-Point Scoring Model fields
        d["company_size"] = d.get("company_size") or "2-10"
        d["company_size_score"] = d.get("company_size_score") or 0
        d["service_fit_score"] = d.get("service_fit_score") or 0
        d["scale_automation_score"] = d.get("scale_automation_score") or 0
        d["buying_intent_score"] = d.get("buying_intent_score") or 0
        d["decision_maker_score"] = d.get("decision_maker_score") or 0
        d["contactability_score"] = d.get("contactability_score") or 0
        d["total_score"] = d.get("total_score") if d.get("total_score") is not None else (d.get("opportunity_score") or 0)

        raw_classification = d.get("lead_classification")
        if raw_classification:
            try:
                d["lead_classification"] = LeadClassification(raw_classification)
            except Exception:
                d["lead_classification"] = LeadClassification.CONTACT_RESEARCH_REQUIRED
        else:
            d["lead_classification"] = LeadClassification.CONTACT_RESEARCH_REQUIRED

        raw_email_type = d.get("email_type")
        if raw_email_type and raw_email_type not in ["unknown", "Unknown email type"]:
            try:
                d["email_type"] = EmailType(raw_email_type)
            except Exception:
                d["email_type"] = EmailType.GENERIC_BUSINESS
        else:
            # Classify dynamically by email prefix using comprehensive GENERIC_EMAIL_PREFIXES
            act_email = d.get("verified_email") or d.get("email") or ""
            local_prefix = act_email.split("@")[0].lower() if "@" in act_email else ""
            tokens = re.split(r"[._-]", local_prefix)
            is_generic = (not act_email or local_prefix in GENERIC_EMAIL_PREFIXES or any(t in GENERIC_EMAIL_PREFIXES for t in tokens))
            if is_generic:
                d["email_type"] = EmailType.GENERIC_BUSINESS
            else:
                # Check for person's name or firstname.lastname pattern
                d["email_type"] = EmailType.PERSONAL_PROFESSIONAL
                # Auto-infer Decision Maker if currently missing
                if not d.get("decision_maker_name") or d.get("decision_maker_name") in ["Not identified", "None", ""]:
                    if len(tokens) >= 2 and all(len(t) >= 2 and t.isalpha() for t in tokens[:2]):
                        d["decision_maker_name"] = f"{tokens[0].title()} {tokens[1].title()}"
                        if not d.get("decision_maker_role"):
                            d["decision_maker_role"] = "Founder / Leadership"
                    elif len(tokens) == 1 and len(tokens[0]) >= 3 and tokens[0].isalpha():
                        d["decision_maker_name"] = tokens[0].title()
                        if not d.get("decision_maker_role"):
                            d["decision_maker_role"] = "Leadership"

        d["recommended_outreach_channel"] = d.get("recommended_outreach_channel") or "email"
        d["evidence_of_need"] = d.get("evidence_of_need") or ""
        d["evidence_source_urls"] = json.loads(d.get("evidence_source_urls") or "[]")
        d["backup_emails"] = json.loads(d.get("backup_emails") or "[]")
        d["complete_business_summary"] = d.get("complete_business_summary") or ""
        d["their_target_clients"] = d.get("their_target_clients") or ""
        d["personalization_guide"] = d.get("personalization_guide") or ""
        d["source_footprint"] = d.get("source_footprint") or ""

        # Bug 6 Fix: Never allow REJECTED leads to say VERIFIED_TARGET!
        is_lead_rejected = (d["overall_priority"] == PriorityTier.REJECTED or d.get("lead_classification") == LeadClassification.REJECTED)
        raw_status = d.get("target_verification_status")
        if is_lead_rejected:
            rejection_note = d.get("rejection_reason") or "Failed qualification"
            d["target_verification_status"] = f"REJECTED: {rejection_note}"
        else:
            d["target_verification_status"] = raw_status or "VERIFIED_TARGET (B2B Agency)"

        return LeadRecord.model_validate(d)

init_db()

_default_repo = LeadRepository()

def get_crawl_page(source_name: str) -> int:
    return _default_repo.get_crawl_page(source_name)

def set_crawl_page(source_name: str, page: int):
    _default_repo.set_crawl_page(source_name, page)
