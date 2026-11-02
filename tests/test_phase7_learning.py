import pytest
from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus
from learning.memory_store import MemoryStore
from learning.evaluator import PipelineEvaluator

def test_memory_store_penalty_and_golden_examples():
    store = MemoryStore()
    
    # 1. Log a penalty rule
    store.add_penalty(
        trigger_reason="Classified local plumber as an agency buyer",
        mistake_rule="Never classify direct local home services as agencies",
        agency_type="non_icp"
    )
    penalties = store.get_penalties(limit=3)
    assert any("Never classify direct local home services" in p for p in penalties)

    # 2. Log a golden example
    sample_golden = LeadRecord(
        business_name="Dental Growth Pro",
        agency_type=AgencyType.LOCAL_SEO,
        client_industries_served=["Cosmetic Dentists"],
        recommended_scraping_pitch="Automated map pack review & citation scraper for cosmetic dentists",
        overall_priority=PriorityTier.HIGH_POTENTIAL
    )
    store.add_golden_example(sample_golden)
    goldens = store.get_golden_examples(agency_type="local_seo")
    assert len(goldens) > 0
    assert goldens[0]["business_name"] == "Dental Growth Pro"

    # 3. Dynamic in-context prompt enhancement
    enhancement = store.get_in_context_prompt_enhancement(agency_type="local_seo")
    assert "CRITICAL AVOIDANCE RULES" in enhancement
    assert "GOLDEN EXAMPLES" in enhancement
    print("\n[Dynamic In-Context Injected Prompt]:\n", enhancement)

def test_pipeline_evaluator():
    evaluator = PipelineEvaluator()
    leads = [
        LeadRecord(business_name="Agency 1", overall_priority=PriorityTier.HIGH_POTENTIAL, email_verification_status=VerificationStatus.LIKELY_VALID, decision_maker_name="Sarah"),
        LeadRecord(business_name="Agency 2", overall_priority=PriorityTier.QUALIFIED, email_verification_status=VerificationStatus.LIKELY_VALID),
        LeadRecord(business_name="Local Bakery", overall_priority=PriorityTier.REJECTED)
    ]
    metrics = evaluator.calculate_metrics(leads)
    assert metrics["total_leads"] == 3
    assert metrics["qualified_count"] == 2
    assert metrics["rejected_count"] == 1
    assert metrics["qualification_rate"] == 0.667
    assert metrics["dm_extraction_rate"] == 0.333
    print("\n[Evaluator Metrics Output]:", metrics)

