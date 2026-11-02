import pytest
from core.orchestrator import MasterOrchestrator
from core.schemas import AgencyType, PriorityTier

def test_campaign_parsing():
    orchestrator = MasterOrchestrator()
    prompt = "Find 5 Cold Email & Local SEO agencies in Texas specializing in roofing or dental"
    plan = orchestrator.parse_campaign_prompt(prompt)
    
    assert len(plan.agency_types) > 0
    assert any(t in plan.agency_types for t in (AgencyType.COLD_EMAIL, AgencyType.LOCAL_SEO, AgencyType.B2B_LEAD_GEN))
    assert len(plan.search_queries) > 0
    print("\n[Parsed Campaign Plan]:", plan.model_dump())

def test_end_to_end_campaign_execution():
    orchestrator = MasterOrchestrator()
    # Run a targeted mini-campaign
    prompt = "Cold email lead generation agencies"
    result = orchestrator.run_campaign(prompt, target_count=2)
    
    assert "campaign_id" in result
    assert "metrics" in result
    assert "leads" in result
    leads = result["leads"]
    assert len(leads) > 0
    
    # Check first lead structure
    first = leads[0]
    assert first.business_name
    assert first.opportunity_score >= 0
    assert len(first.score_explanation) > 0
    if first.overall_priority in (PriorityTier.HIGH_POTENTIAL, PriorityTier.QUALIFIED):
        assert first.recommended_scraping_pitch is not None
        assert first.outreach_draft is not None

    print(f"\n[End-to-End Campaign Success]: {len(leads)} leads processed. Metrics: {result['metrics']}")

