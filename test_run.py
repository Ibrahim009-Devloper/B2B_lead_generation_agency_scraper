from core.orchestrator import master_orchestrator
from api.exporter import lead_exporter

def log_evt(agent, msg):
    safe_msg = str(msg).encode("ascii", errors="replace").decode("ascii")
    print(f"[{agent}]: {safe_msg}", flush=True)

def test():
    print("Starting test campaign for 5 B2B lead generation agencies...", flush=True)
    res = master_orchestrator.run_campaign("B2B lead generation agencies", target_count=5, on_event=log_evt)
    leads = res["leads"]
    print(f"\n--- CAMPAIGN SUMMARY ---")
    print(f"Total Discovered: {res.get('total_discovered', 0)}")
    print(f"Qualified Leads: {len(leads)}")
    for l in leads:
        print(f"  * Company: {l.business_name} ({l.website})")
        print(f"    Email: {l.verified_email} ({l.email_type})")
        print(f"    Decision Maker: {l.decision_maker_name} ({l.decision_maker_role})")
        print(f"    Status: {l.target_verification_status}")
        print(f"    Cold Email Sample (first 100 chars): {l.outreach_draft[:100] if l.outreach_draft else 'None'}...")
    
    xlsx_path = lead_exporter.export_to_xlsx(res["all_records"], "exports/test_leads.xlsx", total_discovered=res["total_discovered"])
    print(f"\nSuccessfully generated 5-sheet Excel at: {xlsx_path}")

if __name__ == "__main__":
    test()
