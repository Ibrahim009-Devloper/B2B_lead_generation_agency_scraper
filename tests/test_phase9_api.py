import os
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from api.main import app
from core.database import LeadRepository
from core.schemas import LeadRecord, AgencyType, PriorityTier, OutreachStatus
from api.exporter import lead_exporter

client = TestClient(app)

def test_api_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"

def test_api_leads_and_approval():
    repo = LeadRepository()
    lead_id = uuid4()
    lead = LeadRecord(
        lead_id=lead_id,
        business_name="Pipeline Pro Agency",
        agency_type=AgencyType.COLD_EMAIL,
        client_industries_served=["B2B SaaS"],
        website="pipelinepro.io",
        opportunity_score=85,
        overall_priority=PriorityTier.HIGH_POTENTIAL,
        recommended_scraping_pitch="Custom scraper for software directories"
    )
    repo.save_lead(lead)

    # 1. Fetch lead
    res = client.get(f"/api/leads/{lead_id}")
    assert res.status_code == 200
    assert res.json()["business_name"] == "Pipeline Pro Agency"

    # 2. Approve draft
    res_appr = client.post(f"/api/leads/{lead_id}/approve")
    assert res_appr.status_code == 200
    assert res_appr.json()["status"] == "approved"

    # Verify updated status
    updated = repo.get_lead_by_id(lead_id)
    assert updated.outreach_status == OutreachStatus.APPROVED

def test_api_rejection_feedback():
    repo = LeadRepository()
    lead_id = uuid4()
    lead = LeadRecord(
        lead_id=lead_id,
        business_name="Local Pizza Shop",
        agency_type=AgencyType.NON_ICP,
        website="pizzashop.com",
        overall_priority=PriorityTier.NEEDS_REVIEW
    )
    repo.save_lead(lead)

    # Reject with feedback
    res = client.post(
        f"/api/leads/{lead_id}/reject",
        json={"reason": "B2C Restaurant, not an agency", "mistake_rule": "Never classify restaurants as agencies"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    updated = repo.get_lead_by_id(lead_id)
    assert updated.overall_priority == PriorityTier.REJECTED

def test_exporter_csv_and_xlsx(tmp_path):
    repo = LeadRepository()
    leads = [
        LeadRecord(
            business_name="Growth Engine",
            agency_type=AgencyType.B2B_LEAD_GEN,
            client_industries_served=["Fintech"],
            opportunity_score=88,
            overall_priority=PriorityTier.HIGH_POTENTIAL
        )
    ]
    csv_file = tmp_path / "test_leads.csv"
    xlsx_file = tmp_path / "test_leads.xlsx"

    lead_exporter.export_to_csv(leads, str(csv_file))
    lead_exporter.export_to_xlsx(leads, str(xlsx_file))

    assert os.path.exists(csv_file)
    assert os.path.getsize(csv_file) > 50

    assert os.path.exists(xlsx_file)
    assert os.path.getsize(xlsx_file) > 100

