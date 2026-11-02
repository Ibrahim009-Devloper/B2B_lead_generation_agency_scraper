import pytest
from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus, OutreachStatus
from pipeline.scorer import ScrapingBuyerScorer
from pipeline.outreach_agent import OutreachAgent

def test_scorer_high_potential_agency():
    scorer = ScrapingBuyerScorer()
    lead = LeadRecord(
        business_name="RoofScale Inbound",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["Roofing Contractors", "Solar Installers"],
        core_services=["Cold Email Outbound", "List Building"],
        data_dependency_signals=["Builds custom verified prospect lists weekly"],
        website="roofscale.io",
        email="marcus@roofscale.io",
        phone="+15125550199",
        decision_maker_name="Marcus Vance",
        decision_maker_role="Founder",
        email_verification_status=VerificationStatus.LIKELY_VALID,
        phone_verification_status=VerificationStatus.VERIFIED,
        factual_confidence=0.85,
        evidence={
            "is_personal_email": True,
            "decision_maker_name": {"url": "https://roofscale.io/about", "snippet": "Founded by Marcus Vance"}
        }
    )

    scored = scorer.score_lead(lead)
    assert scored.icp_fit_score >= 25
    assert scored.opportunity_score >= 80
    assert scored.overall_priority in (PriorityTier.HOT_LEAD, PriorityTier.HIGH_POTENTIAL)
    assert len(scored.score_explanation) >= 4
    print("\n[High Potential Scored]:", scored.opportunity_score, "Explanation:", scored.score_explanation)

def test_scorer_reject_non_icp():
    scorer = ScrapingBuyerScorer()
    non_icp_lead = LeadRecord(
        business_name="Austin Roofing & Repairs",
        agency_type=AgencyType.NON_ICP,
        website="austinroofing.com"
    )
    scored = scorer.score_lead(non_icp_lead)
    assert scored.opportunity_score == 0
    assert scored.overall_priority == PriorityTier.REJECTED
    assert "Rejected" in (scored.rejection_reason or "")

def test_outreach_generation_under_75_words_and_no_links():
    agent = OutreachAgent()
    lead = LeadRecord(
        business_name="Local Dental Boost",
        agency_type=AgencyType.LOCAL_SEO,
        client_industries_served=["Cosmetic Dentists"],
        core_services=["GBP Optimization", "Review Audits"],
        decision_maker_name="Elena Rostova",
        decision_maker_role="Managing Director",
        overall_priority=PriorityTier.HIGH_POTENTIAL,
        evidence={"evidence_quote_niche": "We help cosmetic dentists dominate Google Map Pack."}
    )

    with_outreach = agent.generate_outreach(lead)
    draft = with_outreach.outreach_draft
    assert draft is not None
    word_count = len(draft.split())
    assert word_count < 75, f"Expected <75 words, got {word_count}"
    assert "http://" not in draft and "https://" not in draft
    assert with_outreach.outreach_status == OutreachStatus.DRAFT
    print(f"\n[Generated Outreach Draft ({word_count} words)]:\n{draft}")

