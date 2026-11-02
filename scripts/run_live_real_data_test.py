import os
import sys
import time
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

# Ensure root directory in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import settings
from core.schemas import LeadRecord, AgencyType, PriorityTier, VerificationStatus, OutreachStatus
from core.database import LeadRepository, get_connection
from core.llm_router import llm_router, TaskType
from adapters.search_api_adapter import SearchApiAdapter
from adapters.directory_adapter import DirectoryAdapter
from adapters.linkedin_xray_adapter import LinkedInXRayAdapter
from adapters.job_board_adapter import JobBoardAdapter
from adapters.website_enrichment import WebsiteEnrichmentAgent
from pipeline.verifier import LeadVerifier
from pipeline.scorer import ScrapingBuyerScorerV2
from pipeline.outreach_agent import OutreachAgent
from core.orchestrator import master_orchestrator
from api.exporter import lead_exporter

def log_section(title: str):
    print("\n" + "=" * 80)
    print(f"  >>> {title.upper()} <<<")
    print("=" * 80 + "\n")

def main():
    start_total_time = time.time()
    results_summary = {}
    issues_found = []

    print(f"Starting Complete Live Real-Data Test at {datetime.now(timezone.utc).isoformat()}")
    print(f"Working Directory: {ROOT_DIR}")
    print(f"Configured Groq Keys: {len(settings.get_groq_keys())}")
    print(f"Configured Gemini Keys: {len(settings.get_gemini_keys())}")

    # =========================================================================
    # TEST 1: LIVE MULTI-SOURCE DISCOVERY & RECON
    # =========================================================================
    log_section("Test 1: Live Multi-Source Recon & Discovery")
    t1_start = time.time()
    try:
        search_adapter = SearchApiAdapter()
        dir_adapter = DirectoryAdapter()
        xray_adapter = LinkedInXRayAdapter()
        job_adapter = JobBoardAdapter()

        print("[1.1] Testing SearchApiAdapter with live query...")
        q_search = "b2b lead generation agency california"
        cands_search = search_adapter.search(q_search, limit=4)
        print(f" -> Found {len(cands_search)} candidates from SearchApiAdapter")
        for i, c in enumerate(cands_search[:2], 1):
            print(f"    {i}. {c.business_name} | {c.website} | Source: {c.source_name}")

        print("\n[1.2] Testing DirectoryAdapter (Clutch / GoodFirms)...")
        q_dir = "site:clutch.co/agencies/lead-generation California"
        cands_dir = dir_adapter.search(q_dir, limit=4)
        print(f" -> Found {len(cands_dir)} candidates from DirectoryAdapter")
        for i, c in enumerate(cands_dir[:2], 1):
            print(f"    {i}. {c.business_name} | {c.website} | Source: {c.source_name}")

        print("\n[1.3] Testing LinkedInXRayAdapter (Google Dork)...")
        q_xray = "site:linkedin.com/company 'b2b lead generation' 'California'"
        cands_xray = xray_adapter.search(q_xray, limit=4)
        print(f" -> Found {len(cands_xray)} candidates from LinkedInXRayAdapter")
        for i, c in enumerate(cands_xray[:2], 1):
            print(f"    {i}. {c.business_name} | {c.website} | Source: {c.source_name}")

        print("\n[1.4] Testing JobBoardAdapter (Hiring Signal)...")
        q_job = "lead generation specialist hiring California"
        cands_job = job_adapter.search(q_job, limit=4)
        print(f" -> Found {len(cands_job)} candidates from JobBoardAdapter")
        for i, c in enumerate(cands_job[:2], 1):
            print(f"    {i}. {c.business_name} | {c.website} | Source: {c.source_name}")

        total_discovered = len(cands_search) + len(cands_dir) + len(cands_xray) + len(cands_job)
        if total_discovered == 0:
            issues_found.append("Test 1: Zero candidates discovered across all 4 adapters.")
        else:
            print(f"\n[Test 1 Passed]: Total {total_discovered} candidates discovered in {time.time()-t1_start:.2f}s")
        results_summary["Test 1: Discovery"] = f"SUCCESS ({total_discovered} candidates)"

    except Exception as e:
        err = f"Test 1 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 1: Discovery"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 2: LIVE HARVESTER & ZERO-TOKEN PRE-FILTERING
    # =========================================================================
    log_section("Test 2: Live Browserless Harvester & Zero-Token Pre-filtering")
    t2_start = time.time()
    try:
        enricher = WebsiteEnrichmentAgent()

        # Test 2.1: Real B2B Agency Website HTML fetch & compression
        test_agency_url = "https://belkins.io"
        print(f"[2.1] Fetching live agency website: {test_agency_url} via curl_cffi / httpx...")
        html_agency = enricher.fetch_html(test_agency_url)
        print(f" -> Raw HTML fetched: {len(html_agency)} bytes")

        if len(html_agency) < 100:
            print(" -> Notice: Website returned minimal HTML, trying fallback clever agency site...")
            test_agency_url = "https://cleverly.co"
            html_agency = enricher.fetch_html(test_agency_url)
            print(f" -> Alternate Raw HTML: {len(html_agency)} bytes")

        # HTML Compression
        compressed_text = enricher.compress_html_payload(html_agency)
        compression_ratio = (1 - (len(compressed_text) / max(1, len(html_agency)))) * 100
        print(f" -> Compressed payload size: {len(compressed_text)} chars")
        print(f" -> Token Compression Ratio: {compression_ratio:.1f}% reduction")
        print(f" -> Sample compressed text: {compressed_text[:180]}...")

        # Zero-Token Pre-filter check on Agency
        agency_passed = enricher.zero_token_prefilter(compressed_text)
        print(f" -> Zero-token prefilter result for B2B Agency: {agency_passed} (Expected: True)")
        if not agency_passed:
            issues_found.append(f"Test 2: Agency website {test_agency_url} failed zero-token prefilter")

        # Test 2.2: Negative Control (Irrelevant non-agency page)
        print("\n[2.2] Testing negative control: Non-agency local medical / dental clinic text...")
        non_agency_html = "<html><body><h1>Sunset Family Dental Clinic</h1><p>We provide teeth whitening, dental implants, root canal cleaning, and braces for kids.</p></body></html>"
        non_agency_text = enricher.compress_html_payload(non_agency_html)
        non_agency_passed = enricher.zero_token_prefilter(non_agency_text)
        print(f" -> Zero-token prefilter result for Dental Clinic: {non_agency_passed} (Expected: False - Dropped with 0 tokens)")
        if non_agency_passed:
            issues_found.append("Test 2: Non-agency page passed zero-token prefilter erroneously")

        results_summary["Test 2: Harvester & Zero-Token Pre-filtering"] = "SUCCESS"
        print(f"\n[Test 2 Passed] Completed in {time.time()-t2_start:.2f}s")

    except Exception as e:
        err = f"Test 2 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 2: Harvester & Zero-Token Pre-filtering"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 3: LIVE LLM ROUTING & MULTI-KEY POOL ROTATION
    # =========================================================================
    log_section("Test 3: Live LLM Routing & Multi-Key Pool Rotation")
    t3_start = time.time()
    try:
        from adapters.website_enrichment import WebsiteEnrichmentResult

        sample_enrichment_prompt = (
            "Agency Text:\n"
            "Cleverly is a B2B lead generation and cold email outreach agency. "
            "We build custom verified prospect lists, set appointments, and run outbound cold email for SaaS and Tech companies. "
            "Founded by Michael Lin, CEO. Contact us at sales@cleverly.co or direct to mlin@cleverly.co. "
            "We handle large scale automated outbound pipelines."
        )

        print("[3.1] Testing live Groq Pool key rotation & JSON extraction...")
        groq_key1 = llm_router.groq_pool.get_next_key()
        groq_key2 = llm_router.groq_pool.get_next_key()
        print(f" -> Groq Key #1 index active: {groq_key1[:12]}...")
        print(f" -> Groq Key #2 index active: {groq_key2[:12]}...")

        res_groq = llm_router._call_groq(
            prompt=sample_enrichment_prompt,
            system_prompt="Extract structured agency intelligence from website text in json format.",
            schema=WebsiteEnrichmentResult
        )
        groq_data: WebsiteEnrichmentResult = res_groq["data"]
        print(f" -> Groq Output: Agency Type={groq_data.agency_type}, Decision Maker={groq_data.decision_maker_name} ({groq_data.decision_maker_role})")
        print(f" -> Groq Services: {groq_data.core_services}")
        print(f" -> Groq Latency: {res_groq.get('latency_ms', 0):.0f}ms | Provider: {res_groq.get('provider')}")

        print("\n[3.2] Testing live Gemini Pool with gemini-2.5-flash...")
        res_gemini = llm_router._call_gemini(
            prompt=sample_enrichment_prompt,
            system_prompt="Extract structured agency intelligence from website text in json format.",
            schema=WebsiteEnrichmentResult
        )
        gemini_data: WebsiteEnrichmentResult = res_gemini["data"]
        print(f" -> Gemini Output: Agency Type={gemini_data.agency_type}, Decision Maker={gemini_data.decision_maker_name}")
        print(f" -> Gemini Services: {gemini_data.core_services}")
        print(f" -> Gemini Latency: {res_gemini.get('latency_ms', 0):.0f}ms | Provider: {res_gemini.get('provider')}")

        print("\n[3.3] Testing unified router matrix (TaskType.FAST_CLASSIFICATION & TaskType.WEBSITE_PARSING)...")
        res_route = llm_router.route(
            task=TaskType.FAST_CLASSIFICATION,
            prompt="Classify if this agency buys scraping: 'We build cold email lists for clients.'",
            system_prompt="Classify agency type in json."
        )
        print(f" -> Router Matrix Provider: {res_route.get('provider')}")

        results_summary["Test 3: LLM Multi-Key Pools"] = "SUCCESS (Groq + Gemini Live Verified)"
        print(f"\n[Test 3 Passed] Completed in {time.time()-t3_start:.2f}s")

    except Exception as e:
        err = f"Test 3 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 3: LLM Multi-Key Pools"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 4: LIVE DNS MX RESOLUTION & VERIFICATION AGENT
    # =========================================================================
    log_section("Test 4: Live DNS MX Resolution & Verification")
    t4_start = time.time()
    try:
        verifier = LeadVerifier()

        # 4.1 Real MX Check on live domains
        test_valid_domain = "google.com"
        test_bogus_domain = "nonexistent-domain-xyz-12345.biz"

        print(f"[4.1] Checking DNS MX records for real domain: {test_valid_domain}...")
        mx_status_valid = verifier.verify_email_mx(test_valid_domain)
        print(f" -> MX Status for {test_valid_domain}: {mx_status_valid} (Expected: likely_valid)")
        if mx_status_valid != VerificationStatus.LIKELY_VALID:
            issues_found.append(f"Test 4: Real domain {test_valid_domain} did not resolve to likely_valid")

        print(f"\n[4.2] Checking DNS MX records for bogus domain: {test_bogus_domain}...")
        mx_status_invalid = verifier.verify_email_mx(test_bogus_domain)
        print(f" -> MX Status for {test_bogus_domain}: {mx_status_invalid} (Expected: invalid)")
        if mx_status_invalid != VerificationStatus.INVALID:
            issues_found.append(f"Test 4: Bogus domain {test_bogus_domain} did not resolve to invalid")

        # 4.3 Email Classification: personal vs role inbox
        personal_check = verifier.is_personal_email("marcus.vance@agency.com")
        role_check = verifier.is_personal_email("info@agency.com")
        print(f"\n[4.3] Personal email check: marcus.vance@agency.com -> {personal_check} (Expected: True)")
        print(f"      Role email check: info@agency.com -> {role_check} (Expected: False)")

        results_summary["Test 4: Verification & MX"] = "SUCCESS"
        print(f"\n[Test 4 Passed] Completed in {time.time()-t4_start:.2f}s")

    except Exception as e:
        err = f"Test 4 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 4: Verification & MX"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 5: LIVE THE JUDGE (100-POINT SCORING MODEL V2)
    # =========================================================================
    log_section("Test 5: Live The Judge (100-Point Scoring Model V2)")
    t5_start = time.time()
    try:
        scorer = ScrapingBuyerScorerV2()

        # Hot Lead Candidate
        lead_hot = LeadRecord(
            business_name="SignalFlow Outbound Agency",
            agency_type=AgencyType.COLD_EMAIL,
            client_industries_served=["B2B SaaS", "Fintech"],
            core_services=["Cold Email Outbound", "Custom Lead Scraping", "Appointment Setting"],
            data_dependency_signals=["Requires fresh prospect data continuously", "Scrapes niche directories"],
            scale_signals=["Automates high volume campaigns", "Hiring outbound data researchers"],
            website="signalflow.io",
            email="founder@signalflow.io",
            verified_email="founder@signalflow.io",
            email_mx_status=VerificationStatus.LIKELY_VALID,
            email_verification_status=VerificationStatus.LIKELY_VALID,
            decision_maker_name="Alex Mercer",
            decision_maker_role="CEO & Founder",
            decision_maker_linkedin="https://linkedin.com/in/alex-mercer",
            factual_confidence=0.88,
            evidence={
                "is_personal_email": True,
                "decision_maker_name": {"url": "https://signalflow.io/about", "snippet": "Founded by Alex Mercer"}
            }
        )

        scored_hot = scorer.score_lead(lead_hot)
        print(f"[5.1] Hot Lead Score: {scored_hot.opportunity_score}/100 | Priority: {scored_hot.overall_priority.value}")
        print(f" -> Data Dependency: {scored_hot.icp_fit_score}/30")
        print(f" -> Factual Confidence: {scored_hot.factual_confidence}")
        print(f" -> Explanations:")
        for exp in scored_hot.score_explanation:
            print(f"    * {exp}")

        if scored_hot.overall_priority != PriorityTier.HOT_LEAD or scored_hot.opportunity_score < 80:
            issues_found.append(f"Test 5: Scored hot lead got {scored_hot.opportunity_score} ({scored_hot.overall_priority.value}), expected >=80 Hot Lead")

        # Rejected Lead Candidate (Non-ICP)
        lead_rejected = LeadRecord(
            business_name="Austin Roofing & Repairs",
            agency_type=AgencyType.NON_ICP,
            website="austinroofingrepair.com"
        )
        scored_rej = scorer.score_lead(lead_rejected)
        print(f"\n[5.2] Non-ICP Lead Score: {scored_rej.opportunity_score}/100 | Priority: {scored_rej.overall_priority.value}")
        print(f" -> Rejection Reason: {scored_rej.rejection_reason}")
        if scored_rej.overall_priority != PriorityTier.REJECTED:
            issues_found.append("Test 5: Non-ICP lead was not Rejected")

        results_summary["Test 5: 100-Point Scoring Model"] = "SUCCESS"
        print(f"\n[Test 5 Passed] Completed in {time.time()-t5_start:.2f}s")

    except Exception as e:
        err = f"Test 5 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 5: 100-Point Scoring Model"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 6: LIVE OUTREACH ANGLE & CUSTOM HOOK AGENT
    # =========================================================================
    log_section("Test 6: Live Outreach Angle & Custom Hook Generation")
    t6_start = time.time()
    try:
        outreach = OutreachAgent()
        print(f"[6.1] Generating custom outreach pitch for: {scored_hot.business_name} via live LLM...")
        enriched_outreach = outreach.generate_outreach(scored_hot)

        print(f" -> Custom Outreach Hook: \"{enriched_outreach.custom_outreach_hook}\"")
        print(f" -> Recommended Scraping Pitch: \"{enriched_outreach.recommended_scraping_pitch}\"")
        print(f" -> Cold Outreach Draft:\n---\n{enriched_outreach.outreach_draft}\n---")

        word_count = len(enriched_outreach.outreach_draft.split())
        print(f" -> Draft Word Count: {word_count} words (Limit: <= 75 words)")
        has_http = "http://" in enriched_outreach.outreach_draft or "https://" in enriched_outreach.outreach_draft
        print(f" -> Contains Hyperlinks: {has_http} (Limit: False - Zero links)")

        if word_count > 75:
            issues_found.append(f"Test 6: Outreach draft exceeded 75 words ({word_count} words)")
        if has_http:
            issues_found.append("Test 6: Outreach draft contains hyperlinks")

        results_summary["Test 6: Outreach Angle Agent"] = "SUCCESS"
        print(f"\n[Test 6 Passed] Completed in {time.time()-t6_start:.2f}s")

    except Exception as e:
        err = f"Test 6 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 6: Outreach Angle Agent"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 7: LIVE 90-DAY COOLDOWN & PERSISTENT SQLITE MEMORY
    # =========================================================================
    log_section("Test 7: Live 90-Day Cooldown & SQLite Memory")
    t7_start = time.time()
    try:
        repo = LeadRepository()
        test_domain = f"agency-cooldown-live-{int(time.time())}.com"

        print(f"[7.1] Checking if new domain {test_domain} is in cooldown...")
        init_cooldown = repo.is_domain_in_cooldown(test_domain, cooldown_days=90)
        print(f" -> Initial cooldown status: {init_cooldown} (Expected: False)")

        print(f"[7.2] Recording {test_domain} to scraped_domains table...")
        repo.record_scraped_domain(test_domain, status="Hot Lead")

        print(f"[7.3] Re-checking cooldown for {test_domain}...")
        post_cooldown = repo.is_domain_in_cooldown(test_domain, cooldown_days=90)
        print(f" -> Post cooldown status: {post_cooldown} (Expected: True - Zero Token Burn)")

        if not post_cooldown:
            issues_found.append(f"Test 7: Domain {test_domain} did not register in 90-day cooldown")

        # Save the scored hot lead into DB
        repo.save_lead(enriched_outreach)
        retrieved_lead = repo.get_lead_by_id(enriched_outreach.lead_id)
        print(f"[7.4] Database persistence check: Retrieved lead '{retrieved_lead.business_name}' with ID {retrieved_lead.lead_id}")

        results_summary["Test 7: 90-Day Cooldown & SQLite Memory"] = "SUCCESS"
        print(f"\n[Test 7 Passed] Completed in {time.time()-t7_start:.2f}s")

    except Exception as e:
        err = f"Test 7 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 7: 90-Day Cooldown & SQLite Memory"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 8: LIVE END-TO-END CAMPAIGN ORCHESTRATION
    # =========================================================================
    log_section("Test 8: Live End-to-End Campaign Execution")
    t8_start = time.time()
    try:
        campaign_prompt = "Find B2B lead generation and cold email agencies in California"
        print(f"[8.1] Running complete live campaign for prompt: '{campaign_prompt}' (target_count=3)...")

        campaign_res = master_orchestrator.run_campaign(campaign_prompt, target_count=3)
        campaign_id = campaign_res["campaign_id"]
        leads_collected = campaign_res["leads"]
        metrics = campaign_res["metrics"]

        print(f" -> Campaign ID: {campaign_id}")
        print(f" -> Total Leads Collected & Processed: {len(leads_collected)}")
        print(f" -> Metrics: Qualified={metrics.get('qualified_count')}, Hot Leads={metrics.get('hot_leads_count', 0)}, Avg Score={metrics.get('average_opportunity_score', 0):.1f}")

        print("\n[8.2] Inspecting Real Live Leads Processed in Campaign:")
        for idx, l in enumerate(leads_collected[:3], 1):
            print(f"  --- Lead #{idx} ---")
            print(f"  Name: {l.business_name}")
            print(f"  Website: {l.website}")
            print(f"  Domain Hash: {l.domain_hash}")
            print(f"  Agency Type: {l.agency_type.value}")
            print(f"  Score: {l.opportunity_score} (Priority: {l.overall_priority.value})")
            print(f"  Decision Maker: {l.decision_maker_name or 'N/A'} ({l.decision_maker_role or 'N/A'})")
            print(f"  Verified Email: {l.verified_email or l.email or 'N/A'} (MX: {l.email_mx_status.value})")
            print(f"  Custom Hook: {l.custom_outreach_hook or 'N/A'}")
            if l.outreach_draft:
                print(f"  Outreach Draft Snippet: {l.outreach_draft[:100]}...")

        if len(leads_collected) == 0:
            issues_found.append("Test 8: Campaign returned zero processed leads.")

        results_summary["Test 8: End-to-End Campaign"] = f"SUCCESS ({len(leads_collected)} leads processed)"
        print(f"\n[Test 8 Passed] Completed in {time.time()-t8_start:.2f}s")

    except Exception as e:
        err = f"Test 8 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 8: End-to-End Campaign"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 9: LIVE CSV & EXCEL EXPORTS
    # =========================================================================
    log_section("Test 9: Live CSV & Excel Exports")
    t9_start = time.time()
    try:
        export_csv_path = str(ROOT_DIR / "exports" / "live_hot_leads.csv")
        export_xlsx_path = str(ROOT_DIR / "exports" / "live_hot_leads.xlsx")

        all_current_leads = repo.list_leads(limit=100)
        print(f"[9.1] Exporting {len(all_current_leads)} live leads from SQLite...")
        
        csv_file = lead_exporter.export_to_csv(all_current_leads, export_csv_path)
        xlsx_file = lead_exporter.export_to_xlsx(all_current_leads, export_xlsx_path)

        print(f" -> CSV Exported: {csv_file} (Size: {os.path.getsize(csv_file)} bytes)")
        print(f" -> XLSX Exported: {xlsx_file} (Size: {os.path.getsize(xlsx_file)} bytes)")

        # Verify CSV with Pandas
        df_csv = pd.read_csv(csv_file)
        print(f" -> DataFrame loaded: {len(df_csv)} rows, {len(df_csv.columns)} columns")
        print(f" -> Columns: {list(df_csv.columns)}")

        required_v2_cols = ["Domain Hash", "Data Dependency Score", "Scale Signals", "Custom Outreach Hook", "Last Scraped At"]
        missing_cols = [c for c in required_v2_cols if c not in df_csv.columns]
        if missing_cols:
            issues_found.append(f"Test 9: Export missing V2 columns: {missing_cols}")
        else:
            print(" -> All Version 2.0 export columns verified!")

        results_summary["Test 9: Exports (CSV & Excel)"] = "SUCCESS"
        print(f"\n[Test 9 Passed] Completed in {time.time()-t9_start:.2f}s")

    except Exception as e:
        err = f"Test 9 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 9: Exports (CSV & Excel)"] = f"FAILED: {e}"

    # =========================================================================
    # TEST 10: LIVE FASTAPI ENDPOINTS & FRONTEND SERVING
    # =========================================================================
    log_section("Test 10: Live FastAPI Endpoints & Frontend Serving")
    t10_start = time.time()
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)

        # 10.1 Root browser request
        print("[10.1] Testing GET / with browser Accept header...")
        r_root = client.get("/", headers={"Accept": "text/html"})
        print(f" -> Status: {r_root.status_code} | Content-Type: {r_root.headers.get('content-type')}")
        if "LEAD-PULSE 3D" not in r_root.text:
            issues_found.append("Test 10: GET / did not serve LEAD-PULSE 3D HTML dashboard")

        # 10.2 Dashboard route
        print("[10.2] Testing GET /dashboard...")
        r_dash = client.get("/dashboard")
        print(f" -> Status: {r_dash.status_code} | Has 3D Canvas: {'threejs-container' in r_dash.text}")

        # 10.3 API Status
        print("[10.3] Testing GET /api/status...")
        r_status = client.get("/api/status")
        print(f" -> Status: {r_status.status_code} | Body: {r_status.json()}")

        # 10.4 API Telemetry
        print("[10.4] Testing GET /api/telemetry...")
        r_telem = client.get("/api/telemetry")
        print(f" -> Status: {r_telem.status_code} | Body: {r_telem.json()}")

        # 10.5 API Leads listing
        print("[10.5] Testing GET /api/leads...")
        r_leads = client.get("/api/leads?limit=5")
        leads_json = r_leads.json()
        print(f" -> Status: {r_leads.status_code} | Returned: {len(leads_json)} leads")

        # 10.6 Lead approval
        if leads_json:
            target_id = leads_json[0]["lead_id"]
            print(f"[10.6] Testing POST /api/leads/{target_id}/approve...")
            r_appr = client.post(f"/api/leads/{target_id}/approve")
            print(f" -> Status: {r_appr.status_code} | Result: {r_appr.json()}")

        # 10.7 Feedback injection
        print("[10.7] Testing POST /api/feedback (Operator console rule)...")
        r_fb = client.post("/api/feedback", json={"rule": "Prioritize agencies handling outbound SDR pipelines."})
        print(f" -> Status: {r_fb.status_code} | Result: {r_fb.json()}")

        results_summary["Test 10: FastAPI & Frontend"] = "SUCCESS"
        print(f"\n[Test 10 Passed] Completed in {time.time()-t10_start:.2f}s")

    except Exception as e:
        err = f"Test 10 Failed with error: {e}"
        print(err)
        traceback.print_exc()
        issues_found.append(err)
        results_summary["Test 10: FastAPI & Frontend"] = f"FAILED: {e}"

    # =========================================================================
    # FINAL AUDIT SUMMARY & ISSUES REPORT
    # =========================================================================
    total_elapsed = time.time() - start_total_time
    log_section("Final Live Real-Data Audit Summary")
    print(f"Total Execution Time: {total_elapsed:.2f}s")
    print("\nResults by Module:")
    for test_name, res in results_summary.items():
        print(f"  - {test_name}: {res}")

    print("\n" + "-" * 50)
    if not issues_found:
        print(">>> ALL 10 LIVE REAL-DATA TESTS PASSED WITH 0 ISSUES! <<<")
        print("Data is accurate, verified, and functioning properly across the entire pipeline.")
    else:
        print(f">>> {len(issues_found)} ISSUES IDENTIFIED DURING LIVE RUN: <<<")
        for idx, iss in enumerate(issues_found, 1):
            print(f"  {idx}. {iss}")

    # Save full audit log to JSON
    audit_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_time_seconds": round(total_elapsed, 2),
        "results": results_summary,
        "issues_found": issues_found,
        "overall_status": "PASSED" if not issues_found else "NEEDS_ATTENTION"
    }
    audit_file = ROOT_DIR / "exports" / "live_real_data_audit.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit_log, f, indent=2)
    print(f"\nSaved detailed audit log to: {audit_file}")

if __name__ == "__main__":
    main()

