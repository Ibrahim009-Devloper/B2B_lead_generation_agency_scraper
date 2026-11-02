import os
import sys
import pandas as pd
from uuid import uuid4

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

from pipeline.normalizer import normalize_domain
from core.schemas import LeadRecord, AgencyType, PriorityTier, LeadClassification, VerificationStatus, EmailType
from adapters.website_enrichment import WebsiteEnrichmentAgent
from pipeline.verifier import LeadVerifier
from pipeline.scorer import ScrapingBuyerScorer
from pipeline.outreach_agent import OutreachAgent
from api.exporter import LeadExporter
from core.database import LeadRepository

def run_tests():
    print("=" * 60)
    print("RUNNING RIGOROUS TEST SUITE FOR ALL 6 PRODUCTION BUGS")
    print("=" * 60)

    # ---------------------------------------------------------
    # BUG 3: Strict Domain-Match & Junk/Placeholder Email Filtering
    # ---------------------------------------------------------
    print("\n[Testing Bug 3]: Strict Domain-Match & Junk Email Filtering...")
    enricher = WebsiteEnrichmentAgent()

    test_cases_bug3 = [
        # (text, target_url, should_extract, reason)
        ("Contact us at support@graph8.com or hello@cience.com", "https://cience.com", "hello@cience.com", "Drop graph8.com third-party widget email"),
        ("Reach out to jane@company.com or sales@callboxinc.com", "https://callboxinc.com", "sales@callboxinc.com", "Drop jane@company.com placeholder"),
        ("Send CV to recruitment@belkins.io or partnership@belkins.io", "https://belkins.io", "partnership@belkins.io", "Drop recruitment@ HR email"),
        ("Email info@sopro.io or careers@sopro.io", "https://sopro.io", "info@sopro.io", "Drop careers@ prefix"),
        ("Contact test@example.com or admin@domain.com", "https://myagency.com", None, "Placeholder domains must return empty list"),
    ]

    for raw_text, url, expected_extracted, desc in test_cases_bug3:
        extracted = enricher.extract_emails(raw_text, target_url=url)
        if expected_extracted:
            assert expected_extracted in extracted, f"Failed Bug 3 ({desc}): Expected {expected_extracted} in {extracted}"
            # Also ensure junk is NOT in extracted
            for junk in ["support@graph8.com", "jane@company.com", "recruitment@belkins.io", "careers@sopro.io", "test@example.com", "admin@domain.com"]:
                assert junk not in extracted, f"Failed Bug 3 ({desc}): Found junk {junk} in {extracted}"
        else:
            assert len(extracted) == 0, f"Failed Bug 3 ({desc}): Expected 0 emails, got {extracted}"
    print(">>> Bug 3 PASSED! Junk emails, placeholders, HR prefixes, and third-party widgets are strictly filtered.")

    # ---------------------------------------------------------
    # BUG 4: Email Category Classification & Promotion of Generic Emails
    # ---------------------------------------------------------
    print("\n[Testing Bug 4]: Email Category Classification & Promoting Generic Emails to Hot Leads...")
    scorer = ScrapingBuyerScorer()

    lead_generic = LeadRecord(
        business_name="Martal Group",
        agency_type=AgencyType.B2B_LEAD_GEN,
        website="martal.ca",
        email="info@martal.ca",
        verified_email="info@martal.ca",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        is_agency_verified=True,
        company_size="10-50",
        buying_intent_score=20,
        data_dependency_score=20
    )
    scored_lead = scorer.score_lead(lead_generic)
    assert scored_lead.overall_priority == PriorityTier.HOT_LEAD, f"Failed Bug 4: Generic email lead should be HOT_LEAD, got {scored_lead.overall_priority}"
    assert scored_lead.lead_classification == LeadClassification.HOT_LEAD, f"Failed Bug 4: Classification should be HOT_LEAD, got {scored_lead.lead_classification}"
    assert scored_lead.email_type == EmailType.GENERIC_BUSINESS, f"Failed Bug 4: EmailType should be GENERIC_BUSINESS, got {scored_lead.email_type}"

    # Check that personal email is classified as PERSONAL_PROFESSIONAL
    lead_owner = LeadRecord(
        business_name="Salaria Sales",
        agency_type=AgencyType.COLD_EMAIL,
        website="salariasales.com",
        email="nathan@salariasales.com",
        verified_email="nathan@salariasales.com",
        email_mx_status=VerificationStatus.LIKELY_VALID,
        is_agency_verified=True,
        decision_maker_name="Nathan",
        company_size="2-10",
        buying_intent_score=20,
        data_dependency_score=20
    )
    scored_owner = scorer.score_lead(lead_owner)
    assert scored_owner.overall_priority == PriorityTier.HOT_LEAD
    assert scored_owner.email_type == EmailType.PERSONAL_PROFESSIONAL, f"Failed Bug 4: Owner email should be PERSONAL_PROFESSIONAL, got {scored_owner.email_type}"
    print(">>> Bug 4 PASSED! Generic business emails with valid MX are classified correctly and promoted to Hot Leads.")

    # ---------------------------------------------------------
    # BUG 5: Anti-Hallucination Greeting in Cold Emails
    # ---------------------------------------------------------
    print("\n[Testing Bug 5]: Cold Email Greeting Anti-Hallucination Check...")
    outreach = OutreachAgent()

    # Lead with NO identified decision maker
    lead_no_dm = LeadRecord(
        business_name="CIENCE Technologies",
        agency_type=AgencyType.B2B_LEAD_GEN,
        website="cience.com",
        verified_email="sales@cience.com",
        decision_maker_name=None,
        decision_maker_role=None,
        core_services=["Outbound Lead Generation", "Cold Email Prospecting"],
        client_industries_served=["SaaS", "Enterprise Tech"]
    )
    lead_res_no_dm = outreach.generate_outreach(lead_no_dm)
    email_draft_no_dm = lead_res_no_dm.outreach_draft or ""
    print(f"Cold email generated (No DM):\n--- {email_draft_no_dm[:100]}... ---")
    assert not email_draft_no_dm.lower().startswith("hi founder"), f"Failed Bug 5: Should not start with 'Hi founder', got: {email_draft_no_dm[:30]}"
    assert not email_draft_no_dm.lower().startswith("hey eric"), f"Failed Bug 5: Should not start with hallucinated name 'Eric', got: {email_draft_no_dm[:30]}"
    assert (
        email_draft_no_dm.startswith("Hi CIENCE Technologies team,")
        or email_draft_no_dm.startswith("Hi CIENCE team,")
        or email_draft_no_dm.startswith("Hi there,")
    ), f"Failed Bug 5: Expected company team greeting, got: {email_draft_no_dm[:40]}"

    # Lead WITH identified decision maker
    lead_with_dm = LeadRecord(
        business_name="Belkins",
        agency_type=AgencyType.B2B_LEAD_GEN,
        website="belkins.io",
        verified_email="michael@belkins.io",
        decision_maker_name="Michael Maximoff",
        decision_maker_role="Managing Partner",
        core_services=["Appointment Setting", "Cold Outreach"],
        client_industries_served=["B2B Companies"]
    )
    lead_res_with_dm = outreach.generate_outreach(lead_with_dm)
    email_draft_with_dm = lead_res_with_dm.outreach_draft or ""
    print(f"Cold email generated (With DM):\n--- {email_draft_with_dm[:100]}... ---")
    assert email_draft_with_dm.startswith("Hi Michael,"), f"Failed Bug 5: Should start with 'Hi Michael,', got: {email_draft_with_dm[:30]}"
    print(">>> Bug 5 PASSED! Greetings are strictly grounded and never hallucinate names or use 'Hi founder'.")

    # ---------------------------------------------------------
    # BUG 2: Never Allow Empty Emails in 'Hot Leads' or AI Outreach
    # ---------------------------------------------------------
    print("\n[Testing Bug 2]: Empty Emails Never Enter Hot Leads or Outreach...")
    lead_empty_email = LeadRecord(
        business_name="SalesRoads",
        agency_type=AgencyType.B2B_LEAD_GEN,
        website="salesroads.com",
        email=None,
        verified_email=None,
        email_mx_status=VerificationStatus.UNKNOWN,
        is_agency_verified=True,
        company_size="10-50"
    )
    scored_empty = scorer.score_lead(lead_empty_email)
    assert scored_empty.overall_priority != PriorityTier.HOT_LEAD, f"Failed Bug 2: Empty email lead must not be HOT_LEAD, got {scored_empty.overall_priority}"
    assert scored_empty.lead_classification == LeadClassification.CONTACT_RESEARCH_REQUIRED, f"Failed Bug 2: Should be CONTACT_RESEARCH_REQUIRED, got {scored_empty.lead_classification}"

    # Outreach agent should immediately return without generating draft
    lead_outreach_test = outreach.generate_outreach(scored_empty)
    assert lead_outreach_test.outreach_draft is None, "Failed Bug 2: Outreach draft must remain None if verified_email is empty"
    print(">>> Bug 2 PASSED! Leads without deliverable emails never enter Hot Leads and never trigger outreach LLM.")

    # ---------------------------------------------------------
    # BUG 1 & BUG 6: Mutually Exclusive Routing & Rejected Status
    # ---------------------------------------------------------
    print("\n[Testing Bug 1 & 6]: Mutually Exclusive Routing & Rejection Status in Excel Export...")
    exporter = LeadExporter()
    test_xlsx_path = "exports/test_verification_leads.xlsx"

    # Create 4 test leads:
    # 1. Hot Lead with verified email
    l1 = LeadRecord(
        business_name="Leadle HQ",
        website="https://www.leadlehq.com/about",
        agency_type=AgencyType.B2B_LEAD_GEN,
        email="sales@leadlehq.com",
        verified_email="sales@leadlehq.com",
        email_type=EmailType.GENERIC_BUSINESS,
        email_mx_status=VerificationStatus.LIKELY_VALID,
        overall_priority=PriorityTier.HOT_LEAD,
        lead_classification=LeadClassification.HOT_LEAD,
        target_verification_status="VERIFIED_TARGET (B2B Lead Gen Agency)",
        outreach_draft="Hi Leadle HQ team,\n\nI noticed your lead generation work...",
        total_score=90
    )

    # 2. Duplicate of l1 (simulating cross-sheet bug)
    l1_dup = LeadRecord(
        business_name="Leadle HQ Dup",
        website="leadlehq.com",
        agency_type=AgencyType.B2B_LEAD_GEN,
        email="sales@leadlehq.com",
        verified_email="sales@leadlehq.com",
        overall_priority=PriorityTier.HOT_LEAD,
        lead_classification=LeadClassification.CONTACT_RESEARCH_REQUIRED,
        total_score=85
    )

    # 3. Contact Research Required (No email)
    l2 = LeadRecord(
        business_name="No Email Agency",
        website="noemailagency.com",
        agency_type=AgencyType.B2B_LEAD_GEN,
        email=None,
        verified_email=None,
        email_mx_status=VerificationStatus.UNKNOWN,
        overall_priority=PriorityTier.NEEDS_REVIEW,
        lead_classification=LeadClassification.CONTACT_RESEARCH_REQUIRED,
        target_verification_status="VERIFIED_TARGET (B2B Lead Gen Agency)",
        total_score=60
    )

    # 4. Rejected Lead
    l3 = LeadRecord(
        business_name="Local Dental Clinic",
        website="localdentalclinic.com",
        agency_type=AgencyType.NON_ICP,
        email="reception@localdentalclinic.com",
        overall_priority=PriorityTier.REJECTED,
        lead_classification=LeadClassification.REJECTED,
        rejection_reason="Local service business / Non-ICP",
        total_score=10
    )

    exporter.export_to_xlsx([l1, l1_dup, l2, l3], test_xlsx_path, total_discovered=10)

    # Inspect the generated excel
    excel_file = pd.ExcelFile(test_xlsx_path)
    sheet_names = excel_file.sheet_names
    print(f"Exported sheets: {sheet_names}")
    assert set(sheet_names) == {"Hot Leads", "LinkedIn Outreach Candidates", "Contact Research Required", "Rejected Leads", "Audit Summary"}

    df_hot = pd.read_excel(excel_file, sheet_name="Hot Leads")
    df_research = pd.read_excel(excel_file, sheet_name="Contact Research Required")
    df_rejected = pd.read_excel(excel_file, sheet_name="Rejected Leads")
    df_audit = pd.read_excel(excel_file, sheet_name="Audit Summary")

    # Bug 1 Check: Mutually Exclusive Routing across sheets
    hot_domains = set(df_hot["Website Domain"].dropna()) if not df_hot.empty else set()
    research_domains = set(df_research["Website Domain"].dropna()) if not df_research.empty else set()
    rejected_domains = set(df_rejected["Website Domain"].dropna()) if not df_rejected.empty else set()

    overlap_hot_research = hot_domains.intersection(research_domains)
    overlap_hot_rejected = hot_domains.intersection(rejected_domains)
    overlap_research_rejected = research_domains.intersection(rejected_domains)

    assert len(overlap_hot_research) == 0, f"Failed Bug 1: Domain overlap between Hot Leads and Research: {overlap_hot_research}"
    assert len(overlap_hot_rejected) == 0, f"Failed Bug 1: Domain overlap between Hot Leads and Rejected: {overlap_hot_rejected}"
    assert len(overlap_research_rejected) == 0, f"Failed Bug 1: Domain overlap between Research and Rejected: {overlap_research_rejected}"
    print(">>> Bug 1 (Sheet Routing) PASSED! Zero domain overlap across workbook sheets (1 company = 1 row).")

    # Bug 1 Check: Audit summary calculates duplicates removed
    audit_dict = dict(zip(df_audit["Audit Metric"], df_audit["Value"]))
    duplicates_removed_val = int(audit_dict.get("Duplicate Records Removed", 0))
    print(f"Audit Summary 'Duplicate Records Removed': {duplicates_removed_val}")
    assert duplicates_removed_val > 0, f"Failed Bug 1: Duplicate Records Removed should be > 0, got {duplicates_removed_val}"
    print(">>> Bug 1 (Audit Summary Duplicates Counter) PASSED!")

    # Bug 2 Check in Excel: No NaN/empty emails in Hot Leads
    if not df_hot.empty:
        for idx, row in df_hot.iterrows():
            email_val = str(row["Primary Verified Email"]).strip()
            assert email_val and email_val.lower() not in ["nan", "none", ""], f"Failed Bug 2: Found empty email in Hot Leads sheet: {row}"
            assert "@" in email_val, f"Failed Bug 2: Invalid email string in Hot Leads: {email_val}"
    print(">>> Bug 2 (Excel Hot Leads Email check) PASSED! All Hot Leads have valid emails.")

    # Bug 4 Check in Excel: Email Category never 'Unknown email type'
    if not df_hot.empty:
        for idx, row in df_hot.iterrows():
            cat = str(row["Email Category"]).strip()
            assert cat in ["Generic Business Email", "Owner / Personal Email"], f"Failed Bug 4: Invalid Email Category '{cat}' in row: {row}"
            assert "unknown" not in cat.lower(), f"Failed Bug 4: Found 'unknown' in Email Category: '{cat}'"
    print(">>> Bug 4 (Excel Email Category check) PASSED! Category is clean and explicit.")

    # Bug 6 Check in Excel: Rejected Leads verification status MUST say REJECTED
    assert not df_rejected.empty, "Failed Bug 6: Rejected leads sheet should have entries"
    for idx, row in df_rejected.iterrows():
        v_status = str(row["Verification Status"]).strip()
        assert v_status.startswith("REJECTED"), f"Failed Bug 6: Verification Status in Rejected Leads must start with 'REJECTED', got '{v_status}'"
        assert "VERIFIED_TARGET" not in v_status, f"Failed Bug 6: Found VERIFIED_TARGET in Rejected Leads sheet: '{v_status}'"
    print(">>> Bug 6 (Excel Rejected Leads Status check) PASSED! Status correctly starts with 'REJECTED'.")

    print("\n" + "=" * 60)
    print("ALL 6 PRODUCTION BUG TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()