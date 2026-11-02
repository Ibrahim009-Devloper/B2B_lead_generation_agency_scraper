import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import settings
from core.schemas import PriorityTier
from core.database import LeadRepository
from core.orchestrator import master_orchestrator
from api.exporter import lead_exporter

def run_daily_swarm(target_hot_leads: int = 250):
    print("=" * 80)
    print(f"  >>> AUTONOMOUS LEAD PULSE SWARM: TARGETING {target_hot_leads} VERIFIED HOT LEADS <<<")
    print("=" * 80)
    print(f"Start Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Groq API Keys Pool: {len(settings.get_groq_keys())} keys active")
    print(f"Gemini API Keys Pool: {len(settings.get_gemini_keys())} keys active")

    repo = LeadRepository()
    
    # Diversified high-intent search footprints covering major B2B agency markets
    campaign_prompts = [
        "B2B lead generation and appointment setting agencies California",
        "Outbound cold email marketing agencies New York",
        "B2B cold outreach and sales development agencies Texas",
        "Local SEO citation and lead generation agencies Florida",
        "B2B tech prospecting and pipeline generation agencies Chicago",
        "Outsourced SDR and sales lead generation agencies nationwide",
        "Cold email outbound agencies for SaaS Los Angeles",
        "B2B recruiting and talent research agencies San Francisco",
        "Digital marketing and directory tracking agencies Atlanta",
        "B2B appointment setting companies Boston and Austin"
    ]

    total_hot_leads = []
    start_total_time = time.time()

    for idx, prompt in enumerate(campaign_prompts, 1):
        if len(total_hot_leads) >= target_hot_leads:
            print(f"\n[GOAL REACHED]: Successfully gathered {len(total_hot_leads)} Verified Hot Leads!")
            break

        remaining = target_hot_leads - len(total_hot_leads)
        batch_limit = min(25, remaining)

        print(f"\n[{idx}/{len(campaign_prompts)}] Running Swarm Batch: '{prompt}' (Target: {batch_limit} leads)...")
        try:
            res = master_orchestrator.run_campaign(prompt, target_count=batch_limit)
            leads = res.get("leads", [])
            hot = [l for l in leads if l.overall_priority == PriorityTier.HOT_LEAD]
            total_hot_leads.extend(hot)
            print(f" -> Batch Processed: {len(leads)} leads | Hot Leads Qualified: {len(hot)} (Total So Far: {len(total_hot_leads)}/{target_hot_leads})")

            # Progressive export after each batch
            all_current_hot = repo.list_leads(priority=PriorityTier.HOT_LEAD, limit=500)
            export_csv = ROOT_DIR / "exports" / "daily_hot_leads.csv"
            export_xlsx = ROOT_DIR / "exports" / "daily_hot_leads.xlsx"
            lead_exporter.export_to_csv(all_current_hot, str(export_csv))
            lead_exporter.export_to_xlsx(all_current_hot, str(export_xlsx))

        except Exception as e:
            print(f" -> Batch warning: {e}. Rotating to next search footprint...")
            continue

    total_time = time.time() - start_total_time
    print("\n" + "=" * 80)
    print("  >>> DAILY SWARM SUMMARY <<<")
    print("=" * 80)
    print(f"Total Execution Time: {total_time:.2f}s ({total_time / 60:.1f} minutes)")
    print(f"Total Verified Hot Leads in Database: {len(repo.list_leads(priority=PriorityTier.HOT_LEAD, limit=1000))}")
    print(f"Exports saved to:\n  - CSV: {ROOT_DIR / 'exports' / 'daily_hot_leads.csv'}\n  - XLSX: {ROOT_DIR / 'exports' / 'daily_hot_leads.xlsx'}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=250, help="Target number of verified hot leads")
    args = parser.parse_args()
    run_daily_swarm(target_hot_leads=args.target)

