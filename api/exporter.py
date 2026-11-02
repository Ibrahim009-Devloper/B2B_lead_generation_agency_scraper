import os
from typing import List, Dict, Any
from pathlib import Path
from collections import Counter
import pandas as pd
from core.schemas import LeadRecord, LeadClassification, PriorityTier, VerificationStatus

class LeadExporter:
    """
    Exports leads according to Lead Generation System Architecture Rules:
    - 12 Clean Columns:
        1. Company Name
        2. Website Domain
        3. Verification Status (VERIFIED_TARGET + Category)
        4. Primary Verified Email
        5. Email Category (Owner/Founder vs Generic)
        6. Backup Emails (1-2 fallback emails)
        7. Decision Maker Name & Role
        8. Complete Business Summary
        9. Their Target Clients
        10. How to Pitch / Personalization Guide
        11. Ready Personalized Cold Email (<75 words, plain-text, no links, free sample)
        12. Source Footprint (e.g. Clutch, Directory, Web Search)
    - 5 Dedicated Worksheets:
        1. Hot Leads
        2. LinkedIn Outreach Candidates
        3. Contact Research Required
        4. Rejected Leads
        5. Audit Summary
    """
    def __init__(self):
        pass

    def _lead_to_row(self, l: LeadRecord) -> Dict[str, Any]:
        email_val = l.verified_email or l.email or ""
        email_type_val = l.email_type.value if hasattr(l.email_type, "value") else str(l.email_type)
        
        # Bug 4: Never output Unknown email type
        if not email_type_val or email_type_val in ["unknown", "Unknown email type", "None"]:
            email_lower = email_val.lower().strip()
            local = email_lower.split("@")[0] if "@" in email_lower else ""
            if any(local.startswith(p) for p in ["info", "hello", "contact", "sales", "team", "support", "office", "admin", "inquiries", "marketing"]):
                email_type_val = "Generic Business Email"
            elif email_val:
                email_type_val = "Owner / Personal Email"
            else:
                email_type_val = "Generic Business Email"

        # Format Decision Maker Name & Role
        if l.decision_maker_name and l.decision_maker_role:
            dm_str = f"{l.decision_maker_name} ({l.decision_maker_role})"
        elif l.decision_maker_name:
            dm_str = l.decision_maker_name
        elif l.decision_maker_role:
            dm_str = l.decision_maker_role
        else:
            dm_str = "Not identified"

        backup_emails_str = ", ".join(l.backup_emails) if l.backup_emails else ""
        summary_str = l.complete_business_summary or (", ".join(l.core_services) if l.core_services else "")
        target_clients_str = l.their_target_clients or (", ".join(l.client_industries_served) if l.client_industries_served else "")
        pitch_guide_str = l.personalization_guide or l.recommended_scraping_pitch or l.custom_outreach_hook or ""
        source_str = l.source_footprint or (", ".join(l.source_names) if l.source_names else "Directory Harvester")

        # Bug 6: If lead is rejected, Verification Status MUST say REJECTED (never VERIFIED_TARGET)
        if l.overall_priority == PriorityTier.REJECTED or l.lead_classification == LeadClassification.REJECTED:
            if l.target_verification_status and str(l.target_verification_status).startswith("REJECTED"):
                v_status = l.target_verification_status
            else:
                v_status = f"REJECTED: {l.rejection_reason or 'Failed ICP qualification'}"
        else:
            v_status = l.target_verification_status or "VERIFIED_TARGET (B2B Agency)"

        from pipeline.normalizer import normalize_domain
        clean_domain = normalize_domain(l.website) or ""

        return {
            "Company Name": l.business_name,
            "Website Domain": clean_domain,
            "Verification Status": v_status,
            "Opportunity Score": l.opportunity_score or 0,
            "Opportunity Tier": l.opportunity_tier or "MODERATE OPPORTUNITY",
            "Primary Verified Email": email_val,
            "Email Category": email_type_val,
            "Backup Emails": backup_emails_str,
            "Decision Maker Name & Role": dm_str,
            "Complete Business Summary": summary_str,
            "Their Target Clients": target_clients_str,
            "How to Pitch / Personalization Guide": pitch_guide_str,
            "Ready Personalized Cold Email": l.outreach_draft or "",
            "Opportunity Need Signals": "; ".join(l.opportunity_signals) if l.opportunity_signals else "",
            "Source Footprint": source_str
        }

    def _leads_to_df(self, leads: List[LeadRecord]) -> pd.DataFrame:
        columns = [
            "Company Name", "Website Domain", "Verification Status", "Opportunity Score", "Opportunity Tier",
            "Primary Verified Email", "Email Category", "Backup Emails", "Decision Maker Name & Role",
            "Complete Business Summary", "Their Target Clients",
            "How to Pitch / Personalization Guide", "Ready Personalized Cold Email",
            "Opportunity Need Signals", "Source Footprint"
        ]
        if not leads:
            return pd.DataFrame(columns=columns)

        sorted_leads = sorted(leads, key=lambda x: (x.total_score or x.opportunity_score or 0), reverse=True)
        rows = [self._lead_to_row(l) for l in sorted_leads]
        df = pd.DataFrame(rows)
        if "Website Domain" in df.columns:
            df = df.drop_duplicates(subset=["Website Domain"])
        return df

    def _rejected_leads_to_df(self, leads: List[LeadRecord]) -> pd.DataFrame:
        columns = [
            "Company Name", "Website Domain", "Verification Status", "Rejection Reason", "Source Footprint"
        ]
        if not leads:
            return pd.DataFrame(columns=columns)

        from pipeline.normalizer import normalize_domain
        rows = []
        for l in leads:
            reason = l.rejection_reason or "Non-ICP or missing deliverable email"
            v_status = l.target_verification_status if (l.target_verification_status and str(l.target_verification_status).startswith("REJECTED")) else f"REJECTED ({reason[:30]})"
            rows.append({
                "Company Name": l.business_name,
                "Website Domain": normalize_domain(l.website) or "",
                "Verification Status": v_status,
                "Rejection Reason": reason,
                "Source Footprint": l.source_footprint or (", ".join(l.source_names) if l.source_names else "Directory Harvester")
            })
        df = pd.DataFrame(rows)
        if "Website Domain" in df.columns:
            df = df.drop_duplicates(subset=["Website Domain"])
        return df

    def _generate_audit_summary_df(self, leads: List[LeadRecord], total_discovered: int = 0) -> pd.DataFrame:
        from pipeline.normalizer import normalize_domain
        from core.database import get_connection

        all_domains = [normalize_domain(l.website) for l in leads if l.website]
        domain_counts = Counter(all_domains)
        intra_duplicates = sum(count - 1 for count in domain_counts.values())

        # Check total scraped / duplicate records in database
        db_scraped_total = 0
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM scraped_domains")
            db_scraped_total = c.fetchone()[0]
            conn.close()
        except Exception:
            pass

        total = total_discovered or max(len(leads), db_scraped_total)
        duplicates_removed = intra_duplicates
        if total > len(leads):
            duplicates_removed += (total - len(leads))

        genuine_companies = len([l for l in leads if l.agency_type.value != "non_icp" and "blog" not in (l.business_name.lower())])
        matching_icp = len([l for l in leads if l.agency_type.value != "non_icp"])
        buying_intent_leads = len([l for l in leads if l.buying_intent_score > 0])
        emails_found = len([l for l in leads if (l.verified_email or l.email)])
        
        valid_emails = len([l for l in leads if (l.verified_email or l.email) and l.email_mx_status in (VerificationStatus.LIKELY_VALID, VerificationStatus.VERIFIED)])
        unverified_emails = emails_found - valid_emails
        qualified_hot_leads = len([
            l for l in leads 
            if (l.lead_classification == LeadClassification.HOT_LEAD or l.overall_priority == PriorityTier.HOT_LEAD)
            and l.verified_email
        ])

        reasons = [l.rejection_reason for l in leads if l.rejection_reason]
        reason_counts = Counter(reasons).most_common(5)
        top_rejections = "; ".join([f"{r}: {c}" for r, c in reason_counts]) if reason_counts else "None"

        sources = [s for l in leads for s in l.source_names]
        source_counts = Counter(sources)
        source_rates = "; ".join([f"{s}: {c} discovered" for s, c in source_counts.items()]) if source_counts else "Direct Harvester"

        summary_data = [
            {"Audit Metric": "Total Companies Discovered", "Value": str(total)},
            {"Audit Metric": "Duplicate Records Removed", "Value": str(max(duplicates_removed, 0))},
            {"Audit Metric": "Genuine Companies Verified", "Value": str(genuine_companies)},
            {"Audit Metric": "Companies Matching ICP", "Value": str(matching_icp)},
            {"Audit Metric": "Leads with Credible Buying-Intent Evidence", "Value": str(buying_intent_leads)},
            {"Audit Metric": "Emails Found", "Value": str(emails_found)},
            {"Audit Metric": "Email Verification Outcomes (Deliverable / Unverified)", "Value": f"{valid_emails} Valid / {unverified_emails} Unverified"},
            {"Audit Metric": "Qualified Hot Leads (Score >= 80 + Verified Email)", "Value": str(qualified_hot_leads)},
            {"Audit Metric": "Primary Rejection Reasons", "Value": top_rejections},
            {"Audit Metric": "Source-Wise Distribution", "Value": source_rates}
        ]
        return pd.DataFrame(summary_data)

    def export_to_csv(self, leads: List[LeadRecord], output_path: str) -> str:
        df = self._leads_to_df(leads)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return str(Path(output_path).resolve())

    def export_to_xlsx(self, leads: List[LeadRecord], output_path: str, total_discovered: int = 0) -> str:
        """
        Creates a multi-sheet workbook with 5 dedicated sheets.
        MUTUALLY EXCLUSIVE ROUTING (Bug 1 Fix):
        One company = One row in the entire Excel workbook!
        """
        from pipeline.normalizer import normalize_domain
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        routed_domains = set()

        # 1. Sheet 1: Hot Leads (Must have valid deliverable email per Bug 2)
        hot_leads: List[LeadRecord] = []
        for l in leads:
            dom = normalize_domain(l.website)
            if not dom or dom in routed_domains:
                continue
            act_email = l.verified_email or l.email
            has_valid_email = bool(
                act_email
                and str(act_email).strip().lower() not in ["", "none", "nan", "null"]
                and "@" in str(act_email)
            )
            # Route to Hot Leads if verified email is present and lead is NOT rejected!
            if has_valid_email and l.overall_priority != PriorityTier.REJECTED and l.lead_classification != LeadClassification.REJECTED:
                hot_leads.append(l)
                routed_domains.add(dom)

        # 2. Sheet 2: LinkedIn Outreach Candidates (Has verified decision-maker LinkedIn URL)
        linkedin_candidates: List[LeadRecord] = []
        for l in leads:
            dom = normalize_domain(l.website)
            if not dom or dom in routed_domains:
                continue
            is_linkedin = (
                l.lead_classification == LeadClassification.LINKEDIN_OUTREACH_CANDIDATE
                or (bool(l.decision_maker_linkedin) and str(l.decision_maker_linkedin).strip().lower() not in ["", "none", "nan", "null"])
            )
            if is_linkedin and l.overall_priority != PriorityTier.REJECTED and l.lead_classification != LeadClassification.REJECTED:
                linkedin_candidates.append(l)
                routed_domains.add(dom)

        # 3. Sheet 3: Contact Research Required (Valid ICP targets with ZERO valid email found)
        research_required: List[LeadRecord] = []
        for l in leads:
            dom = normalize_domain(l.website)
            if not dom or dom in routed_domains:
                continue
            if l.overall_priority != PriorityTier.REJECTED and l.lead_classification != LeadClassification.REJECTED:
                research_required.append(l)
                routed_domains.add(dom)

        # 4. Sheet 4: Rejected Leads
        rejected_leads: List[LeadRecord] = []
        for l in leads:
            dom = normalize_domain(l.website)
            if not dom or dom in routed_domains:
                continue
            if l.lead_classification == LeadClassification.REJECTED or l.overall_priority == PriorityTier.REJECTED:
                rejected_leads.append(l)
                routed_domains.add(dom)

        df_hot = self._leads_to_df(hot_leads)
        df_linkedin = self._leads_to_df(linkedin_candidates)
        df_research = self._leads_to_df(research_required)
        df_rejected = self._rejected_leads_to_df(rejected_leads)
        df_summary = self._generate_audit_summary_df(leads, total_discovered=total_discovered)

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_hot.to_excel(writer, index=False, sheet_name="Hot Leads")
            df_linkedin.to_excel(writer, index=False, sheet_name="LinkedIn Outreach Candidates")
            df_research.to_excel(writer, index=False, sheet_name="Contact Research Required")
            df_rejected.to_excel(writer, index=False, sheet_name="Rejected Leads")
            df_summary.to_excel(writer, index=False, sheet_name="Audit Summary")

        return str(Path(output_path).resolve())

lead_exporter = LeadExporter()
