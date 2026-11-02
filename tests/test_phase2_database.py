import pytest
from uuid import uuid4
from core.database import LeadRepository, init_db
from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_save_and_retrieve_lead():
    repo = LeadRepository()
    lead_id = uuid4()
    lead = LeadRecord(
        lead_id=lead_id,
        business_name="Nexus Cold Outreach",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["B2B SaaS", "Fintech"],
        core_services=["Outbound Lead Generation", "Cold Email Automation"],
        data_dependency_signals=["Needs custom verified B2B lists"],
        website="nexusoutreach.io",
        email="founder@nexusoutreach.io",
        phone="+15125550199",
        decision_maker_name="Sarah Jenkins",
        decision_maker_role="Founder & CEO",
        evidence={
            "decision_maker_name": {
                "url": "https://nexusoutreach.io/about",
                "snippet": "Founded by Sarah Jenkins in 2021"
            }
        },
        opportunity_score=85,
        overall_priority=PriorityTier.HIGH_POTENTIAL
    )

    saved = repo.save_lead(lead)
    assert saved.lead_id == lead_id

    retrieved = repo.get_lead_by_id(lead_id)
    assert retrieved is not None
    assert retrieved.business_name == "Nexus Cold Outreach"
    assert retrieved.agency_type == AgencyType.COLD_EMAIL
    assert retrieved.opportunity_score == 85
    assert retrieved.overall_priority == PriorityTier.HIGH_POTENTIAL
    assert "B2B SaaS" in retrieved.client_industries_served
    assert retrieved.evidence["decision_maker_name"]["snippet"] == "Founded by Sarah Jenkins in 2021"

def test_find_by_domain_and_update():
    repo = LeadRepository()
    domain = f"test-agency-{uuid4().hex[:6]}.com"
    lead = LeadRecord(
        business_name="Local Ranking Pro",
        agency_type=AgencyType.LOCAL_SEO,
        website=domain,
        opportunity_score=72,
        overall_priority=PriorityTier.QUALIFIED
    )
    repo.save_lead(lead)

    found = repo.find_by_domain(domain)
    assert found is not None
    assert found.website == domain

    # Update opportunity score
    found.opportunity_score = 90
    found.overall_priority = PriorityTier.HIGH_POTENTIAL
    repo.save_lead(found)

    updated = repo.find_by_domain(domain)
    assert updated.opportunity_score == 90
    assert updated.overall_priority == PriorityTier.HIGH_POTENTIAL

def test_list_leads_by_priority():
    repo = LeadRepository()
    leads = repo.list_leads(priority=PriorityTier.HIGH_POTENTIAL)
    assert isinstance(leads, list)
    for l in leads:
        assert l.overall_priority == PriorityTier.HIGH_POTENTIAL

