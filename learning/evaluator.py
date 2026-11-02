from typing import List, Dict, Any
from core.schemas import LeadRecord, PriorityTier, VerificationStatus
from core.llm_router import llm_router

class PipelineEvaluator:
    def __init__(self):
        pass

    def calculate_metrics(
        self,
        leads: List[LeadRecord],
        total_discovered: int = 0,
        duplicates_removed: int = 0
    ) -> Dict[str, Any]:
        total = len(leads)
        if total == 0:
            return {
                "total_leads": 0,
                "total_discovered": total_discovered,
                "duplicates_removed": duplicates_removed,
                "qualified_count": 0,
                "high_potential_count": 0,
                "rejected_count": 0,
                "qualification_rate": 0.0,
                "email_validity_rate": 0.0,
                "dm_extraction_rate": 0.0,
                "total_estimated_cost_usd": 0.0,
                "cost_per_qualified_lead_usd": 0.0
            }

        high_pot = sum(1 for l in leads if l.overall_priority == PriorityTier.HIGH_POTENTIAL)
        qualified = sum(1 for l in leads if l.overall_priority in (PriorityTier.HIGH_POTENTIAL, PriorityTier.QUALIFIED, PriorityTier.HOT_LEAD))
        rejected = sum(1 for l in leads if l.overall_priority == PriorityTier.REJECTED)
        valid_emails = sum(1 for l in leads if l.email_verification_status in (VerificationStatus.LIKELY_VALID, VerificationStatus.VERIFIED))
        dm_found = sum(1 for l in leads if l.decision_maker_name is not None)

        total_cost = sum(m.cost_estimate_usd for m in llm_router.metrics)
        cpql = (total_cost / qualified) if qualified > 0 else 0.0

        return {
            "total_leads": total,
            "total_discovered": total_discovered or total,
            "duplicates_removed": duplicates_removed,
            "qualified_count": qualified,
            "high_potential_count": high_pot,
            "rejected_count": rejected,
            "qualification_rate": round(qualified / total, 3),
            "email_validity_rate": round(valid_emails / total, 3),
            "dm_extraction_rate": round(dm_found / total, 3),
            "total_estimated_cost_usd": round(total_cost, 4),
            "cost_per_qualified_lead_usd": round(cpql, 4),
            "total_llm_calls": len(llm_router.metrics)
        }

pipeline_evaluator = PipelineEvaluator()

