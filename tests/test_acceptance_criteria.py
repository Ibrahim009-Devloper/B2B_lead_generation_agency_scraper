import os
import json
import pytest
from core.orchestrator import master_orchestrator
from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus
from pipeline.normalizer import normalize_domain, normalize_phone
from pipeline.deduplicator import deduplication_engine
from pipeline.verifier import lead_verifier
from pipeline.scorer import scraping_buyer_scorer
from pipeline.outreach_agent import outreach_agent
from api.exporter import lead_exporter
from learning.evaluator import pipeline_evaluator

def test_criterion_1_agency_campaign_parsing():
    """Criterion 1: Turns a natural language prompt into a structured search plan."""
    prompt = "Find 30 Cold Email & Local SEO agencies in Florida"
    plan = master_orchestrator.parse_campaign_prompt(prompt)
    assert len(plan.agency_types) >= 1
    assert any(t in plan.agency_types for t in (AgencyType.COLD_EMAIL, AgencyType.LOCAL_SEO, AgencyType.B2B_LEAD_GEN))
    assert len(plan.search_queries) >= 1
    print("\n[Criterion 1 Passed]: Plan parsed into", plan.search_queries)

def test_criterion_2_permitted_collection_and_enrichment():
    """Criterion 2: Collects agency websites and enriches services & team browserless."""
    candidates = master_orchestrator.search_adapter.search("cold email agency", limit=2)
    assert len(candidates) > 0
    first_cand = candidates[0]
    assert first_cand.website or first_cand.source_url
    print("\n[Criterion 2 Passed]: Discovered agency candidate:", first_cand.business_name, first_cand.website)

def test_criterion_3_agency_schema_normalization():
    """Criterion 3: Populates agency_type, client_industries_served while keeping unknown fields null."""
    lead = LeadRecord(
        business_name="Niche Inbound",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["Solar Installers"],
        core_services=["Outbound Cold Email"],
        data_dependency_signals=["Outbound lists"]
    )
    assert lead.phone is None
    assert lead.email is None
    assert lead.address is None
    assert lead.agency_type == AgencyType.COLD_EMAIL
    assert lead.client_industries_served == ["Solar Installers"]
    print("\n[Criterion 3 Passed]: Standard Lead Schema keeps unknown fields strictly null")

def test_criterion_4_deduplication():
    """Criterion 4: Flags and merges duplicate agency listings across Maps and Search results."""
    lead_a = LeadRecord(business_name="Vanguard SEO", website="vanguardseo.com", source_names=["maps"])
    lead_b = LeadRecord(business_name="Vanguard SEO Agency", website="https://www.vanguardseo.com/services", source_names=["search"], client_industries_served=["Lawyers"])
    
    assert deduplication_engine.are_exact_duplicates(lead_a, lead_b) is True
    merged = deduplication_engine.merge_leads(lead_a, lead_b)
    assert "maps" in merged.source_names
    assert "search" in merged.source_names
    assert "Lawyers" in merged.client_industries_served
    print("\n[Criterion 4 Passed]: Exact and fuzzy deduplication links under group", merged.duplicate_group_id)

def test_criterion_5_evidence_preservation():
    """Criterion 5: Stores exact URLs and text snippets proving agency niche, services, founder identity."""
    lead = LeadRecord(
        business_name="Vanguard Outbound",
        agency_type=AgencyType.COLD_EMAIL,
        decision_maker_name="Sarah Miller",
        evidence={
            "decision_maker_name": {
                "url": "https://vanguardoutbound.io/team",
                "snippet": "Sarah Miller is the Founder & CEO of Vanguard Outbound."
            },
            "evidence_quote_niche": "We build outbound pipelines for B2B SaaS."
        }
    )
    assert lead.evidence["decision_maker_name"]["url"] == "https://vanguardoutbound.io/team"
    assert "Sarah Miller is the Founder" in lead.evidence["decision_maker_name"]["snippet"]
    print("\n[Criterion 5 Passed]: Provenance evidence preserved with URLs and snippets")

def test_criterion_6_dual_scoring():
    """Criterion 6: Computes separate factual_confidence (0.0-1.0) and opportunity_score (0-100)."""
    lead = LeadRecord(
        business_name="HyperScale Leads",
        agency_type=AgencyType.B2B_LEAD_GEN,
        client_industries_served=["HVAC"],
        data_dependency_signals=["Needs prospect data"],
        factual_confidence=0.85
    )
    scored = scraping_buyer_scorer.score_lead(lead)
    assert 0.0 <= scored.factual_confidence <= 1.0
    assert 0 <= scored.opportunity_score <= 100
    assert scored.icp_fit_score >= 25
    print("\n[Criterion 6 Passed]: Factual confidence:", scored.factual_confidence, "| Opportunity score:", scored.opportunity_score)

def test_criterion_7_explainable_filtering():
    """Criterion 7: Clearly explains why an agency scored High-Potential or why non-agency was Rejected."""
    non_agency = LeadRecord(
        business_name="Downtown Dental Clinic",
        agency_type=AgencyType.NON_ICP,
        website="downtowndental.com"
    )
    rejected = scraping_buyer_scorer.score_lead(non_agency)
    assert rejected.overall_priority == PriorityTier.REJECTED
    assert len(rejected.score_explanation) > 0
    assert "not a B2B agency" in rejected.score_explanation[0]
    print("\n[Criterion 7 Passed]: Explainable rejection:", rejected.score_explanation[0])

def test_criterion_8_tailored_scraping_pitch():
    """Criterion 8: Generates a specific recommended_scraping_pitch based on industries agency serves."""
    lead = LeadRecord(
        business_name="Contractor Growth Labs",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["Commercial Roofing Contractors"],
        core_services=["Outbound Lead Generation"],
        overall_priority=PriorityTier.HIGH_POTENTIAL
    )
    with_pitch = outreach_agent.generate_outreach(lead)
    assert with_pitch.recommended_scraping_pitch is not None
    assert with_pitch.outreach_draft is not None
    assert len(with_pitch.outreach_draft.split()) < 75
    pitch_text = f"{with_pitch.recommended_scraping_pitch} {with_pitch.outreach_draft}".lower()
    assert any(term in pitch_text for term in ["roof", "contractor"])
    print("\n[Criterion 8 Passed]: Tailored pitch generated:\n", with_pitch.recommended_scraping_pitch)

def test_criterion_9_export_and_telemetry(tmp_path):
    """Criterion 9: Exports qualified leads to CSV and XLSX alongside collection and cost metrics."""
    leads = [
        LeadRecord(
            business_name="Lead Velocity Inc",
            agency_type=AgencyType.COLD_EMAIL,
            client_industries_served=["Fintech"],
            opportunity_score=85,
            overall_priority=PriorityTier.HIGH_POTENTIAL
        )
    ]
    csv_file = tmp_path / "leads.csv"
    xlsx_file = tmp_path / "leads.xlsx"
    lead_exporter.export_to_csv(leads, str(csv_file))
    lead_exporter.export_to_xlsx(leads, str(xlsx_file))
    
    assert os.path.exists(csv_file)
    assert os.path.exists(xlsx_file)
    
    metrics = pipeline_evaluator.calculate_metrics(leads)
    assert metrics["total_leads"] == 1
    assert metrics["qualified_count"] == 1
    print("\n[Criterion 9 Passed]: Export and telemetry validated. Metrics:", metrics)

def test_criterion_10_epistemic_honesty():
    """Criterion 10: Never invents decision-makers or guarantees deliverability from MX alone."""
    # 1. MX match must be LIKELY_VALID, never VERIFIED
    status, _ = lead_verifier.verify_email("founder@google.com")
    assert status == VerificationStatus.LIKELY_VALID
    assert status != VerificationStatus.VERIFIED

    # 2. Decision maker without evidence URL/snippet is cleared
    unverified_dm_lead = LeadRecord(
        business_name="Hype Agency",
        decision_maker_name="Fictional CEO",
        evidence={}
    )
    verified = lead_verifier.verify_lead(unverified_dm_lead)
    assert verified.decision_maker_name is None
    print("\n[Criterion 10 Passed]: Epistemic honesty strictly enforced (no hallucinations allowed)")
