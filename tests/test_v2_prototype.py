import pytest
import os
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd

from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus
from core.database import LeadRepository, get_connection
from core.llm_router import llm_router, TaskType
from adapters.directory_adapter import DirectoryAdapter
from adapters.website_enrichment import WebsiteEnrichmentAgent
from pipeline.scorer import ScrapingBuyerScorerV2
from pipeline.outreach_agent import OutreachAgent
from api.exporter import LeadExporter

@pytest.fixture
def repo():
    return LeadRepository()

def test_v2_criterion_1_directory_targeting():
    """
    V2 Criterion 1: Execute a command targeting one directory (e.g. a specific Clutch page / footprint).
    """
    adapter = DirectoryAdapter()
    candidates = adapter.search("site:clutch.co/agencies/lead-generation California", limit=3)
    assert len(candidates) > 0
    assert any("directories" in c.source_name.lower() or "clutch" in (c.source_url or "").lower() for c in candidates)
    for c in candidates:
        assert c.business_name
        assert c.website

def test_v2_criterion_2_duplicate_bypass_90day_cooldown(repo):
    """
    V2 Criterion 2: Successfully bypass duplicate domains using the scraped_domains SQLite database.
    Verifies that domains scraped within 90 days are skipped (0 token cost).
    """
    test_domain = f"test-agency-{uuid4().hex[:8]}.com"
    
    # Initially not in cooldown
    assert not repo.is_domain_in_cooldown(test_domain, cooldown_days=90)
    
    # Record domain as scraped today
    repo.record_scraped_domain(test_domain, status="Hot Lead")
    
    # Should now be in cooldown
    assert repo.is_domain_in_cooldown(test_domain, cooldown_days=90)
    
    # Test 91-day expired record
    expired_domain = f"expired-agency-{uuid4().hex[:8]}.com"
    conn = get_connection()
    old_time = (datetime.now(timezone.utc) - timedelta(days=95)).isoformat()
    cursor = conn.cursor()
    import hashlib
    h = hashlib.sha256(expired_domain.encode("utf-8")).hexdigest()
    cursor.execute(
        "INSERT OR REPLACE INTO scraped_domains (domain_hash, domain, status, last_scraped_at) VALUES (?, ?, ?, ?)",
        (h, expired_domain, "Qualified Prospect", old_time)
    )
    conn.commit()
    conn.close()
    
    # Expired domain should NOT be in cooldown
    assert not repo.is_domain_in_cooldown(expired_domain, cooldown_days=90)

def test_v2_criterion_3_zero_token_prefiltering():
    """
    V2 Criterion 3: Perform Zero-Token Pre-filtering to drop irrelevant agencies using Python logic.
    """
    enricher = WebsiteEnrichmentAgent()
    
    # Irrelevant HTML (dental clinic)
    irrelevant_text = "We provide gentle dental cleaning, teeth whitening, and family dentistry."
    assert not enricher.zero_token_prefilter(irrelevant_text)
    
    # Relevant B2B agency HTML
    relevant_text = "Apex Growth is a B2B lead generation agency specialized in cold email outbound campaigns."
    assert enricher.zero_token_prefilter(relevant_text)
    
    # Test HTML payload compression strips non-content and cuts tokens
    raw_html = """
    <html>
        <head><style>.nav { display: flex; }</style></head>
        <body>
            <nav><a href="/home">Home</a><a href="/login">Login</a></nav>
            <main>
                <h1>B2B Outbound Lead Generation for SaaS</h1>
                <p>We build high-converting cold email sequences and verified prospect databases.</p>
            </main>
            <footer><p>© 2026 All Rights Reserved</p></footer>
            <script>console.log("analytics tracking");</script>
        </body>
    </html>
    """
    compressed = enricher.compress_html_payload(raw_html)
    assert "<script>" not in compressed
    assert "<style>" not in compressed
    assert "Home" not in compressed
    assert "B2B Outbound Lead Generation" in compressed

def test_v2_criterion_4_multi_key_rotation():
    """
    V2 Criterion 4: Rotate between at least 2 LLM API keys for the remaining valid sites.
    """
    assert len(llm_router.groq_pool.keys) >= 2 or len(llm_router.gemini_pool.keys) >= 2
    
    active_pool = llm_router.groq_pool if llm_router.groq_pool.keys else llm_router.gemini_pool
    key1 = active_pool.get_next_key()
    key2 = active_pool.get_next_key()
    
    # Verify round-robin key switching
    assert key1 != key2 or len(active_pool.keys) == 1
    assert active_pool.key_count >= 2

def test_v2_criterion_5_score_and_custom_outreach_hook():
    """
    V2 Criterion 5: Generate the data_dependency_score and custom_outreach_hook.
    """
    scorer = ScrapingBuyerScorerV2()
    outreach = OutreachAgent()
    
    lead = LeadRecord(
        business_name="SignalFlow Outbound",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["SaaS", "Fintech"],
        core_services=["Cold Email Outbound", "List Building"],
        data_dependency_signals=["Requires fresh prospect data continuously"],
        scale_signals=["Automates massive volume campaigns"],
        website="signalflow.io",
        email="alex@signalflow.io",
        verified_email="alex@signalflow.io",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        decision_maker_name="Alex Mercer",
        decision_maker_role="CEO",
        decision_maker_linkedin="https://linkedin.com/in/alex-mercer",
        factual_confidence=0.9
    )
    
    scored_lead = scorer.score_lead(lead)
    assert scored_lead.data_dependency_score >= 25
    assert scored_lead.opportunity_score >= 80
    assert scored_lead.overall_priority == PriorityTier.HOT_LEAD
    
    enriched_lead = outreach.generate_outreach(scored_lead)
    assert enriched_lead.custom_outreach_hook is not None
    assert any(term in enriched_lead.custom_outreach_hook.lower() for term in ["cold email", "apollo", "lead", "list", "prospect", "data", "scrape"])
    assert enriched_lead.outreach_draft is not None
    # Outreach draft must be under 75 words, plain-text, no links
    word_count = len(enriched_lead.outreach_draft.split())
    assert word_count <= 75
    assert "http" not in enriched_lead.outreach_draft

def test_v2_criterion_6_export_hot_leads_to_csv(tmp_path):
    """
    V2 Criterion 6: Export the final Hot Leads to a CSV without crashing on rate limits.
    """
    exporter = LeadExporter()
    out_csv = tmp_path / "hot_leads.csv"
    
    lead = LeadRecord(
        business_name="TargetReach B2B",
        agency_type=AgencyType.B2B_LEAD_GEN,
        website="targetreach.co",
        data_dependency_score=90,
        opportunity_score=90,
        overall_priority=PriorityTier.HOT_LEAD,
        custom_outreach_hook="I can build custom APIs to scrape thousands of fresh, verified leads daily from Apollo/LinkedIn for your client campaigns.",
        scale_signals=["Hiring lead gen specialists"]
    )
    
    exported_file = exporter.export_to_csv([lead], str(out_csv))
    assert Path(exported_file).exists()
    
    df = pd.read_csv(exported_file)
    assert len(df) == 1
    assert "Data Dependency Score" in df.columns
    assert "Custom Outreach Hook" in df.columns
    assert "Domain Hash" in df.columns
    assert df["Data Dependency Score"].iloc[0] == 90
    assert "Apollo/LinkedIn" in df["Custom Outreach Hook"].iloc[0]

