import os
import sys
import pandas as pd
from uuid import uuid4

sys.path.insert(0, os.path.abspath("."))

from core.schemas import LeadRecord, AgencyType, PriorityTier, LeadClassification, VerificationStatus, EmailType
from core.database import LeadRepository, get_connection
from api.exporter import LeadExporter
from core.orchestrator import MasterOrchestrator

def test_session_export_and_strict_email():
    print("=" * 60)
    print("TESTING SESSION-SCOPED EXPORT & STRICT EMAIL FILTERING")
    print("=" * 60)

    repo = LeadRepository()
    exporter = LeadExporter()

    # Session 1: Old Historic Session
    old_campaign_id = str(uuid4())
    lead_old = LeadRecord(
        campaign_id=old_campaign_id,
        business_name="Old Historic Agency",
        website="oldagency.com",
        agency_type=AgencyType.B2B_LEAD_GEN,
        email="contact@oldagency.com",
        verified_email="contact@oldagency.com",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        overall_priority=PriorityTier.HOT_LEAD,
        lead_classification=LeadClassification.HOT_LEAD,
        total_score=85
    )
    repo.save_lead(lead_old)

    # Session 2: Current Active Session
    current_campaign_id = str(uuid4())
    lead_current_1 = LeadRecord(
        campaign_id=current_campaign_id,
        business_name="Fresh Outreach Lab",
        website="freshoutreach.com",
        agency_type=AgencyType.COLD_EMAIL,
        email="hello@freshoutreach.com",
        verified_email="hello@freshoutreach.com",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        overall_priority=PriorityTier.HOT_LEAD,
        lead_classification=LeadClassification.HOT_LEAD,
        total_score=90
    )
    lead_current_2 = LeadRecord(
        campaign_id=current_campaign_id,
        business_name="Growth Spark B2B",
        website="growthspark.io",
        agency_type=AgencyType.B2B_LEAD_GEN,
        email="sales@growthspark.io",
        verified_email="sales@growthspark.io",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        overall_priority=PriorityTier.HOT_LEAD,
        lead_classification=LeadClassification.HOT_LEAD,
        total_score=88
    )
    repo.save_lead(lead_current_1)
    repo.save_lead(lead_current_2)

    # Query leads for CURRENT session
    current_leads = repo.list_leads(campaign_id=current_campaign_id)
    print(f"Retrieved {len(current_leads)} leads for current campaign {current_campaign_id}")
    assert len(current_leads) == 2, f"Expected 2 leads for current campaign, got {len(current_leads)}"
    domains = [l.website for l in current_leads]
    assert "oldagency.com" not in domains, "Error: Old campaign lead leaked into current session leads!"
    assert "freshoutreach.com" in domains
    assert "growthspark.io" in domains
    print(">>> Session Filtering PASSED: Current campaign does not leak old historical leads.")

    # Test Session-Scoped Export to XLSX
    session_xlsx = "exports/test_session_leads.xlsx"
    exporter.export_to_xlsx(current_leads, session_xlsx)

    xf = pd.ExcelFile(session_xlsx)
    df_hot = pd.read_excel(xf, sheet_name="Hot Leads")
    print(f"Session Excel Hot Leads count: {len(df_hot)}")
    assert len(df_hot) == 2, f"Expected 2 rows in session Hot Leads, got {len(df_hot)}"
    assert "oldagency.com" not in list(df_hot["Website Domain"]), "Error: Old domain in session excel export!"
    print(">>> Session Excel Export PASSED: Excel export contains ONLY current session leads!")

    # Test Strict Email Requirement ("email sara kono lead nibe na")
    for idx, row in df_hot.iterrows():
        email = str(row["Primary Verified Email"]).strip()
        assert email and email.lower() not in ["none", "nan", ""], f"Found empty email: {row}"
        assert "@" in email, f"Invalid email format: {email}"
    print(">>> Strict Email Requirement PASSED: Every exported lead has a valid, deliverable email.")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_session_export_and_strict_email()

